import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getStatus, listTasks } from "../api/montage";
import type { TaskStatus, TaskSummary } from "../api/types";
import { useProjectStore } from "../state/projectStore";
import { PipelineSteps } from "../ui/PipelineSteps";
import { ProgressBar } from "../ui/ProgressBar";
import {
  artifactProgressPercent,
  editorHref,
  isLiveState,
  liveProgressPercent,
  resumeHref,
  statusLabel,
  stepsDoneLabel,
} from "../ui/jobProgress";

type Row = {
  task: TaskSummary;
  status: TaskStatus | null;
};

export function Home() {
  const taskId = useProjectStore((s) => s.taskId);
  const setTaskId = useProjectStore((s) => s.setTaskId);
  const [rows, setRows] = useState<Row[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const { tasks } = await listTasks();
      const withStatus = await Promise.all(
        tasks.slice(0, 24).map(async (task) => {
          try {
            const status = await getStatus(task.task_id);
            return { task, status };
          } catch {
            return { task, status: null };
          }
        })
      );
      setRows(withStatus);
      setError("");
      if (!taskId && withStatus[0]) setTaskId(withStatus[0].task.task_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load projects");
    } finally {
      setLoading(false);
    }
  }, [setTaskId, taskId]);

  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => void refresh(), 4000);
    return () => window.clearInterval(id);
  }, [refresh]);

  return (
    <div className="page">
      <div className="projects-hero">
        <div>
          <h1>Lost SI Studio</h1>
          <p className="muted">
            Track detect → select → compose → edit → render. Open the editor on any job that already has a script.
          </p>
        </div>
        <div className="projects-actions">
          <Link className="btn btn-primary" to="/upload">
            AI Montage Maker
          </Link>
          <button className="btn" type="button" onClick={() => void refresh()}>
            Refresh
          </button>
          <Link className="btn btn-ghost" to="/logs">
            Live logs
          </Link>
        </div>
      </div>

      {error ? <div className="error" style={{ marginBottom: 12 }}>{error}</div> : null}
      {loading && !rows.length ? <p className="muted">Loading projects…</p> : null}
      {!loading && !rows.length ? (
        <div className="panel" style={{ marginTop: 12 }}>
          <p className="muted" style={{ margin: 0 }}>
            No montage tasks on disk yet. Start with AI Montage Maker.
          </p>
        </div>
      ) : null}

      <div className="job-grid">
        {rows.map(({ task, status }) => {
          const live = status ? isLiveState(status.state) : false;
          const pct = live
            ? liveProgressPercent(status, artifactProgressPercent(task))
            : artifactProgressPercent(task);
          const label = live ? statusLabel(status, task) : stepsDoneLabel(task);
          return (
            <article key={task.task_id} className={`job-card ${live ? "job-card-live" : ""}`}>
              <div className="job-card-top">
                <div>
                  <div className="job-id">{task.task_id.slice(0, 8)}…</div>
                  <div className="muted" style={{ fontSize: 13 }}>
                    {task.song_name || "Untitled song"} · {task.num_videos} videos
                    {task.num_highlights ? ` · ${task.num_highlights} kills` : ""}
                  </div>
                </div>
                <span className={`job-badge job-badge-${task.resume_path}`}>
                  {task.has_outputs ? "done" : task.resume_path}
                </span>
              </div>
              <ProgressBar percent={pct} label={label} />
              <PipelineSteps resumePath={task.resume_path} hasOutputs={task.has_outputs} />
              <div className="job-card-actions">
                <Link
                  className="btn btn-primary"
                  to={resumeHref(task.task_id, task.resume_path)}
                  onClick={() => setTaskId(task.task_id)}
                >
                  Resume
                </Link>
                {task.has_script ? (
                  <Link className="btn" to={editorHref(task.task_id)} onClick={() => setTaskId(task.task_id)}>
                    Open editor
                  </Link>
                ) : null}
                <Link className="btn btn-ghost" to={`/logs?task=${encodeURIComponent(task.task_id)}`}>
                  Logs
                </Link>
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}
