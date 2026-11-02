import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { pingApi } from "../api/http";
import { createMontage } from "../api/montage";
import { useProjectStore } from "../state/projectStore";
import { runAiMontageMaker } from "../studio/runAiMontage";
import { ProgressBar } from "../ui/ProgressBar";

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

export function Upload() {
  const nav = useNavigate();
  const {
    density,
    durationMode,
    layout,
    titleText,
    setDensity,
    setDurationMode,
    setLayout,
    setTitleText,
    setTaskId,
    setSongName,
    applyAiResult,
  } = useProjectStore();
  const [videos, setVideos] = useState<File[]>([]);
  const [song, setSong] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState("");
  const [percent, setPercent] = useState(0);
  const [error, setError] = useState("");
  const [apiOk, setApiOk] = useState<boolean | null>(null);

  const selectedBytes = useMemo(
    () => videos.reduce((a, f) => a + f.size, 0) + (song?.size || 0),
    [videos, song]
  );

  useEffect(() => {
    let cancel = false;
    void pingApi().then((ok) => {
      if (!cancel) setApiOk(ok);
    });
    return () => {
      cancel = true;
    };
  }, []);

  function onProgress(msg: string, pct?: number) {
    setPhase(msg);
    if (typeof pct === "number") setPercent(pct);
  }

  async function startDetectOnly() {
    if (!videos.length || !song) {
      setError("Add at least one video and a song.");
      return;
    }
    setBusy(true);
    setError("");
    setPercent(1);
    setPhase("Uploading…");
    try {
      const { task_id } = await createMontage(videos, song, (pct) => {
        setPhase(`Uploading… ${Math.round(pct)}%`);
        setPercent(pct);
      });
      setTaskId(task_id);
      setSongName(song.name.replace(/\.[^.]+$/, ""));
      setPercent(100);
      nav(`/jobs/${task_id}/detect`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  async function aiMontageMaker() {
    if (!videos.length || !song) {
      setError("Add at least one video and a song.");
      return;
    }
    setBusy(true);
    setError("");
    setPercent(1);
    setPhase("Starting AI Montage Maker…");
    try {
      const result = await runAiMontageMaker(videos, song, {
        density,
        titleText,
        onProgress,
      });
      applyAiResult({
        ...result,
        songName: song.name.replace(/\.[^.]+$/, ""),
      });
      nav(`/jobs/${result.taskId}/edit`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "AI montage failed");
    } finally {
      setBusy(false);
    }
  }

  const canStart = videos.length > 0 && !!song;

  return (
    <div className="page">
      <h1>Upload</h1>
      <p className="muted">
        Files upload in <strong>parallel</strong> straight to the API on <code>:8000</code> (raw stream, not through
        the Express proxy). Progress shows real byte transfer.
      </p>
      <div className="panel" style={{ marginTop: 16, display: "grid", gap: 14 }}>
        <div style={{ color: apiOk === false ? "#ff8b8b" : apiOk ? "var(--accent-2)" : "var(--muted)" }}>
          API: {apiOk === null ? "checking…" : apiOk ? "reachable via /montage proxy" : "unreachable — run docker compose up -d"}
        </div>
        <label>
          Gameplay videos
          <input
            type="file"
            accept="video/*"
            multiple
            disabled={busy}
            onChange={(e) => setVideos(Array.from(e.target.files || []))}
          />
          <div className="muted">{videos.length} file(s)</div>
        </label>
        <label>
          Song
          <input
            type="file"
            accept="audio/*"
            disabled={busy}
            onChange={(e) => setSong(e.target.files?.[0] || null)}
          />
        </label>
        <div className="muted">Selected payload: {formatBytes(selectedBytes)}</div>
        <label>
          Title text
          <input value={titleText} onChange={(e) => setTitleText(e.target.value)} placeholder="Lost SI" />
        </label>
        <label>
          Layout
          <select value={layout} onChange={(e) => setLayout(e.target.value as "16:9" | "9:16")}>
            <option value="16:9">16:9</option>
            <option value="9:16">9:16</option>
          </select>
        </label>
        <label>
          Duration mode
          <select
            value={durationMode}
            onChange={(e) => setDurationMode(e.target.value as "fixed" | "clip_driven")}
          >
            <option value="clip_driven">Clip-driven (recommended)</option>
            <option value="fixed">Fixed target</option>
          </select>
        </label>
        <label>
          Curation density
          <select value={density} onChange={(e) => setDensity(e.target.value as "standard" | "dense")}>
            <option value="standard">Standard</option>
            <option value="dense">Dense</option>
          </select>
        </label>

        {busy || phase ? <ProgressBar percent={percent} label={phase || "Working…"} /> : null}
        {error ? <div className="error">{error}</div> : null}

        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button
            className="btn btn-primary"
            type="button"
            disabled={busy || !canStart}
            onClick={() => void aiMontageMaker()}
          >
            {busy ? "AI working…" : "AI Montage Maker"}
          </button>
          <button className="btn" type="button" disabled={busy || !canStart} onClick={() => void startDetectOnly()}>
            Manual: detect only
          </button>
        </div>
      </div>
    </div>
  );
}
