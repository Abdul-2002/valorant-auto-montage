import type { MontageScript, ScriptClip } from "../api/types";

function sourceDur(c: ScriptClip): number {
  return Math.max(0.2, Number(c.end_sec) - Number(c.start_sec));
}

function recipeStretch(recipe: string | undefined): number {
  switch (recipe) {
    case "slow":
      return 1.35;
    case "punch":
      return 0.88;
    case "cinematic":
      return 1.12;
    default:
      return 1;
  }
}

/** Rebuild contiguous output_start/end after source trim / enable toggles. */
export function retimeScript(script: MontageScript): MontageScript {
  let cursor = 0;
  const clips = script.clips.map((c) => {
    if (c.enabled === false) {
      return { ...c, output_start_sec: cursor, output_end_sec: cursor };
    }
    const src = sourceDur(c);
    const outLen = Math.max(0.2, src * recipeStretch(c.recipe));
    const start = cursor;
    const end = cursor + outLen;
    cursor = end;

    const kills = (c.kill_timestamps_sec?.length ? c.kill_timestamps_sec : [c.kill_timestamp_sec]).map((k) => {
      const rel = Math.max(0, Number(k) - Number(c.start_sec));
      return Math.min(outLen, (rel / src) * outLen);
    });

    return {
      ...c,
      output_start_sec: start,
      output_end_sec: end,
      kill_output_times_sec: kills,
    };
  });
  return { ...script, clips };
}

/** Expand/shrink source windows so assembled span ≈ targetSec (fill the song). */
export function fitScriptToDuration(script: MontageScript, targetSec: number): MontageScript {
  const enabledIdx = script.clips.map((c, i) => (c.enabled === false ? -1 : i)).filter((i) => i >= 0);
  if (!enabledIdx.length || targetSec < 1) return retimeScript(script);

  const timed = retimeScript(script);
  const span = Math.max(
    0.2,
    ...timed.clips.filter((c) => c.enabled !== false).map((c) => Number(c.output_end_sec || 0))
  );
  const scale = targetSec / span;
  const clips = timed.clips.map((c) => {
    if (c.enabled === false) return c;
    const src = sourceDur(c);
    const mid = (Number(c.start_sec) + Number(c.end_sec)) / 2;
    const half = (src * scale) / 2;
    const start = Math.max(0, mid - half);
    const end = Math.max(start + 0.25, mid + half);
    return { ...c, start_sec: start, end_sec: end };
  });
  return retimeScript({ ...timed, clips });
}
