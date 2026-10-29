import { send } from "./http";
import type { Channel, Layout, UploadStatus } from "./types";

export type UploadListing = {
  task_id: string;
  song_title: string;
  title: string;
  description: string;
  tags: string[];
  privacy_status: string;
};

export function listChannels(): Promise<{ channels: Channel[] }> {
  return send("/youtube/channels");
}

export function getUploadListing(taskId: string): Promise<UploadListing> {
  return send(`/youtube/listing/${encodeURIComponent(taskId)}`);
}

export function queueUpload(input: {
  task_id: string;
  channel_id: string;
  title: string;
  description: string;
  tags: string[];
  privacy_status: string;
  format: Layout;
}): Promise<{ upload_id: string; status: string }> {
  return send("/youtube/uploads", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...input, category_id: "20" }),
  });
}

export function getUpload(uploadId: string): Promise<UploadStatus> {
  return send(`/youtube/uploads/${encodeURIComponent(uploadId)}`);
}

export function openYouTubeConnect(): void {
  window.open("/youtube/connect", "_blank", "noopener");
}
