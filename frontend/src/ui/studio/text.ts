import type { Highlight } from "../../api/types";

export const TERMINAL_STATES = new Set(["SUCCESS", "FAILURE", "REVOKED"]);
export const UPLOAD_DONE = new Set(["uploaded", "failed", "channel_mismatch"]);

export function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

export function phaseText(state: string, phase: string | null): string {
  return phase ? `${state} · ${phase}` : state;
}

export function failureText(state: string): string {
  return state === "FAILURE" ? "The job failed. Check the logs." : state;
}

export function parseTags(raw: string): string[] {
  return raw.split(",").map((tag) => tag.trim()).filter(Boolean);
}

export function fileLabel(files: File[], empty: string): string {
  return files.length ? files.map((file) => file.name).join(", ") : empty;
}

export function highlightLabel(item: Highlight): string {
  return `Video ${item.video_index} · ${item.timestamp_sec.toFixed(1)}s · ${item.event_type} · ${item.score.toFixed(2)}`;
}

export function chosenHighlights(highlights: Highlight[], picked: boolean[]): Highlight[] {
  return highlights.filter((_, index) => picked[index]);
}

export function watchUrl(status: string, videoId: string | null): string {
  if (status !== "uploaded" || !videoId) return "";
  return `https://www.youtube.com/watch?v=${videoId}`;
}

export function toggleAt(picked: boolean[], index: number, checked: boolean): boolean[] {
  return picked.map((on, i) => (i === index ? checked : on));
}
