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
