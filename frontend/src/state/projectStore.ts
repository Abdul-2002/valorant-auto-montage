import { create } from "zustand";
import type { Layout, MontageScript, RecommendedPlay, TimelineProject } from "../api/types";

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
  applyAiResult: (r: {
    taskId: string;
    script: MontageScript;
    timeline: TimelineProject;
    songName?: string;
  }) => void;
};

export const useProjectStore = create<ProjectState>((set, get) => ({
  taskId: "",
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
  setTaskId: (id) => set({ taskId: id }),
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
    set({ script: { ...script, clips } });
  },
  applyAiResult: (r) =>
    set({
      taskId: r.taskId,
      script: {
        ...r.script,
        clips: r.script.clips.map((c) => ({ ...c, enabled: true })),
      },
      timeline: r.timeline,
      songName: r.songName ?? get().songName,
      activeClip: 0,
    }),
}));
