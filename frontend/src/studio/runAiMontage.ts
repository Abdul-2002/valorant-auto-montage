import {
  composePreview,
  confirmRecommendations,
  createMontage,
  getRecommendations,
  getScript,
  getStatus,
} from "../api/montage";
import type { MontageScript, TimelineProject } from "../api/types";
import { buildTimelineFromScript } from "../editor/buildTimeline";

const DONE = new Set(["SUCCESS", "FAILURE", "REVOKED"]);

export type AiMontageProgress = (msg: string, percent?: number) => void;

function mapDetectPercent(progress: number): number {
  const p = Math.max(0, Math.min(1, progress));
  return 8 + p * 62;
}

async function waitTask(taskId: string, onProgress?: AiMontageProgress): Promise<void> {
  for (;;) {
    const s = await getStatus(taskId);
    const pct = mapDetectPercent(Number(s.progress || 0));
    const label = s.phase ? `${s.state} · ${s.phase}` : s.state;
    onProgress?.(label, pct);
    if (DONE.has(s.state)) {
      if (s.state !== "SUCCESS") throw new Error(`Job failed: ${s.state}`);
      return;
    }
    await new Promise((r) => setTimeout(r, 1500));
  }
}

export type AiMontageResult = {
  taskId: string;
  script: MontageScript;
  timeline: TimelineProject;
};

export async function runAiMontageFromTask(
  taskId: string,
  opts: {
    density?: string;
    titleText?: string;
    songName?: string;
    onProgress?: AiMontageProgress;
  } = {}
): Promise<AiMontageResult> {
  const onProgress = opts.onProgress;
  onProgress?.("Waiting for detect…", 8);
  await waitTask(taskId, onProgress);

  onProgress?.("Scoring plays…", 72);
  const rec = await getRecommendations(taskId, opts.density);
  const ids = rec.recommended_ids.length ? rec.recommended_ids : rec.plays.map((p) => p.id);
  if (!ids.length) {
    throw new Error(
      "No plays to recommend — detect returned 0 kills. Check worker logs for open/detect errors."
    );
  }

  onProgress?.(`Confirming ${ids.length} AI picks…`, 78);
  await confirmRecommendations(taskId, ids, opts.density);

  onProgress?.("Composing script (effects + beat layout)…", 86);
  await composePreview(taskId);

  onProgress?.("Building timeline…", 94);
  const { script } = await getScript(taskId);
  const timeline = buildTimelineFromScript(script, {
    titleText: opts.titleText ?? "Lost SI",
    songName: opts.songName,
    engagement: true,
  });
  onProgress?.("Ready", 100);
  return { taskId, script, timeline };
}

/** Browser upload (parallel raw PUT to :8000) + full AI montage maker. */
export async function runAiMontageMaker(
  videos: File[],
  music: File,
  opts: {
    density?: string;
    titleText?: string;
    onProgress?: AiMontageProgress;
  } = {}
): Promise<AiMontageResult> {
  opts.onProgress?.("Uploading…", 1);
  const { task_id } = await createMontage(videos, music, (pct) => {
    opts.onProgress?.(`Uploading… ${Math.round(pct)}%`, 1 + (pct / 100) * 7);
  });
  opts.onProgress?.("Upload complete · queued detect", 8);
  return runAiMontageFromTask(task_id, {
    density: opts.density,
    titleText: opts.titleText,
    songName: music.name.replace(/\.[^.]+$/, ""),
    onProgress: opts.onProgress,
  });
}
