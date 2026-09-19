import React, { useEffect, useMemo, useRef, useState } from "react";

type ContainerInfo = {
  id: string;
  name: string;
  image: string;
  state: string;
};

function useSse(url: string | null, onMessage: (data: string) => void) {
  useEffect(() => {
    if (!url) return;
    const es = new EventSource(url);
    es.onmessage = (ev) => onMessage(ev.data);
    es.onerror = () => {
      // Let the browser auto-retry.
    };
    return () => es.close();
  }, [url, onMessage]);
}

function LogPane(props: {
  title: string;
  sseUrl: string | null;
  tail: number;
  heightPx?: number;
}) {
  const { title, sseUrl, heightPx = 420 } = props;
  const [lines, setLines] = useState<string[]>([]);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const scrollerRef = useRef<HTMLPreElement | null>(null);

  // Reset lines when stream source changes.
  useEffect(() => {
    setLines([]);
    setIsAtBottom(true);
  }, [sseUrl]);

  useSse(sseUrl, (data) => {
    setLines((prev) => {
      const next = prev.length > 2000 ? prev.slice(-1200) : prev.slice();
      next.push(data);
      return next;
    });
  });

  // Smart follow: only autoscroll if user is already at bottom.
  useEffect(() => {
    const el = scrollerRef.current;
    if (!el || !isAtBottom) return;
    el.scrollTop = el.scrollHeight;
  }, [lines, isAtBottom]);

  return (
    <section style={styles.pane}>
      <div style={styles.paneHeader}>
        <div style={styles.paneTitle}>{title}</div>
        <div style={styles.paneHint}>{isAtBottom ? "Following" : "Paused (scroll to bottom to resume)"}</div>
      </div>
      <pre
        ref={scrollerRef}
        style={{ ...styles.paneBody, height: heightPx }}
        onScroll={(e) => {
          const el = e.currentTarget;
          const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
          setIsAtBottom(distanceToBottom < 24);
        }}
      >
        {lines.length ? lines.join("\n") : sseUrl ? "Waiting for logs…" : ""}
      </pre>
    </section>
  );
}

export function App() {
  const [containers, setContainers] = useState<ContainerInfo[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [tail, setTail] = useState<number>(300);

  useEffect(() => {
    if (window.location.pathname === "/") {
      window.history.replaceState({}, "", "/logs");
    }
  }, []);

  useEffect(() => {
    fetch("/api/containers")
      .then((r) => r.json())
      .then((data) => setContainers(data.containers ?? []))
      .catch(() => setContainers([]));
  }, []);

  const selected = useMemo(
    () => containers.find((c) => c.id === selectedId) ?? null,
    [containers, selectedId]
  );

  const selectedSseUrl = selected
    ? `/api/containers/${encodeURIComponent(selected.id)}/logs?tail=${encodeURIComponent(
        String(tail)
      )}&follow=1`
    : null;

  return (
    <div style={styles.page}>
      <header style={styles.header}>
        <div>
          <div style={styles.title}>Valorant Montage Bot</div>
          <div style={styles.subtitle}>Logs viewer (frontend skeleton)</div>
        </div>
        <a style={styles.link} href="http://localhost:8000/docs" target="_blank" rel="noreferrer">
          API docs
        </a>
      </header>

      <div style={styles.controls}>
        <label style={styles.label}>
          Container
          <select
            style={styles.select}
            value={selectedId}
            onChange={(e) => {
              setSelectedId(e.target.value);
            }}
          >
            <option value="" disabled>
              Select a container…
            </option>
            <option value="__all__">All containers (live)</option>
            {containers.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} ({c.state})
              </option>
            ))}
          </select>
        </label>

        <label style={styles.label}>
          Tail
          <input
            style={styles.input}
            type="number"
            min={10}
            max={2000}
            value={tail}
            onChange={(e) => setTail(Number(e.target.value))}
          />
        </label>

        {/* Clear is per-pane now */}
      </div>

      <div style={styles.meta}>
        {selectedId === "__all__" ? (
          <div style={styles.hint}>
            Showing one live pane per container. Each pane only autoscrolls while you stay at the bottom.
          </div>
        ) : selected ? (
          <div>
            <div style={styles.metaLine}>
              <span style={styles.metaLabel}>Image</span> {selected.image}
            </div>
            <div style={styles.metaLine}>
              <span style={styles.metaLabel}>State</span> {selected.state}
            </div>
          </div>
        ) : (
          <div style={styles.hint}>Pick a container to start streaming logs.</div>
        )}
      </div>

      {selectedId === "__all__" ? (
        <div style={styles.grid}>
          {containers.map((c) => (
            <LogPane
              key={c.id}
              title={`${c.name} (${c.state})`}
              tail={tail}
              sseUrl={`/api/containers/${encodeURIComponent(c.id)}/logs?tail=${encodeURIComponent(
                String(tail)
              )}&follow=1`}
            />
          ))}
        </div>
      ) : (
        <LogPane title={selected ? `${selected.name} (${selected.state})` : "Logs"} tail={tail} sseUrl={selectedSseUrl} heightPx={620} />
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  page: {
    fontFamily:
      'ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Cantarell, Noto Sans, sans-serif',
    background: "#0b0f17",
    color: "#e7edf7",
    minHeight: "100vh",
    padding: 16
  },
  header: {
    display: "flex",
    alignItems: "baseline",
    justifyContent: "space-between",
    marginBottom: 16
  },
  title: { fontSize: 20, fontWeight: 800, letterSpacing: 0.2 },
  subtitle: { fontSize: 12, opacity: 0.7 },
  link: { color: "#8dd3ff", textDecoration: "none", fontSize: 13 },
  controls: {
    display: "flex",
    gap: 12,
    alignItems: "end",
    flexWrap: "wrap",
    marginBottom: 12
  },
  label: { display: "flex", flexDirection: "column", gap: 6, fontSize: 12, opacity: 0.9 },
  select: {
    minWidth: 320,
    background: "#121a29",
    border: "1px solid #22304b",
    color: "#e7edf7",
    padding: "8px 10px",
    borderRadius: 10
  },
  input: {
    width: 120,
    background: "#121a29",
    border: "1px solid #22304b",
    color: "#e7edf7",
    padding: "8px 10px",
    borderRadius: 10
  },
  button: {
    background: "#1e2a44",
    border: "1px solid #2b3a5c",
    color: "#e7edf7",
    padding: "9px 12px",
    borderRadius: 10,
    cursor: "pointer"
  },
  meta: {
    background: "#0f1624",
    border: "1px solid #22304b",
    borderRadius: 12,
    padding: 12,
    marginBottom: 12
  },
  metaLine: { fontSize: 12, opacity: 0.9, marginBottom: 6 },
  metaLabel: { display: "inline-block", width: 52, opacity: 0.65 },
  hint: { fontSize: 13, opacity: 0.8 },
  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(420px, 1fr))",
    gap: 12
  },
  pane: {
    background: "#05070c",
    border: "1px solid #22304b",
    borderRadius: 12,
    overflow: "hidden",
    display: "flex",
    flexDirection: "column"
  },
  paneHeader: {
    padding: "10px 12px",
    borderBottom: "1px solid #22304b",
    background: "#0b1020",
    display: "flex",
    justifyContent: "space-between",
    gap: 10
  },
  paneTitle: { fontSize: 12, fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" },
  paneHint: { fontSize: 11, opacity: 0.7, whiteSpace: "nowrap" },
  paneBody: {
    margin: 0,
    padding: 12,
    overflow: "auto",
    whiteSpace: "pre-wrap"
  }
};
