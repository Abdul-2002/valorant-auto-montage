import { create } from "zustand";
import type { Layout, MontageScript, RecommendedPlay, TimelineOverlay, TimelineProject } from "../api/types";
import { buildTimelineFromScript } from "../editor/buildTimeline";
import { fitScriptToDuration, retimeScript } from "../editor/retimeScript";
import { sourceDur, timelineDeltaToSource } from "../editor/timelineMath";

type TrackKey = "text" | "music" | "effects" | "video";

type ProjectState = {
  taskId: string;
  density: "standard" | "dense";
  durationMode: "fixed" | "clip_driven";
  layout: Layout;
  titleText: string;
  songName: string;
  selectedIds: string[];
  plays: RecommendedPlay[];
  script: MontageScript | null;
  timeline: TimelineProject | null;
  activeClip: number;
  setTaskId: (id: string) => void;
  setDensity: (d: "standard" | "dense") => void;
  setDurationMode: (m: "fixed" | "clip_driven") => void;
  setLayout: (l: Layout) => void;
  setTitleText: (t: string) => void;
  setSongName: (n: string) => void;
  setPlays: (plays: RecommendedPlay[]) => void;
  setSelectedIds: (ids: string[]) => void;
  togglePlay: (id: string) => void;
  setScript: (s: MontageScript | null) => void;
  setTimeline: (t: TimelineProject | null) => void;
  setActiveClip: (i: number) => void;
  patchClip: (index: number, patch: Partial<MontageScript["clips"][number]>) => void;
  /** Trim in/out using timeline-seconds delta (converts via clip stretch). */
  trimClip: (index: number, edge: "in" | "out", timelineDeltaSec: number) => void;
  /** Slip source window (keep duration): decide where the clip starts in the VOD. */
  slipClip: (index: number, timelineDeltaSec: number) => void;
  /** Reorder clips in the montage sequence. */
  reorderClip: (fromIndex: number, toIndex: number) => void;
  moveOverlay: (track: TrackKey, id: string, deltaSec: number) => void;
  resizeOverlay: (track: TrackKey, id: string, edge: "in" | "out", deltaSec: number) => void;
  syncTimelineFromScript: (preserveStudio?: boolean) => void;
  fitToSong: (targetSec: number) => void;
  retime: () => void;
  applyAiResult: (r: {
    taskId: string;
    script: MontageScript;
    timeline: TimelineProject;
    songName?: string;
  }) => void;
};

const TASK_KEY = "lostsi.activeTaskId";

function readStoredTaskId(): string {
  try {
    return localStorage.getItem(TASK_KEY) || "";
  } catch {
    return "";
  }
}

function writeStoredTaskId(id: string): void {
  try {
    if (id) localStorage.setItem(TASK_KEY, id);
    else localStorage.removeItem(TASK_KEY);
  } catch {
    /* ignore */
  }
}

function rebuild(
  script: MontageScript,
  titleText: string,
  songName: string,
  prev: TimelineProject | null,
  preserveStudio: boolean
): TimelineProject {
  const next = buildTimelineFromScript(script, { titleText, songName, engagement: true });
  if (!preserveStudio || !prev) return next;
  return {
    ...next,
    tracks: {
      ...next.tracks,
      // Keep user-moved text/music; refresh video/fx from script.
      text: prev.tracks.text.length ? prev.tracks.text : next.tracks.text,
      music: prev.tracks.music.length ? prev.tracks.music : next.tracks.music,
    },
  };
}

function patchTrack(
  timeline: TimelineProject,
  track: TrackKey,
  id: string,
  fn: (o: TimelineOverlay) => TimelineOverlay
): TimelineProject {
  const items = timeline.tracks[track].map((o) => (o.id === id ? fn(o) : o));
  return {
    ...timeline,
    tracks: { ...timeline.tracks, [track]: items },
  };
}

export const useProjectStore = create<ProjectState>((set, get) => ({
  taskId: readStoredTaskId(),
  density: "standard",
  durationMode: "clip_driven",
  layout: "16:9",
  titleText: "Lost SI",
  songName: "",
  selectedIds: [],
  plays: [],
  script: null,
  timeline: null,
  activeClip: 0,
  setTaskId: (id) => {
    writeStoredTaskId(id);
    set({ taskId: id });
  },
  setDensity: (d) => set({ density: d }),
  setDurationMode: (m) => set({ durationMode: m }),
  setLayout: (l) => set({ layout: l }),
  setTitleText: (t) => set({ titleText: t }),
  setSongName: (n) => set({ songName: n }),
  setPlays: (plays) => set({ plays }),
  setSelectedIds: (ids) => set({ selectedIds: ids }),
  togglePlay: (id) => {
    const cur = get().selectedIds;
    set({ selectedIds: cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id] });
  },
  setScript: (s) => set({ script: s }),
  setTimeline: (t) => set({ timeline: t }),
  setActiveClip: (i) => set({ activeClip: i }),
  patchClip: (index, patch) => {
    const script = get().script;
    if (!script) return;
    const clips = script.clips.map((c, i) => (i === index ? { ...c, ...patch } : c));
    const next = retimeScript({ ...script, clips });
    set({
      script: next,
      timeline: rebuild(next, get().titleText, get().songName, get().timeline, true),
    });
  },
  trimClip: (index, edge, timelineDeltaSec) => {
    const script = get().script;
    if (!script) return;
    const clip = script.clips[index];
    if (!clip) return;
    const srcDelta = timelineDeltaToSource(clip, timelineDeltaSec);
    let start = Number(clip.start_sec);
    let end = Number(clip.end_sec);
    if (edge === "in") {
      start = Math.max(0, Math.min(end - 0.25, start + srcDelta));
    } else {
      end = Math.max(start + 0.25, end + srcDelta);
    }
    const clips = script.clips.map((c, i) => (i === index ? { ...c, start_sec: start, end_sec: end } : c));
    const next = retimeScript({ ...script, clips });
    set({
      script: next,
      timeline: rebuild(next, get().titleText, get().songName, get().timeline, true),
      activeClip: index,
    });
  },
  slipClip: (index, timelineDeltaSec) => {
    const script = get().script;
    if (!script) return;
    const clip = script.clips[index];
    if (!clip) return;
    const srcDelta = timelineDeltaToSource(clip, timelineDeltaSec);
    let start = Math.max(0, Number(clip.start_sec) + srcDelta);
    let end = start + sourceDur(clip);
    const clips = script.clips.map((c, i) => (i === index ? { ...c, start_sec: start, end_sec: end } : c));
    const next = retimeScript({ ...script, clips });
    set({
      script: next,
      timeline: rebuild(next, get().titleText, get().songName, get().timeline, true),
      activeClip: index,
    });
  },
  reorderClip: (fromIndex, toIndex) => {
    const script = get().script;
    if (!script) return;
    if (fromIndex === toIndex) return;
    if (fromIndex < 0 || toIndex < 0 || fromIndex >= script.clips.length || toIndex >= script.clips.length) return;
    const clips = script.clips.slice();
    const [item] = clips.splice(fromIndex, 1);
    clips.splice(toIndex, 0, item);
    const next = retimeScript({ ...script, clips });
    set({
      script: next,
      timeline: rebuild(next, get().titleText, get().songName, get().timeline, true),
      activeClip: toIndex,
    });
  },
  moveOverlay: (track, id, deltaSec) => {
    const timeline = get().timeline;
    if (!timeline) return;
    set({
      timeline: patchTrack(timeline, track, id, (o) => {
        const dur = Math.max(0.2, o.end_sec - o.start_sec);
        const start = Math.max(0, o.start_sec + deltaSec);
        return { ...o, start_sec: start, end_sec: start + dur };
      }),
    });
  },
  resizeOverlay: (track, id, edge, deltaSec) => {
    const timeline = get().timeline;
    if (!timeline) return;
    set({
      timeline: patchTrack(timeline, track, id, (o) => {
        if (edge === "in") {
          const start = Math.max(0, Math.min(o.end_sec - 0.2, o.start_sec + deltaSec));
          return { ...o, start_sec: start };
        }
        const end = Math.max(o.start_sec + 0.2, o.end_sec + deltaSec);
        return { ...o, end_sec: end };
      }),
    });
  },
  syncTimelineFromScript: (preserveStudio = true) => {
    const script = get().script;
    if (!script) return;
    set({
      timeline: rebuild(script, get().titleText, get().songName, get().timeline, preserveStudio),
    });
  },
  fitToSong: (targetSec) => {
    const script = get().script;
    if (!script) return;
    const next = fitScriptToDuration(script, targetSec);
    set({
      script: next,
      timeline: rebuild(next, get().titleText, get().songName, get().timeline, true),
    });
  },
  retime: () => {
    const script = get().script;
    if (!script) return;
    const next = retimeScript(script);
    set({
      script: next,
      timeline: rebuild(next, get().titleText, get().songName, get().timeline, true),
    });
  },
  applyAiResult: (r) => {
    writeStoredTaskId(r.taskId);
    set({
      taskId: r.taskId,
      script: {
        ...r.script,
        clips: r.script.clips.map((c) => ({ ...c, enabled: true })),
      },
      timeline: r.timeline,
      songName: r.songName ?? get().songName,
      activeClip: 0,
    });
  },
}));
