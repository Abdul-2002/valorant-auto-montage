import type { MontageScript, ScriptClip, TimelineOverlay, TimelineProject } from "../api/types";
import { recipeLabel, transitionLabel } from "./fxLabels";

function clipOut(c: ScriptClip): { start: number; end: number } {
  const start = Number(c.output_start_sec ?? 0);
  const end = Number(c.output_end_sec ?? start + Math.max(0.2, c.end_sec - c.start_sec));
  return { start, end };
}

/** Map AI MontageScript + studio options onto a Pro-style multi-track timeline. */
export function buildTimelineFromScript(
  script: MontageScript,
  opts: {
    titleText?: string;
    songName?: string;
    engagement?: boolean;
  } = {}
): TimelineProject {
  const clips = script.clips || [];
  const spans = clips.map(clipOut);
  const t0 = spans.length ? Math.min(...spans.map((s) => s.start)) : 0;
  const t1 = spans.length ? Math.max(...spans.map((s) => s.end)) : 0;
  const duration = Math.max(1, t1 - t0);

  const video = clips.map((c, i) => {
    const { start, end } = clipOut(c);
    return {
      id: `vid-${i}`,
      kind: "video" as const,
      label: `Clip ${i + 1} · ${recipeLabel(c.recipe)}`,
      start_sec: start - t0,
      end_sec: end - t0,
      clip_index: i,
      recipe: c.recipe || "clean",
      hit_style: c.hit_style || "flash_blur",
      ghost: Boolean(c.ghost_candidate),
      gun: Boolean(c.gun_candidate),
      color: recipeColor(c.recipe || "clean"),
    };
  });

  const music: TimelineOverlay[] = [
    {
      id: "music-bed",
      kind: "music",
      label: opts.songName ? `♪ ${opts.songName}` : "♪ Music bed",
      start_sec: 0,
      end_sec: duration,
      color: "#3d6bff",
    },
  ];

  const text: TimelineOverlay[] = [];
  const title = (opts.titleText || "").trim();
  if (title) {
    text.push({
      id: "title",
      kind: "text",
      label: `Title: ${title}`,
      start_sec: 0,
      end_sec: Math.min(2.4, duration * 0.15),
      text: title,
      color: "#ff4655",
    });
  }
  if (opts.engagement === true && duration > 8) {
    const mid = duration * 0.45;
    text.push({
      id: "engage-mid",
      kind: "text",
      label: "LIKE / SUB",
      start_sec: mid,
      end_sec: mid + 2,
      text: "LIKE · SUBSCRIBE",
      color: "#f5c542",
    });
    text.push({
      id: "engage-out",
      kind: "text",
      label: "COMMENT",
      start_sec: Math.max(0, duration - 2.2),
      end_sec: duration,
      text: "COMMENT BELOW",
      color: "#f5c542",
    });
  }

  const effects: TimelineOverlay[] = [];
  clips.forEach((c, i) => {
    const { start } = clipOut(c);
    const rel = start - t0;
    const kills = c.kill_output_times_sec?.length
      ? c.kill_output_times_sec
      : [0];
    kills.forEach((k, ki) => {
      const t = rel + Number(k);
      effects.push({
        id: `kill-${i}-${ki}`,
        kind: "effect",
        label: `${c.hit_style || "hit"}`,
        start_sec: t,
        end_sec: t + 0.35,
        clip_index: i,
        color: "#3dffa8",
      });
    });
    if (c.recipe && c.recipe !== "clean") {
      const { end } = clipOut(c);
      effects.push({
        id: `recipe-${i}`,
        kind: "effect",
        label: recipeLabel(c.recipe),
        start_sec: rel,
        end_sec: end - t0,
        clip_index: i,
        color: recipeColor(c.recipe),
      });
    }
    if (c.ghost_candidate) {
      effects.push({
        id: `ghost-${i}`,
        kind: "effect",
        label: "Ghost freeze",
        start_sec: rel,
        end_sec: rel + 0.85,
        clip_index: i,
        color: "#a78bfa",
      });
    }
    if (c.gun_candidate) {
      effects.push({
        id: `gun-${i}`,
        kind: "effect",
        label: "Weapon glow",
        start_sec: rel,
        end_sec: rel + 1.4,
        clip_index: i,
        color: "#f5c542",
      });
    }
    if (c.transition_to_next?.type) {
      const { end } = clipOut(c);
      const trDur = Math.max(0.4, Number(c.transition_to_next.duration_sec || 0.55));
      const trType = String(c.transition_to_next.type);
      effects.push({
        id: `tr-${i}`,
        kind: "effect",
        label: transitionLabel(trType),
        start_sec: Math.max(0, end - t0 - trDur),
        end_sec: end - t0,
        clip_index: i,
        color: trType === "jigsaw" ? "#ff4655" : "#ff8b4a",
      });
    }
  });

  return {
    duration_sec: duration,
    phase_offset_sec: t0,
    tracks: {
      video,
      music,
      text,
      effects,
    },
  };
}

function recipeColor(recipe: string): string {
  switch (recipe) {
    case "slow":
      return "#5b8cff";
    case "punch":
      return "#ff4655";
    case "cinematic":
      return "#c084fc";
    default:
      return "#2b3348";
  }
}
