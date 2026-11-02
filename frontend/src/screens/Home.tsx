import { Link } from "react-router-dom";
import { useProjectStore } from "../state/projectStore";

export function Home() {
  const taskId = useProjectStore((s) => s.taskId);
  return (
    <div className="page">
      <h1>Lost SI Studio</h1>
      <p className="muted">
        One-click <strong>AI Montage Maker</strong> scores kills, lays video + music + titles + FX on the timeline,
        then you preview and render.
      </p>
      <div style={{ display: "flex", gap: 12, marginTop: 20, flexWrap: "wrap" }}>
        <Link className="btn btn-primary" to="/upload">
          AI Montage Maker
        </Link>
        {taskId ? (
          <Link className="btn" to={`/jobs/${taskId}/edit`}>
            Open editor ({taskId.slice(0, 8)}…)
          </Link>
        ) : null}
      </div>
    </div>
  );
}
