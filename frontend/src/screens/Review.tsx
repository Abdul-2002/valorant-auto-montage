import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { saveScriptAndRender } from "../api/montage";
import { useProjectStore } from "../state/projectStore";

export function Review() {
  const { taskId = "" } = useParams();
  const nav = useNavigate();
  const script = useProjectStore((s) => s.script);
  const layout = useProjectStore((s) => s.layout);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const clips = (script?.clips || []).filter((c) => c.enabled !== false);
  const dur = clips.reduce((a, c) => {
    const s = c.output_start_sec ?? c.start_sec;
    const e = c.output_end_sec ?? c.end_sec;
    return a + Math.max(0, e - s);
  }, 0);

  async function render() {
    if (!script) return;
    setBusy(true);
    setError("");
    try {
      const next = {
        ...script,
        clips: script.clips.filter((c) => c.enabled !== false),
      };
      const res = await saveScriptAndRender(taskId, next);
      nav(`/jobs/${taskId}/render?rid=${encodeURIComponent(res.render_task_id)}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Render queue failed");
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <h1>Review</h1>
      <p className="muted">Confirm before final MoviePy encode. Preview is approximate for heavy FX.</p>
      <div className="panel" style={{ marginTop: 16, display: "grid", gap: 8 }}>
        <div>Clips: {clips.length}</div>
        <div>Assembled span ≈ {dur.toFixed(1)}s</div>
        <div>Layout: {layout}</div>
        <div>
          Final-only FX: <span style={{ color: "var(--warn)" }}>ghost / gun outline / jigsaw</span>
        </div>
        {error ? <div className="error">{error}</div> : null}
        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <Link className="btn" to={`/jobs/${taskId}/edit`}>
            Back to editor
          </Link>
          <button className="btn btn-primary" type="button" disabled={busy || !clips.length} onClick={() => void render()}>
            {busy ? "Queuing…" : "Render final"}
          </button>
        </div>
      </div>
    </div>
  );
}
