import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { getStatus, listTasks } from "../api/montage";
import type { TaskStatus, TaskSummary } from "../api/types";
import { useProjectStore } from "../state/projectStore";
import { PipelineSteps } from "./PipelineSteps";
import { ProgressBar } from "./ProgressBar";
import {
  artifactProgressPercent,
  editorHref,
  isLiveState,
  liveProgressPercent,
  resumeHref,
  statusLabel,
  stepsDoneLabel,
} from "./jobProgress";

type ContainerInfo = {
  id: string;
  name: string;
  image: string;
  state: string;
};

function useSse(url: string | null, onMessage: (data: string) => void) {
  useEffect(() => {
    if (!url) return;
    const es = new EventSource(url);
    es.onmessage = (ev) => onMessage(ev.data);
    es.onerror = () => undefined;
    return () => es.close();
  }, [url, onMessage]);
}

function LogPane(props: { title: string; sseUrl: string | null; heightPx?: number }) {
  const { title, sseUrl, heightPx = 420 } = props;
  const [lines, setLines] = useState<string[]>([]);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const scrollerRef = useRef<HTMLPreElement | null>(null);

  useEffect(() => {
    setLines([]);
    setIsAtBottom(true);
  }, [sseUrl]);

  useSse(sseUrl, (data) => {
    setLines((prev) => {
      const next = prev.length > 2000 ? prev.slice(-1200) : prev.slice();
      next.push(data);
      return next;
    });
  });

  useEffect(() => {
    const el = scrollerRef.current;
    if (!el || !isAtBottom) return;
    el.scrollTop = el.scrollHeight;
  }, [lines, isAtBottom]);

  return (
    <section style={styles.pane}>
      <div style={styles.paneHeader}>
        <div style={styles.paneTitle}>{title}</div>
        <div style={styles.paneHint}>{isAtBottom ? "Following" : "Paused (scroll to bottom to resume)"}</div>
      </div>
      <pre
        ref={scrollerRef}
        style={{ ...styles.paneBody, height: heightPx }}
        onScroll={(event) => {
          const el = event.currentTarget;
          const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
          setIsAtBottom(distance < 24);
        }}
      >
        {lines.length ? lines.join("\n") : sseUrl ? "Waiting for logs…" : ""}
      </pre>
    </section>
  );
}

function TaskProgressPanel({ taskId }: { taskId: string }) {
  const setTaskId = useProjectStore((s) => s.setTaskId);
  const [task, setTask] = useState<TaskSummary | null>(null);
  const [status, setStatus] = useState<TaskStatus | null>(null);

  useEffect(() => {
    if (!taskId) return;
    let stop = false;
    const tick = async () => {
      try {
        const { tasks } = await listTasks();
        const found = tasks.find((t) => t.task_id === taskId) ?? null;
        let nextStatus: TaskStatus | null = null;
        try {
          nextStatus = await getStatus(taskId);
        } catch {
          nextStatus = null;
        }
        if (stop) return;
        setTask(found);
        setStatus(nextStatus);
      } catch {
        if (!stop) {
          setTask(null);
          setStatus(null);
        }
      }
    };
    void tick();
    const id = window.setInterval(() => void tick(), 2500);
    return () => {
      stop = true;
      window.clearInterval(id);
    };
  }, [taskId]);

  if (!taskId) return null;

  const live = status ? isLiveState(status.state) : false;
  const pct = task
    ? live
      ? liveProgressPercent(status, artifactProgressPercent(task))
      : artifactProgressPercent(task)
    : status
      ? liveProgressPercent(status, 2)
      : 0;
  const label = task
    ? live
      ? statusLabel(status, task)
      : stepsDoneLabel(task)
    : status
      ? statusLabel(status, {
          task_id: taskId,
          song_name: "",
          num_videos: 0,
          has_highlights: false,
          has_selection: false,
          has_script: false,
          has_outputs: false,
          num_highlights: 0,
          resume_path: "detect",
          mtime: 0,
        })
      : "Loading…";

  return (
    <div className="panel logs-progress" style={{ marginBottom: 12 }}>
      <div className="job-card-top">
        <div>
          <strong>Job progress</strong>
          <div className="muted" style={{ fontSize: 13 }}>
            {taskId.slice(0, 8)}…{task?.song_name ? ` · ${task.song_name}` : ""}
            {task?.num_highlights ? ` · ${task.num_highlights} kills` : ""}
          </div>
        </div>
        {task ? (
          <span className={`job-badge job-badge-${task.resume_path}`}>
            {task.has_outputs ? "done" : task.resume_path}
          </span>
        ) : null}
      </div>
      <ProgressBar percent={pct} label={label} />
      {task ? <PipelineSteps resumePath={task.resume_path} hasOutputs={task.has_outputs} /> : null}
      <div className="job-card-actions" style={{ marginTop: 10 }}>
        {task ? (
          <Link
            className="btn btn-primary"
            to={resumeHref(task.task_id, task.resume_path)}
            onClick={() => setTaskId(task.task_id)}
          >
            Resume
          </Link>
        ) : null}
        {task?.has_script ? (
          <Link className="btn" to={editorHref(task.task_id)} onClick={() => setTaskId(task.task_id)}>
            Open editor
          </Link>
        ) : null}
        <Link className="btn btn-ghost" to="/">
          All projects
        </Link>
      </div>
    </div>
  );
}

export function LogsView() {
  const [searchParams] = useSearchParams();
  const storeTaskId = useProjectStore((s) => s.taskId);
  const queryTask = searchParams.get("task") || storeTaskId;
  const [containers, setContainers] = useState<ContainerInfo[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [tail, setTail] = useState(300);

  useEffect(() => {
    fetch("/api/containers")
      .then((response) => response.json())
      .then((data: { containers?: ContainerInfo[] }) => {
        const list = data.containers ?? [];
        setContainers(list);
        const worker = list.find((c) => c.name.includes("worker"));
        if (worker) setSelectedId((prev) => prev || worker.id);
      })
      .catch(() => setContainers([]));
  }, []);

  const selected = useMemo(
    () => containers.find((container) => container.id === selectedId) ?? null,
    [containers, selectedId]
  );
  const selectedSseUrl = selected
    ? `/api/containers/${encodeURIComponent(selected.id)}/logs?tail=${encodeURIComponent(String(tail))}&follow=1`
    : null;

  return (
    <div className="page">
      <h1>Logs</h1>
      <p className="muted">Live container streams plus pipeline progress for the active job.</p>
      {queryTask ? <TaskProgressPanel taskId={queryTask} /> : null}
      <div style={styles.controls}>
        <label style={styles.label}>
          Container
          <select style={styles.select} value={selectedId} onChange={(event) => setSelectedId(event.target.value)}>
            <option value="" disabled>
              Select a container…
            </option>
            <option value="__all__">All containers (live)</option>
            {containers.map((container) => (
              <option key={container.id} value={container.id}>
                {container.name} ({container.state})
              </option>
            ))}
          </select>
        </label>
        <label style={styles.label}>
          Tail
          <input
            style={styles.input}
            type="number"
            min={10}
            max={2000}
            value={tail}
            onChange={(event) => setTail(Number(event.target.value))}
          />
        </label>
      </div>
      <div style={styles.meta}>
        {selectedId === "__all__" ? (
          <div style={styles.hint}>Showing one live pane per container.</div>
        ) : selected ? (
          <div>
            <div style={styles.metaLine}>
              <span style={styles.metaLabel}>Image</span> {selected.image}
            </div>
            <div style={styles.metaLine}>
              <span style={styles.metaLabel}>State</span> {selected.state}
            </div>
          </div>
        ) : (
          <div style={styles.hint}>Pick a container to start streaming logs.</div>
        )}
      </div>
      {selectedId === "__all__" ? (
        <div style={styles.grid}>
          {containers.map((container) => (
            <LogPane
              key={container.id}
              title={`${container.name} (${container.state})`}
              sseUrl={`/api/containers/${encodeURIComponent(container.id)}/logs?tail=${encodeURIComponent(String(tail))}&follow=1`}
            />
          ))}
        </div>
      ) : (
        <LogPane title={selected ? `${selected.name} (${selected.state})` : "Logs"} sseUrl={selectedSseUrl} heightPx={520} />
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  controls: { display: "flex", gap: 12, alignItems: "end", flexWrap: "wrap", marginBottom: 12 },
  label: { display: "flex", flexDirection: "column", gap: 6, fontSize: 12, opacity: 0.9 },
  select: {
    minWidth: 320,
    background: "#121a29",
    border: "1px solid #22304b",
    color: "#e7edf7",
    padding: "8px 10px",
    borderRadius: 10,
  },
  input: {
    width: 120,
    background: "#121a29",
    border: "1px solid #22304b",
    color: "#e7edf7",
    padding: "8px 10px",
    borderRadius: 10,
  },
  meta: { background: "#0f1624", border: "1px solid #22304b", borderRadius: 12, padding: 12, marginBottom: 12 },
  metaLine: { fontSize: 12, opacity: 0.9, marginBottom: 6 },
  metaLabel: { display: "inline-block", width: 52, opacity: 0.65 },
  hint: { fontSize: 13, opacity: 0.8 },
  grid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(420px, 1fr))", gap: 12 },
  pane: {
    background: "#05070c",
    border: "1px solid #22304b",
    borderRadius: 12,
    overflow: "hidden",
    display: "flex",
    flexDirection: "column",
  },
  paneHeader: {
    padding: "10px 12px",
    borderBottom: "1px solid #22304b",
    background: "#0b1020",
    display: "flex",
    justifyContent: "space-between",
    gap: 10,
  },
  paneTitle: { fontSize: 12, fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" },
  paneHint: { fontSize: 11, opacity: 0.7, whiteSpace: "nowrap" },
  paneBody: { margin: 0, padding: 12, overflow: "auto", whiteSpace: "pre-wrap" },
};
