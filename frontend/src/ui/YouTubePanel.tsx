import { useEffect, useState } from "react";

import type { Channel, Layout, UploadStatus } from "../api/types";
import { getUpload, getUploadListing, listChannels, openYouTubeConnect, queueUpload } from "../api/youtube";

type Props = {
  taskId: string | null;
  layout: Layout;
  onLayout: (layout: Layout) => void;
};

const DONE = new Set(["uploaded", "failed", "channel_mismatch"]);

export function YouTubePanel(props: Props) {
  const { taskId, layout, onLayout } = props;
  const [channels, setChannels] = useState<Channel[]>([]);
  const [channelId, setChannelId] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [tags, setTags] = useState("valorant,montage,valorantmontage");
  const [privacy, setPrivacy] = useState("public");
  const [upload, setUpload] = useState<UploadStatus | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function refreshChannels(): Promise<void> {
    setError("");
    try {
      const body = await listChannels();
      setChannels(body.channels);
      setChannelId((current) => current || body.channels[0]?.channel_id || "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load channels");
    }
  }

  useEffect(() => {
    void refreshChannels();
  }, []);

  useEffect(() => {
    if (!taskId) return;
    let cancel = false;
    void getUploadListing(taskId)
      .then((listing) => {
        if (cancel) return;
        setTitle(listing.title);
        setDescription(listing.description);
        setTags(listing.tags.join(","));
        setPrivacy(listing.privacy_status || "public");
      })
      .catch((err: unknown) => {
        if (!cancel) setError(err instanceof Error ? err.message : "Could not load upload listing");
      });
    return () => {
      cancel = true;
    };
  }, [taskId]);

  useEffect(() => {
    if (!upload || DONE.has(upload.status)) return;
    let cancel = false;
    const timer = window.setTimeout(() => {
      void getUpload(upload.upload_id)
        .then((next) => {
          if (!cancel) setUpload(next);
        })
        .catch((err: unknown) => {
          if (!cancel) setError(err instanceof Error ? err.message : "Upload status failed");
        });
    }, 2000);
    return () => {
      cancel = true;
      window.clearTimeout(timer);
    };
  }, [upload]);

  async function publish(): Promise<void> {
    if (!taskId) return;
    setBusy(true);
    setError("");
    try {
      const queued = await queueUpload({
        task_id: taskId,
        channel_id: channelId,
        title: title.trim(),
        description: description.trim(),
        tags: tags.split(",").map((tag) => tag.trim()).filter(Boolean),
        privacy_status: privacy,
        format: layout,
      });
      setUpload(await getUpload(queued.upload_id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  const watchUrl =
    upload?.status === "uploaded" && upload.youtube_video_id
      ? `https://www.youtube.com/watch?v=${upload.youtube_video_id}`
      : "";

  return (
    <section style={panel}>
      <h2 style={heading}>YouTube</h2>
      <p style={hint}>
        Connect the channel in the new tab, come back here, then refresh. Defaults: song title, credits + shot chapters + hashtags, public.
      </p>
      <div style={row}>
        <button type="button" style={button} onClick={openYouTubeConnect}>
          Connect YouTube
        </button>
        <button type="button" style={button} onClick={() => void refreshChannels()}>
          Refresh channels
        </button>
      </div>
      <label style={label}>
        Channel
        <select style={field} value={channelId} onChange={(event) => setChannelId(event.target.value)}>
          <option value="">Select a channel…</option>
          {channels.map((channel) => (
            <option key={channel.channel_id} value={channel.channel_id}>
              {channel.title}
            </option>
          ))}
        </select>
      </label>
      <label style={label}>
        Title
        <input style={field} maxLength={100} value={title} onChange={(event) => setTitle(event.target.value)} />
      </label>
      <label style={label}>
        Description
        <textarea style={area} maxLength={5000} value={description} onChange={(event) => setDescription(event.target.value)} />
      </label>
      <label style={label}>
        Tags
        <input style={field} value={tags} onChange={(event) => setTags(event.target.value)} />
      </label>
      <div style={row}>
        <label style={label}>
          Privacy
          <select style={field} value={privacy} onChange={(event) => setPrivacy(event.target.value)}>
            <option value="private">Private</option>
            <option value="unlisted">Unlisted</option>
            <option value="public">Public</option>
          </select>
        </label>
        <label style={label}>
          Format
          <select style={field} value={layout} onChange={(event) => onLayout(event.target.value as Layout)}>
            <option value="16:9">16:9</option>
            <option value="9:16">9:16</option>
          </select>
        </label>
      </div>
      <button
        type="button"
        style={button}
        disabled={!taskId || !channelId || !title.trim() || busy}
        onClick={() => void publish()}
      >
        {taskId ? "Upload to YouTube" : "Render a montage first"}
      </button>
      {upload ? (
        <p style={hint}>
          {upload.status}
          {upload.error ? `: ${upload.error}` : ""}
          {watchUrl ? (
            <>
              {" "}
              <a style={link} href={watchUrl} target="_blank" rel="noreferrer">
                Open video
              </a>
            </>
          ) : null}
        </p>
      ) : null}
      {error ? <p style={errorStyle}>{error}</p> : null}
    </section>
  );
}

const panel: React.CSSProperties = {
  background: "#0f1624",
  border: "1px solid #22304b",
  borderRadius: 12,
  padding: 16,
  display: "flex",
  flexDirection: "column",
  gap: 10,
};
const heading: React.CSSProperties = { margin: 0, fontSize: 16 };
const hint: React.CSSProperties = { margin: 0, fontSize: 13, opacity: 0.8 };
const row: React.CSSProperties = { display: "flex", gap: 12, flexWrap: "wrap" };
const label: React.CSSProperties = { display: "flex", flexDirection: "column", gap: 6, fontSize: 12, flex: 1 };
const field: React.CSSProperties = {
  background: "#121a29",
  border: "1px solid #22304b",
  color: "#e7edf7",
  padding: "8px 10px",
  borderRadius: 10,
};
const area: React.CSSProperties = { ...field, minHeight: 72, resize: "vertical" };
const button: React.CSSProperties = {
  background: "#1e2a44",
  border: "1px solid #2b3a5c",
  color: "#e7edf7",
  padding: "9px 12px",
  borderRadius: 10,
  cursor: "pointer",
  width: "fit-content",
};
const link: React.CSSProperties = { color: "#8dd3ff" };
const errorStyle: React.CSSProperties = { margin: 0, color: "#ffb4b4", fontSize: 13 };
