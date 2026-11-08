import { send } from "./http";
import type { Highlight, Layout, MontageScript, Recommendations, TaskListResponse, TaskStatus } from "./types";
import { uploadApiBase } from "./uploadBase";

async function postJson<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const parsed = (await res.json()) as { detail?: string };
      if (parsed.detail) detail = parsed.detail;
    } catch {
      /* keep statusText */
    }
    throw new Error(detail || `Request failed (${res.status})`);
  }
  return (await res.json()) as T;
}

function putFileWithProgress(
  url: string,
  file: File,
  onProgress: (loaded: number) => void
): Promise<{ bytes_written: number }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.upload.onprogress = (ev) => {
      if (ev.lengthComputable) onProgress(ev.loaded);
      else onProgress(ev.loaded);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as { bytes_written: number });
        } catch (e) {
          reject(e instanceof Error ? e : new Error("Bad stage response"));
        }
        return;
      }
      let detail = xhr.statusText;
      try {
        const parsed = JSON.parse(xhr.responseText) as { detail?: string };
        if (parsed.detail) detail = String(parsed.detail);
      } catch {
        /* keep */
      }
      reject(new Error(detail || `Upload failed (${xhr.status})`));
    };
    xhr.onerror = () => reject(new Error("Upload network error — is the API on :8000 up?"));
    xhr.send(file);
  });
}

/**
 * Parallel raw uploads straight to the API, then create the detect task.
 * Avoids Express proxy + multipart spooling for multi‑GB VODs.
 */
export async function createMontage(
  videos: File[],
  music: File,
  onUploadProgress?: (pct: number) => void
): Promise<{ task_id: string }> {
  const base = uploadApiBase();
  const { session_id } = await postJson<{ session_id: string }>(`${base}/montage/stage/session`, {});

  const jobs: { slot: string; file: File }[] = [
    ...videos.map((file, i) => ({ slot: `video_${i}`, file })),
    { slot: "music", file: music },
  ];
  const total = jobs.reduce((sum, j) => sum + j.file.size, 0) || 1;
  const loadedBySlot = new Map<string, number>();

  const report = () => {
    let loaded = 0;
    for (const v of loadedBySlot.values()) loaded += v;
    onUploadProgress?.(Math.min(99, (loaded / total) * 100));
  };

  // Cap concurrency — saturating OneDrive/WSL with 10× parallel multi‑hundred‑MB PUTs is slower.
  const concurrency = 3;
  let next = 0;
  async function worker() {
    while (next < jobs.length) {
      const idx = next++;
      const { slot, file } = jobs[idx];
      const q = new URLSearchParams({ filename: file.name });
      const url = `${base}/montage/stage/${encodeURIComponent(session_id)}/${encodeURIComponent(slot)}?${q}`;
      loadedBySlot.set(slot, 0);
      await putFileWithProgress(url, file, (loaded) => {
        loadedBySlot.set(slot, loaded);
        report();
      });
      loadedBySlot.set(slot, file.size);
      report();
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, jobs.length) }, () => worker()));

  onUploadProgress?.(99);
  const created = await postJson<{ task_id: string }>(`${base}/montage/create-from-stage`, {
    session_id,
    num_videos: videos.length,
  });
  onUploadProgress?.(100);
  return created;
}

export function listTasks(): Promise<TaskListResponse> {
  return send("/montage/tasks");
}

export function getStatus(taskId: string): Promise<TaskStatus> {
  return send(`/montage/${encodeURIComponent(taskId)}/status`);
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

export function getRecommendations(taskId: string, density?: string): Promise<Recommendations> {
  const q = density ? `?density=${encodeURIComponent(density)}` : "";
  return send(`/montage/${encodeURIComponent(taskId)}/recommendations${q}`);
}

export function confirmRecommendations(
  taskId: string,
  playIds: string[],
  density?: string
): Promise<{ task_id: string; play_ids: string[] }> {
  return send(`/montage/${encodeURIComponent(taskId)}/recommendations/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ play_ids: playIds, density }),
  });
}

export function composePreview(
  taskId: string
): Promise<{ task_id: string; clip_count: number; duration_sec: number }> {
  return send(`/montage/${encodeURIComponent(taskId)}/compose`, { method: "POST" });
}

export function getScript(taskId: string): Promise<{ task_id: string; script: MontageScript }> {
  return send(`/montage/${encodeURIComponent(taskId)}/script`);
}

export function saveScript(
  taskId: string,
  script: MontageScript,
  render = false
): Promise<{ task_id: string; saved: boolean; render_task_id: string | null }> {
  return send(`/montage/${encodeURIComponent(taskId)}/script`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ script, render }),
  });
}

export function saveScriptAndRender(
  taskId: string,
  script: MontageScript
): Promise<{ task_id: string; saved: boolean; render_task_id: string | null }> {
  return saveScript(taskId, script, true);
}
