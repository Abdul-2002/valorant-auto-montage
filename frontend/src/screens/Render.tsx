import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { getOutput, getStatus } from "../api/montage";
import { useProjectStore } from "../state/projectStore";

const DONE = new Set(["SUCCESS", "FAILURE", "REVOKED"]);

export function Render() {
  const { taskId = "" } = useParams();
  const [params] = useSearchParams();
  const rid = params.get("rid") || taskId;
  const layout = useProjectStore((s) => s.layout);
  const [phase, setPhase] = useState("Queued…");
  const [path, setPath] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let stop = false;
    const tick = async () => {
      try {
        const s = await getStatus(rid);
        if (stop) return;
        setPhase(s.phase ? `${s.state} · ${s.phase}` : s.state);
        if (!DONE.has(s.state)) {
          window.setTimeout(() => void tick(), 2000);
          return;
        }
        if (s.state !== "SUCCESS") {
          setError("Render failed");
          return;
        }
        const out = await getOutput(taskId, layout);
        if (!stop) setPath(out.path);
      } catch (e) {
        if (!stop) setError(e instanceof Error ? e.message : "Status failed");
      }
    };
    void tick();
    return () => {
      stop = true;
    };
  }, [rid, taskId, layout]);

  return (
    <div className="page">
      <h1>Render</h1>
      <div className="panel" style={{ marginTop: 16 }}>
        <div>{phase}</div>
        {error ? <div className="error">{error}</div> : null}
        {path ? (
          <div style={{ marginTop: 12 }}>
            <div>Output ready:</div>
            <code>{path}</code>
          </div>
        ) : null}
        <div style={{ marginTop: 12 }}>
          <Link className="btn" to="/">
            Home
          </Link>
        </div>
      </div>
    </div>
  );
}
