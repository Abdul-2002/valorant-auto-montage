import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getStatus } from "../api/montage";
import { ProgressBar } from "../ui/ProgressBar";

const DONE = new Set(["SUCCESS", "FAILURE", "REVOKED"]);

export function Detect() {
  const { taskId = "" } = useParams();
  const nav = useNavigate();
  const [phase, setPhase] = useState("Starting…");
  const [percent, setPercent] = useState(2);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!taskId) return;
    let stop = false;
    const tick = async () => {
      try {
        const s = await getStatus(taskId);
        if (stop) return;
        setPhase(s.phase ? `${s.state} · ${s.phase}` : s.state);
        setPercent(Math.max(2, Math.min(100, Number(s.progress || 0) * 100)));
        if (!DONE.has(s.state)) {
          window.setTimeout(() => void tick(), 1500);
          return;
        }
        if (s.state !== "SUCCESS") {
          setError(s.state === "FAILURE" ? "Detection failed" : s.state);
          return;
        }
        setPercent(100);
        nav(`/jobs/${taskId}/select`);
      } catch (e) {
        if (!stop) setError(e instanceof Error ? e.message : "Status failed");
      }
    };
    void tick();
    return () => {
      stop = true;
    };
  }, [taskId, nav]);

  return (
    <div className="page">
      <h1>Detecting highlights</h1>
      <p className="muted">Task {taskId}</p>
      <div className="panel" style={{ marginTop: 16, display: "grid", gap: 12 }}>
        <ProgressBar percent={percent} label={phase} />
        {error ? <div className="error">{error}</div> : null}
      </div>
    </div>
  );
}
