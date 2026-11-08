import type { TaskStatus, TaskSummary } from "../api/types";

export const PIPELINE_STEPS = [
  { id: "detect", label: "Detect" },
  { id: "select", label: "Select" },
  { id: "compose", label: "Compose" },
  { id: "edit", label: "Edit" },
  { id: "review", label: "Review" },
  { id: "render", label: "Render" },
] as const;

export type PipelineStepId = (typeof PIPELINE_STEPS)[number]["id"];

const STEP_INDEX: Record<string, number> = Object.fromEntries(
  PIPELINE_STEPS.map((step, index) => [step.id, index])
);

export function pipelineIndex(resumePath: string): number {
  return STEP_INDEX[resumePath] ?? 0;
}

/** Artifact-based progress 0–100 when Celery is idle. */
export function artifactProgressPercent(task: TaskSummary): number {
  const idx = pipelineIndex(task.resume_path);
  if (task.has_outputs) return 100;
  const denom = PIPELINE_STEPS.length - 1;
  return Math.round((idx / denom) * 100);
}

export function stepsDoneLabel(task: TaskSummary): string {
  const idx = pipelineIndex(task.resume_path);
  const remaining = Math.max(0, PIPELINE_STEPS.length - 1 - idx);
  if (task.has_outputs) return "Complete — all stages done";
  return `${idx} of ${PIPELINE_STEPS.length - 1} stages done · ${remaining} remaining`;
}

/** Idle strip copy — must not look like a hung Celery percent. */
export function idleStageLabel(task: TaskSummary): string {
  if (task.has_outputs) return "Complete";
  const idx = pipelineIndex(task.resume_path);
  const total = PIPELINE_STEPS.length - 1;
  return `Waiting on you · ${task.resume_path} (${idx}/${total} stages)`;
}

export function resumeHref(taskId: string, resumePath: string): string {
  const step = STEP_INDEX[resumePath] != null ? resumePath : "detect";
  return `/jobs/${encodeURIComponent(taskId)}/${step}`;
}

export function editorHref(taskId: string): string {
  return `/jobs/${encodeURIComponent(taskId)}/edit`;
}

const LIVE = new Set(["PENDING", "STARTED", "RETRY", "PROGRESS"]);

export function isLiveState(state: string): boolean {
  return LIVE.has(state);
}

export function liveProgressPercent(status: TaskStatus | null, fallback: number): number {
  if (!status) return fallback;
  if (status.state === "SUCCESS") return Math.max(fallback, 100);
  const raw = Math.max(0, Math.min(100, Number(status.progress || 0) * 100));
  return Math.max(2, raw || fallback);
}

export function statusLabel(status: TaskStatus | null, task: TaskSummary): string {
  if (!status) return `Resume at ${task.resume_path}`;
  if (status.phase) return `${status.state} · ${status.phase}`;
  return status.state;
}
