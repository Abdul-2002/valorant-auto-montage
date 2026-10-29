import { useEffect, useRef, useState } from "react";

import { confirmHighlights, createMontage, getHighlights, getOutput, getStatus } from "../api/montage";
import type { Highlight, Layout } from "../api/types";
import { YouTubePanel } from "./YouTubePanel";

const TERMINAL = new Set(["SUCCESS", "FAILURE", "REVOKED"]);

export function Studio() {
  const [videos, setVideos] = useState<File[]>([]);
  const [song, setSong] = useState<File | null>(null);
  const [detectId, setDetectId] = useState("");
  const [watchId, setWatchId] = useState("");
  const [watchKind, setWatchKind] = useState<"detect" | "render">("detect");
  const [phase, setPhase] = useState("");
  const [highlights, setHighlights] = useState<Highlight[]>([]);
  const [picked, setPicked] = useState<boolean[]>([]);
  const [layout, setLayout] = useState<Layout>("16:9");
  const [outputPath, setOutputPath] = useState("");
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const detectRef = useRef("");
  const layoutRef = useRef<Layout>("16:9");
  detectRef.current = detectId;
  layoutRef.current = layout;

  useEffect(() => {
    if (!watchId) return;
    const stop = { current: false };
    let timer = 0;
    const tick = async () => {
      try {
        const status = await getStatus(watchId);
        if (stop.current) return;
        setPhase(status.phase ? `${status.state} · ${status.phase}` : status.state);
        if (!TERMINAL.has(status.state)) {
          timer = window.setTimeout(() => void tick(), 2000);
          return;
        }
        if (status.state !== "SUCCESS") {
          setWatchId("");
          setError(status.state === "FAILURE" ? "The job failed. Check the logs." : status.state);
          return;
        }
        await applyResult(watchKind, detectRef.current, layoutRef.current, stop);
        if (!stop.current) setWatchId("");
      } catch (err) {
        if (!stop.current) setError(err instanceof Error ? err.message : "Status check failed");
      }
    };
    void tick();
    return () => {
      stop.current = true;
      window.clearTimeout(timer);
    };
  }, [watchId, watchKind]);

  useEffect(() => {
    if (!ready || !detectId) return;
    let cancel = false;
    void getOutput(detectId, layout)
      .then((body) => {
        if (!cancel) setOutputPath(body.path);
      })
      .catch((err: unknown) => {
        if (!cancel) setError(err instanceof Error ? err.message : "That format is not ready");
      });
    return () => {
      cancel = true;
    };
  }, [ready, detectId, layout]);

  async function applyResult(
    kind: "detect" | "render",
    taskId: string,
    nextLayout: Layout,
    stop: { current: boolean }
  ): Promise<void> {
    if (stop.current || !taskId) return;
    if (kind === "detect") {
      const body = await getHighlights(taskId);
      if (stop.current) return;
      setHighlights(body.highlights);
      setPicked(body.highlights.map(() => true));
      return;
    }
    const body = await getOutput(taskId, nextLayout);
    if (stop.current) return;
    setOutputPath(body.path);
    setReady(true);
  }

  async function start(): Promise<void> {
    if (!videos.length || !song) return;
    setBusy(true);
    setError("");
    setHighlights([]);
    setPicked([]);
    setReady(false);
    setOutputPath("");
    try {
      const created = await createMontage(videos, song);
      setDetectId(created.task_id);
      setWatchKind("detect");
      setWatchId(created.task_id);
      setPhase("queued");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    } finally {
      setBusy(false);
    }
  }

  async function render(): Promise<void> {
    const chosen = highlights.filter((_, index) => picked[index]);
    if (!detectId || !chosen.length) return;
    setBusy(true);
    setError("");
    setReady(false);
    setOutputPath("");
    try {
      const confirmed = await confirmHighlights(detectId, chosen);
      setWatchKind("render");
      setWatchId(confirmed.render_task_id);
      setPhase("rendering");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Render failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={stack}>
      <section style={panel}>
        <h2 style={heading}>Sources</h2>
        <label style={label}>
          Videos
          <input
            style={field}
            type="file"
            accept="video/*"
            multiple
            onChange={(event) => setVideos(Array.from(event.target.files ?? []))}
          />
        </label>
        <p style={hint}>{videos.length ? videos.map((file) => file.name).join(", ") : "No videos selected"}</p>
        <label style={label}>
          Song
          <input style={field} type="file" accept="audio/*" onChange={(event) => setSong(event.target.files?.[0] ?? null)} />
        </label>
        <p style={hint}>{song ? song.name : "No song selected"}</p>
        <button type="button" style={button} disabled={!videos.length || !song || busy} onClick={() => void start()}>
          Create montage
        </button>
        {phase ? <p style={hint}>{phase}</p> : null}
        {detectId ? <p style={hint}>Task {detectId}</p> : null}
        {error ? <p style={errorStyle}>{error}</p> : null}
      </section>

      <section style={panel}>
        <h2 style={heading}>Highlights</h2>
        {highlights.length === 0 ? <p style={hint}>Highlights show up here after detection finishes.</p> : null}
        {highlights.map((item, index) => (
          <label key={`${item.video_index}-${item.timestamp_sec}-${index}`} style={check}>
            <input
              type="checkbox"
              checked={picked[index] ?? false}
              onChange={(event) => {
                const checked = event.target.checked;
                setPicked((current) => current.map((on, i) => (i === index ? checked : on)));
              }}
            />
            <span>
              Video {item.video_index} · {item.timestamp_sec.toFixed(1)}s · {item.event_type} · {item.score.toFixed(2)}
            </span>
          </label>
        ))}
        <button
          type="button"
          style={button}
          disabled={!highlights.some((_, index) => picked[index]) || busy || Boolean(watchId)}
          onClick={() => void render()}
        >
          Render montage
        </button>
        {outputPath ? <p style={hint}>Server file: {outputPath}</p> : null}
        {ready ? <p style={hint}>Montage is ready. Upload it below.</p> : null}
      </section>

      <YouTubePanel taskId={ready ? detectId : null} layout={layout} onLayout={setLayout} />
    </div>
  );
}

const stack: React.CSSProperties = { display: "flex", flexDirection: "column", gap: 12 };
const panel: React.CSSProperties = {
  background: "#0f1624",
  border: "1px solid #22304b",
  borderRadius: 12,
  padding: 16,
  display: "flex",
  flexDirection: "column",
  gap: 10,
};
const heading: React.CSSProperties = { margin: 0, fontSize: 16 };
const hint: React.CSSProperties = { margin: 0, fontSize: 13, opacity: 0.8 };
const label: React.CSSProperties = { display: "flex", flexDirection: "column", gap: 6, fontSize: 12 };
const field: React.CSSProperties = {
  background: "#121a29",
  border: "1px solid #22304b",
  color: "#e7edf7",
  padding: "8px 10px",
  borderRadius: 10,
};
const button: React.CSSProperties = {
  background: "#1e2a44",
  border: "1px solid #2b3a5c",
  color: "#e7edf7",
  padding: "9px 12px",
  borderRadius: 10,
  cursor: "pointer",
  width: "fit-content",
};
const check: React.CSSProperties = { display: "flex", gap: 8, alignItems: "center", fontSize: 13 };
const errorStyle: React.CSSProperties = { margin: 0, color: "#ffb4b4", fontSize: 13 };
