/** Persistable split sizes for the studio panes (bin | preview, timeline height). */

const KEY = "lostsi.studioSplit.v1";

export type StudioSplit = {
  binWidth: number;
  timelineHeight: number;
};

const DEFAULTS: StudioSplit = { binWidth: 250, timelineHeight: 168 };

export function loadStudioSplit(): StudioSplit {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return DEFAULTS;
    const parsed = JSON.parse(raw) as Partial<StudioSplit>;
    return {
      binWidth: clamp(Number(parsed.binWidth) || DEFAULTS.binWidth, 180, 420),
      timelineHeight: clamp(Number(parsed.timelineHeight) || DEFAULTS.timelineHeight, 120, 420),
    };
  } catch {
    return DEFAULTS;
  }
}

export function saveStudioSplit(next: StudioSplit): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* ignore */
  }
}

export function clamp(n: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, n));
}
