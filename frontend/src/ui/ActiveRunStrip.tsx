import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { getStatus, listTasks } from "../api/montage";
import type { TaskStatus, TaskSummary } from "../api/types";
import { useProjectStore } from "../state/projectStore";
import {
  artifactProgressPercent,
  editorHref,
  idleStageLabel,
  isLiveState,
  liveProgressPercent,
  resumeHref,
  statusLabel,
} from "./jobProgress";

type Active = {
  task: TaskSummary;
  status: TaskStatus | null;
};

export function ActiveRunStrip() {
  const location = useLocation();
  const storeTaskId = useProjectStore((s) => s.taskId);
  const setTaskId = useProjectStore((s) => s.setTaskId);
  const [active, setActive] = useState<Active | null>(null);

  useEffect(() => {
    let stop = false;
    const tick = async () => {
      try {
        const { tasks } = await listTasks();
        if (stop || !tasks.length) {
          if (!stop) setActive(null);
          return;
        }
        const preferred =
          tasks.find((t) => t.task_id === storeTaskId) ||
          tasks.find((t) => !t.has_outputs) ||
          tasks[0];
        let status: TaskStatus | null = null;
        try {
          status = await getStatus(preferred.task_id);
        } catch {
          status = null;
        }
        if (stop) return;
        const live = status ? isLiveState(status.state) : false;
        if (!live && preferred.has_outputs && preferred.task_id !== storeTaskId) {
          setActive(null);
          return;
        }
        setActive({ task: preferred, status });
      } catch {
        if (!stop) setActive(null);
      }
    };
    void tick();
    const id = window.setInterval(() => void tick(), 3000);
    return () => {
      stop = true;
      window.clearInterval(id);
    };
  }, [storeTaskId]);

  if (!active) return null;

  // Editor / review / render need the viewport — strip belongs on hub pages only.
  // (Shell also gates this; keep the guard if the strip is reused elsewhere.)
  if (/\/jobs\/[^/]+\/(edit|review|render|select)/.test(location.pathname)) {
    return null;
  }

  const { task, status } = active;
  const live = status ? isLiveState(status.state) : false;
  // Celery SUCCESS on detect looks "done" but montage still needs edit/render —
  // only treat as live while worker is actually running.
  const pct = live
    ? liveProgressPercent(status, artifactProgressPercent(task))
    : artifactProgressPercent(task);
  const label = live ? statusLabel(status, task) : idleStageLabel(task);

  return (
    <div className={`active-run ${live ? "active-run-live" : ""}`} role="status">
      <div className="active-run-main">
        <strong>{live ? "Running" : "Waiting on you"}</strong>
        <span className="muted">
          {task.task_id.slice(0, 8)}… · {task.song_name || "song"} · {label}
          {live ? ` · ${Math.round(pct)}%` : ""}
        </span>
        <div className="active-run-track" aria-hidden>
          <div
            className={`active-run-fill ${live ? "" : "active-run-fill-idle"}`}
            style={{ width: `${Math.max(2, Math.min(100, pct))}%` }}
          />
        </div>
      </div>
      <div className="active-run-links">
        <Link
          className="btn btn-ghost"
          to={resumeHref(task.task_id, task.resume_path)}
          onClick={() => setTaskId(task.task_id)}
        >
          Open stage
        </Link>
        {task.has_script ? (
          <Link className="btn" to={editorHref(task.task_id)} onClick={() => setTaskId(task.task_id)}>
            Editor
          </Link>
        ) : null}
        <Link className="btn btn-ghost" to={`/logs?task=${encodeURIComponent(task.task_id)}`}>
          Logs
        </Link>
      </div>
    </div>
  );
}
