import { send } from "./http";
import type { Highlight, Layout } from "./types";

export function createMontage(videos: File[], music: File): Promise<{ task_id: string }> {
  const body = new FormData();
  for (const video of videos) body.append("videos", video, video.name);
  body.append("music", music, music.name);
  return send("/montage/create", { method: "POST", body });
}

export function getStatus(taskId: string) {
  return send<import("./types").TaskStatus>(`/montage/${encodeURIComponent(taskId)}/status`);
}

export function getHighlights(taskId: string): Promise<{ highlights: Highlight[] }> {
  return send(`/montage/${encodeURIComponent(taskId)}/highlights`);
}

export function confirmHighlights(taskId: string, highlights: Highlight[]): Promise<{ render_task_id: string }> {
  return send(`/montage/${encodeURIComponent(taskId)}/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ highlights }),
  });
}

export function getOutput(taskId: string, format: Layout): Promise<{ path: string }> {
  const query = new URLSearchParams({ format });
  return send(`/montage/${encodeURIComponent(taskId)}/download?${query}`);
}
