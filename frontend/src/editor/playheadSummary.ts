import type { MontageScript, TimelineProject } from "../api/types";
import { recipeLabel, transitionLabel } from "./fxLabels";

export type PlayheadHit = {
  kind: "clip" | "kill" | "ghost" | "transition" | "text" | "recipe";
  label: string;
  detail: string;
};

function clipSpans(script: MontageScript): { index: number; start: number; end: number }[] {
  const spans: { index: number; start: number; end: number }[] = [];
  (script.clips || []).forEach((c, i) => {
    if (c.enabled === false) return;
    const start = Number(c.output_start_sec ?? 0);
    const end = Number(c.output_end_sec ?? start + Math.max(0.2, c.end_sec - c.start_sec));
    spans.push({ index: i, start, end });
  });
  if (!spans.length) return spans;
  const t0 = Math.min(...spans.map((s) => s.start));
  return spans.map((s) => ({ ...s, start: s.start - t0, end: s.end - t0 }));
}

export function summarizePlayhead(
  script: MontageScript,
  timeline: TimelineProject | null,
  playheadSec: number
): PlayheadHit[] {
  const hits: PlayheadHit[] = [];
  const spans = clipSpans(script);
  const clips = script.clips || [];

  spans.forEach((span) => {
    const c = clips[span.index];
    if (!c) return;
    if (playheadSec < span.start || playheadSec >= span.end) return;
    const i = span.index;

    hits.push({
      kind: "clip",
      label: `Clip #${i + 1} · V${c.video_index}`,
      detail: `${(playheadSec - span.start).toFixed(2)}s into clip · ${c.arc_phase || "build"}`,
    });
    hits.push({
      kind: "recipe",
      label: recipeLabel(c.recipe),
      detail: `hit ${c.hit_style || "flash_blur"}`,
    });

    const kills = c.kill_output_times_sec?.length ? c.kill_output_times_sec : [0];
    kills.forEach((k, ki) => {
      const t = span.start + Number(k);
      if (Math.abs(playheadSec - t) <= 0.4) {
        hits.push({
          kind: "kill",
          label: `Kill hit #${ki + 1}`,
          detail: `at ${t.toFixed(2)}s · ${c.hit_style || "flash_blur"}`,
        });
      }
    });

    if (c.ghost_candidate && playheadSec - span.start < 0.6) {
      hits.push({ kind: "ghost", label: "Ghost freeze", detail: "full bake on Export" });
    }
    if (c.gun_candidate) {
      const killT = span.start + Number(c.kill_output_times_sec?.[0] ?? 0.8);
      if (Math.abs(playheadSec - killT) <= 1.2) {
        hits.push({ kind: "ghost", label: "Weapon glow", detail: "preview stand-in · full bake on Export" });
      }
    }

    const tr = c.transition_to_next;
    if (tr?.type) {
      const trDur = Math.max(0.35, Number(tr.duration_sec || 0.45));
      if (playheadSec >= span.end - trDur && playheadSec <= span.end + 0.05) {
        hits.push({
          kind: "transition",
          label: transitionLabel(tr.type),
          detail: `${trDur.toFixed(2)}s into next clip`,
        });
      }
    }
  });

  for (const t of timeline?.tracks.text || []) {
    if (playheadSec >= t.start_sec && playheadSec < t.end_sec) {
      hits.push({ kind: "text", label: t.label, detail: t.text || "" });
    }
  }
  return hits;
}
