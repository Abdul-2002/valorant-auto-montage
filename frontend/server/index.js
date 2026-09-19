import express from "express";
import Docker from "dockerode";
import path from "path";
import fs from "fs";

const app = express();
const docker = new Docker({ socketPath: "/var/run/docker.sock" });

const PORT = Number(process.env.PORT || 3000);
const NAME_PREFIX = process.env.CONTAINER_NAME_PREFIX || "valorant-montage-bot-";

function normalizeName(n) {
  if (!n) return "";
  return n.startsWith("/") ? n.slice(1) : n;
}

function setSseHeaders(res) {
  res.setHeader("Content-Type", "text/event-stream; charset=utf-8");
  res.setHeader("Cache-Control", "no-cache, no-transform");
  res.setHeader("Connection", "keep-alive");
  res.flushHeaders?.();
}

function createLineEmitter(res, { prefix = "" } = {}) {
  return (line) => {
    const safe = String(line).replace(/\r?\n$/, "");
    const out = prefix ? `${prefix} ${safe}` : safe;
    res.write(`data: ${out}\n\n`);
  };
}

function attachDockerLogsToSse({ container, res, tail, follow, prefix }) {
  return container
    .logs({
      stdout: true,
      stderr: true,
      timestamps: false,
      tail,
      follow
    })
    .then((stream) => {
      const sendLine = createLineEmitter(res, { prefix });

      const emitFromBuffer = (b) => {
        let local = Buffer.from(b);
        const texts = [];
        // Try demux repeatedly.
        while (local.length >= 8) {
          const type = local.readUInt8(0);
          const size = local.readUInt32BE(4);
          const isMux = (type === 1 || type === 2) && local.length >= 8 + size;
          if (!isMux) break;
          const payload = local.slice(8, 8 + size);
          local = local.slice(8 + size);
          texts.push(payload.toString("utf8"));
        }
        if (texts.length) {
          for (const t of texts.join("").split(/\\r?\\n/)) {
            if (t.length) sendLine(t);
          }
          return;
        }
        // Fallback: not muxed.
        for (const t of local.toString("utf8").split(/\\r?\\n/)) {
          if (t.length) sendLine(t);
        }
      };

      // dockerode returns a Buffer when follow=false in some environments.
      if (Buffer.isBuffer(stream)) {
        emitFromBuffer(stream);
        return { destroy() {} };
      }

      let buf = Buffer.alloc(0);
      const tryEmitLines = (text) => {
        const parts = text.split(/\r?\n/);
        for (const p of parts) {
          if (p.length) sendLine(p);
        }
      };

      stream.on("data", (chunk) => {
        buf = Buffer.concat([buf, chunk]);
        while (buf.length >= 8) {
          const type = buf.readUInt8(0);
          const size = buf.readUInt32BE(4);
          const isMux = (type === 1 || type === 2) && buf.length >= 8 + size;
          if (!isMux) break;
          const payload = buf.slice(8, 8 + size);
          buf = buf.slice(8 + size);
          tryEmitLines(payload.toString("utf8"));
        }
        if (buf.length && buf.length < 8) return;
        if (buf.length && buf.length >= 8) {
          tryEmitLines(buf.toString("utf8"));
          buf = Buffer.alloc(0);
        }
      });

      return stream;
    });
}

app.get("/api/containers", async (_req, res) => {
  try {
    const list = await docker.listContainers({ all: true });
    const containers = list
      .map((c) => {
        const name = normalizeName((c.Names || [])[0] || "");
        return {
          id: c.Id,
          name,
          image: c.Image,
          state: c.State || c.Status || "unknown"
        };
      })
      .filter((c) => c.name.startsWith(NAME_PREFIX))
      .sort((a, b) => a.name.localeCompare(b.name));
    res.json({ containers });
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

app.get("/api/logs", async (req, res) => {
  const tail = Math.max(1, Math.min(2000, Number(req.query.tail || 300)));
  const follow = String(req.query.follow || "0") === "1";

  setSseHeaders(res);

  let list;
  try {
    list = await docker.listContainers({ all: true });
  } catch (e) {
    res.write(`event: error\ndata: ${JSON.stringify({ error: String(e) })}\n\n`);
    res.end();
    return;
  }

  const targets = list
    .map((c) => ({ id: c.Id, name: normalizeName((c.Names || [])[0] || "") }))
    .filter((c) => c.name.startsWith(NAME_PREFIX))
    .sort((a, b) => a.name.localeCompare(b.name));

  const streams = [];
  for (const t of targets) {
    try {
      const s = await attachDockerLogsToSse({
        container: docker.getContainer(t.id),
        res,
        tail,
        follow,
        prefix: `[${t.name}]`
      });
      streams.push(s);
    } catch (e) {
      res.write(`data: [${t.name}] (error attaching logs: ${String(e)})\n\n`);
    }
  }

  const end = () => {
    for (const s of streams) {
      try {
        s.destroy?.();
      } catch {}
    }
    res.end();
  };

  req.on("close", end);
});

app.get("/api/containers/:id/logs", async (req, res) => {
  const id = req.params.id;
  const tail = Math.max(1, Math.min(2000, Number(req.query.tail || 300)));
  const follow = String(req.query.follow || "0") === "1";

  setSseHeaders(res);

  const container = docker.getContainer(id);

  let stream;
  try {
    stream = await attachDockerLogsToSse({ container, res, tail, follow, prefix: "" });
  } catch (e) {
    res.write(`event: error\ndata: ${JSON.stringify({ error: String(e) })}\n\n`);
    res.end();
    return;
  }

  const end = () => {
    try {
      stream.destroy?.();
    } catch {}
    res.end();
  };

  req.on("close", end);
  stream.on("end", end);
  stream.on("error", end);
});

// Serve built frontend if present; otherwise show a helpful message.
const distDir = path.resolve(process.cwd(), "dist");
if (fs.existsSync(distDir)) {
  app.use(express.static(distDir));
  app.get("/", (_req, res) => res.redirect(302, "/logs"));
  app.get("*", (_req, res) => res.sendFile(path.join(distDir, "index.html")));
} else {
  app.get("/", (_req, res) => {
    res.type("text/plain").send("Frontend not built. In dev: run `npm run dev`.");
  });
}

app.listen(PORT, "0.0.0.0", () => {
  // eslint-disable-next-line no-console
  console.log(`frontend listening on :${PORT}`);
});
