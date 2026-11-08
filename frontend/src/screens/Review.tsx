import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { saveScript, saveScriptAndRender } from "../api/montage";
import { buildTimelineFromScript } from "../editor/buildTimeline";
import { SequencePlayer } from "../editor/SequencePlayer";
import { useProjectStore } from "../state/projectStore";

export function Review() {
  const { taskId = "" } = useParams();
  const nav = useNavigate();
  const script = useProjectStore((s) => s.script);
  const layout = useProjectStore((s) => s.layout);
  const titleText = useProjectStore((s) => s.titleText);
  const songName = useProjectStore((s) => s.songName);
  const setActiveClip = useProjectStore((s) => s.setActiveClip);
  const activeClip = useProjectStore((s) => s.activeClip);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [showPreview, setShowPreview] = useState(true);
  const [playheadSec, setPlayheadSec] = useState(0);

  const clips = (script?.clips || []).filter((c) => c.enabled !== false);
  const timeline = script
    ? buildTimelineFromScript(script, { titleText, songName, engagement: true })
    : null;
  const dur = clips.reduce((a, c) => {
    const s = c.output_start_sec ?? c.start_sec;
    const e = c.output_end_sec ?? c.end_sec;
    return Math.max(a, Number(e));
  }, 0);

  async function finalRender() {
    if (!script) return;
    setBusy(true);
    setError("");
    try {
      await saveScript(taskId, script, false);
      const next = {
        ...script,
        clips: script.clips.filter((c) => c.enabled !== false),
      };
      const res = await saveScriptAndRender(taskId, next);
      if (!res.render_task_id) throw new Error("Render did not queue");
      nav(`/jobs/${taskId}/render?rid=${encodeURIComponent(res.render_task_id)}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Render queue failed");
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <h1>Review</h1>
      <p className="muted">
        You have the final say: keep editing, scrub the studio preview, or queue the full MoviePy render (all FX).
      </p>
      <div className="panel" style={{ marginTop: 16, display: "grid", gap: 10 }}>
        <div>Clips: {clips.length}</div>
        <div>Assembled span ≈ {dur.toFixed(1)}s</div>
        <div>Layout: {layout}</div>
        <div>
          Final-only FX: <span style={{ color: "var(--warn)" }}>ghost cutouts · gun outline · jigsaw</span>
        </div>
        {error ? <div className="error">{error}</div> : null}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 4 }}>
          <Link className="btn" to={`/jobs/${taskId}/edit`}>
            Back to editor
          </Link>
          <button className="btn" type="button" onClick={() => setShowPreview((v) => !v)}>
            {showPreview ? "Hide preview" : "Show preview"}
          </button>
          <button className="btn btn-primary" type="button" disabled={busy || !clips.length} onClick={() => void finalRender()}>
            {busy ? "Queuing…" : "Final render"}
          </button>
        </div>
      </div>
      {showPreview && script && timeline ? (
        <div className="panel review-preview" style={{ marginTop: 16, padding: 0, overflow: "hidden" }}>
          <div style={{ padding: "10px 12px", borderBottom: "1px solid var(--border)" }}>
            <strong>Studio preview</strong>
            <span className="muted"> — sequence + music + markers (not final bake)</span>
          </div>
          <div className="review-preview" style={{ minHeight: 420, padding: 12 }}>
            <SequencePlayer
              taskId={taskId}
              script={script}
              timeline={timeline}
              activeClip={activeClip}
              onActiveClip={setActiveClip}
              playheadSec={playheadSec}
              onPlayhead={setPlayheadSec}
            />
          </div>
        </div>
      ) : null}
    </div>
  );
}
