export type Highlight = {
  video_index: number;
  timestamp_sec: number;
  score: number;
  event_type: string;
};

export type TaskStatus = {
  task_id: string;
  state: string;
  progress: number;
  phase: string | null;
  detail: Record<string, unknown> | null;
};

export type MountedFile = {
  name: string;
  path: string;
  size_bytes: number;
};

export type MountedMedia = {
  videos: MountedFile[];
  songs: MountedFile[];
};

export type Channel = {
  channel_id: string;
  title: string;
  connected_at: string | null;
};

export type UploadStatus = {
  upload_id: string;
  status: string;
  youtube_video_id: string | null;
  error: string | null;
  title: string;
  privacy_status: string;
};

export type Layout = "16:9" | "9:16";

export type WatchKind = "detect" | "render";

export type PlayFlowScores = {
  impact: number;
  watchability: number;
  combined: number;
};

export type RecommendedPlay = {
  id: string;
  video_index: number;
  kill_timestamps_sec: number[];
  kill_count: number;
  play_label: string;
  detector_score: number;
  flow: PlayFlowScores;
  recommended: boolean;
};

export type Recommendations = {
  task_id: string;
  plays: RecommendedPlay[];
  recommended_ids: string[];
  sequence_flow: PlayFlowScores & { pacing?: number; arc?: number; variety?: number };
  density: string;
};

export type ScriptTransition = {
  type?: string;
  duration_sec?: number;
};

export type ScriptClip = {
  video_index: number;
  start_sec: number;
  end_sec: number;
  kill_timestamp_sec: number;
  kill_timestamps_sec?: number[];
  kill_output_times_sec?: number[];
  score: number;
  output_start_sec?: number | null;
  output_end_sec?: number | null;
  recipe?: string;
  hit_style?: string;
  scoped?: boolean;
  ghost_candidate?: boolean;
  gun_candidate?: boolean;
  pip_style?: string;
  arc_phase?: string;
  accent_beats_sec?: number[];
  transition_to_next?: ScriptTransition | null;
  enabled?: boolean;
};

export type MontageScript = {
  clips: ScriptClip[];
  reasoning?: string;
  creative_config_resolved?: Record<string, unknown>;
};

export type TimelineOverlay = {
  id: string;
  kind: "video" | "music" | "text" | "effect";
  label: string;
  start_sec: number;
  end_sec: number;
  clip_index?: number;
  recipe?: string;
  hit_style?: string;
  ghost?: boolean;
  gun?: boolean;
  text?: string;
  color?: string;
};

export type TimelineProject = {
  duration_sec: number;
  phase_offset_sec: number;
  tracks: {
    video: TimelineOverlay[];
    music: TimelineOverlay[];
    text: TimelineOverlay[];
    effects: TimelineOverlay[];
  };
};
