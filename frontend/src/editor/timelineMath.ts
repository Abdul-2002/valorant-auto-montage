import type { ScriptClip } from "../api/types";

export function sourceDur(c: ScriptClip): number {
  return Math.max(0.25, Number(c.end_sec) - Number(c.start_sec));
}

export function outputDur(c: ScriptClip): number {
  const start = Number(c.output_start_sec ?? 0);
  const end = Number(c.output_end_sec ?? start + sourceDur(c));
  return Math.max(0.25, end - start);
}

/** Timeline seconds → source seconds for this clip's stretch. */
export function timelineDeltaToSource(c: ScriptClip, timelineDelta: number): number {
  const stretch = outputDur(c) / sourceDur(c);
  return timelineDelta / Math.max(0.05, stretch);
}
