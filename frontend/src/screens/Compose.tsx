import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { composePreview } from "../api/montage";

export function Compose() {
  const { taskId = "" } = useParams();
  const nav = useNavigate();
  const [msg, setMsg] = useState("Building montage script…");
  const [error, setError] = useState("");

  useEffect(() => {
    let cancel = false;
    void composePreview(taskId)
      .then((r) => {
        if (cancel) return;
        setMsg(`${r.clip_count} clips · ${r.duration_sec.toFixed(1)}s`);
        nav(`/jobs/${taskId}/edit`);
      })
      .catch((e: unknown) => {
        if (!cancel) setError(e instanceof Error ? e.message : "Compose failed");
      });
    return () => {
      cancel = true;
    };
  }, [taskId, nav]);

  return (
    <div className="page">
      <h1>Compose</h1>
      <div className="panel">{error ? <span className="error">{error}</span> : msg}</div>
    </div>
  );
}
