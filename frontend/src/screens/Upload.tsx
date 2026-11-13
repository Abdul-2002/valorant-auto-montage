import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { pingApi } from "../api/http";
import {
  createMontage,
  createMontageFromPaths,
  listMountedMedia,
  type MountedFile,
} from "../api/montage";
import { useProjectStore } from "../state/projectStore";
import { runAiMontageFromPaths, runAiMontageMaker } from "../studio/runAiMontage";
import { ProgressBar } from "../ui/ProgressBar";

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function isExtValorant(path: string): boolean {
  return path.includes("/videos_ext/");
}

/** Newest-first when filenames encode dates like Valorant 2026.11.10 - ... */
function sortVideosNewestFirst(files: MountedFile[]): MountedFile[] {
  return [...files].sort((a, b) => b.name.localeCompare(a.name));
}

export function Upload() {
  const nav = useNavigate();
  const {
    density,
    durationMode,
    layout,
    titleText,
    setDensity,
    setDurationMode,
    setLayout,
    setTitleText,
    setTaskId,
    setSongName,
    applyAiResult,
  } = useProjectStore();

  const [mountedVideos, setMountedVideos] = useState<MountedFile[]>([]);
  const [mountedSongs, setMountedSongs] = useState<MountedFile[]>([]);
  const [selectedVideoPaths, setSelectedVideoPaths] = useState<string[]>([]);
  const [mountedSongPath, setMountedSongPath] = useState("");
  const [legacyVideos, setLegacyVideos] = useState<File[]>([]);
  const [legacySong, setLegacySong] = useState<File | null>(null);
  const [showLegacy, setShowLegacy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState("");
  const [percent, setPercent] = useState(0);
  const [error, setError] = useState("");
  const [apiOk, setApiOk] = useState<boolean | null>(null);
  const [mediaError, setMediaError] = useState("");

  const dDriveVideos = useMemo(
    () => sortVideosNewestFirst(mountedVideos.filter((v) => isExtValorant(v.path))),
    [mountedVideos]
  );
  const otherVideos = useMemo(
    () => sortVideosNewestFirst(mountedVideos.filter((v) => !isExtValorant(v.path))),
    [mountedVideos]
  );

  const selectedBytes = useMemo(() => {
    const mounted = mountedVideos
      .filter((v) => selectedVideoPaths.includes(v.path))
      .reduce((a, v) => a + v.size_bytes, 0);
    const song = mountedSongs.find((s) => s.path === mountedSongPath)?.size_bytes || 0;
    const legacy =
      legacyVideos.reduce((a, f) => a + f.size, 0) + (legacySong?.size || 0);
    return showLegacy ? legacy : mounted + song;
  }, [
    mountedVideos,
    selectedVideoPaths,
    mountedSongs,
    mountedSongPath,
    legacyVideos,
    legacySong,
    showLegacy,
  ]);

  useEffect(() => {
    let cancel = false;
    void pingApi().then((ok) => {
      if (!cancel) setApiOk(ok);
    });
    void listMountedMedia()
      .then((media) => {
        if (cancel) return;
        setMountedVideos(media.videos);
        setMountedSongs(media.songs);
        setMediaError("");
        const ext = sortVideosNewestFirst(media.videos.filter((v) => isExtValorant(v.path)));
        if (ext.length) {
          setSelectedVideoPaths(ext.slice(0, 20).map((v) => v.path));
        }
        const mood = media.songs.find((s) => s.name.toLowerCase().includes("24kgoldn"));
        if (mood) setMountedSongPath(mood.path);
        else if (media.songs[0]) setMountedSongPath(media.songs[0].path);
      })
      .catch((e) => {
        if (!cancel) setMediaError(e instanceof Error ? e.message : "Failed to list mounted media");
      });
    return () => {
      cancel = true;
    };
  }, []);

  function onProgress(msg: string, pct?: number) {
    setPhase(msg);
    if (typeof pct === "number") setPercent(pct);
  }

  function toggleVideo(path: string) {
    setSelectedVideoPaths((prev) =>
      prev.includes(path) ? prev.filter((p) => p !== path) : [...prev, path]
    );
  }

  function selectNewest(n: number) {
    setSelectedVideoPaths(dDriveVideos.slice(0, n).map((v) => v.path));
  }

  async function startDetectMounted() {
    if (!selectedVideoPaths.length || !mountedSongPath) {
      setError("Select at least one mounted video and a song.");
      return;
    }
    setBusy(true);
    setError("");
    setPercent(5);
    setPhase("Linking mounted media…");
    try {
      const { task_id } = await createMontageFromPaths(selectedVideoPaths, mountedSongPath);
      setTaskId(task_id);
      setSongName(mountedSongPath.split("/").pop()?.replace(/\.[^.]+$/, "") || "song");
      setPercent(100);
      nav(`/jobs/${task_id}/detect`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Create from paths failed");
    } finally {
      setBusy(false);
    }
  }

  async function aiMontageMounted() {
    if (!selectedVideoPaths.length || !mountedSongPath) {
      setError("Select at least one mounted video and a song.");
      return;
    }
    setBusy(true);
    setError("");
    setPercent(1);
    setPhase("Starting AI Montage Maker (mounted)…");
    try {
      const result = await runAiMontageFromPaths(selectedVideoPaths, mountedSongPath, {
        density,
        titleText,
        onProgress,
      });
      applyAiResult({
        ...result,
        songName: mountedSongPath.split("/").pop()?.replace(/\.[^.]+$/, "") || "song",
      });
      nav(`/jobs/${result.taskId}/edit`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "AI montage failed");
    } finally {
      setBusy(false);
    }
  }

  async function startDetectLegacy() {
    if (!legacyVideos.length || !legacySong) {
      setError("Add at least one video and a song.");
      return;
    }
    setBusy(true);
    setError("");
    setPercent(1);
    setPhase("Uploading…");
    try {
      const { task_id } = await createMontage(legacyVideos, legacySong, (pct) => {
        setPhase(`Uploading… ${Math.round(pct)}%`);
        setPercent(pct);
      });
      setTaskId(task_id);
      setSongName(legacySong.name.replace(/\.[^.]+$/, ""));
      setPercent(100);
      nav(`/jobs/${task_id}/detect`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  async function aiMontageLegacy() {
    if (!legacyVideos.length || !legacySong) {
      setError("Add at least one video and a song.");
      return;
    }
    setBusy(true);
    setError("");
    setPercent(1);
    setPhase("Starting AI Montage Maker…");
    try {
      const result = await runAiMontageMaker(legacyVideos, legacySong, {
        density,
        titleText,
        onProgress,
      });
      applyAiResult({
        ...result,
        songName: legacySong.name.replace(/\.[^.]+$/, ""),
      });
      nav(`/jobs/${result.taskId}/edit`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "AI montage failed");
    } finally {
      setBusy(false);
    }
  }

  const canStartMounted = selectedVideoPaths.length > 0 && !!mountedSongPath;
  const canStartLegacy = legacyVideos.length > 0 && !!legacySong;

  function renderVideoList(files: MountedFile[], label: string) {
    if (!files.length) return null;
    return (
      <div style={{ display: "grid", gap: 6 }}>
        <div className="muted">{label}</div>
        <div
          style={{
            maxHeight: 280,
            overflow: "auto",
            border: "1px solid var(--border, #333)",
            borderRadius: 8,
            padding: 8,
            display: "grid",
            gap: 4,
          }}
        >
          {files.map((v) => (
            <label key={v.path} style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
              <input
                type="checkbox"
                disabled={busy}
                checked={selectedVideoPaths.includes(v.path)}
                onChange={() => toggleVideo(v.path)}
              />
              <span style={{ flex: 1 }}>
                <span>{v.name}</span>
                <span className="muted" style={{ display: "block", fontSize: 12 }}>
                  {formatBytes(v.size_bytes)} · {v.path}
                </span>
              </span>
            </label>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <h1>New montage</h1>
      <p className="muted">
        Prefer <strong>mounted media</strong> from <code>D:\Videos\Valorant</code> (
        <code>/videos_ext</code>). That is a symlink — no multi‑GB browser copy.
      </p>
      <div className="panel" style={{ marginTop: 16, display: "grid", gap: 14 }}>
        <div style={{ color: apiOk === false ? "#ff8b8b" : apiOk ? "var(--accent-2)" : "var(--muted)" }}>
          API:{" "}
          {apiOk === null
            ? "checking…"
            : apiOk
              ? "reachable via /montage proxy"
              : "unreachable — run docker compose up -d"}
        </div>
        {mediaError ? <div className="error">{mediaError}</div> : null}

        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button className="btn" type="button" disabled={busy || !dDriveVideos.length} onClick={() => selectNewest(15)}>
            Select newest 15 (D:)
          </button>
          <button className="btn" type="button" disabled={busy || !dDriveVideos.length} onClick={() => selectNewest(20)}>
            Select newest 20 (D:)
          </button>
          <button
            className="btn"
            type="button"
            disabled={busy}
            onClick={() => setSelectedVideoPaths([])}
          >
            Clear video selection
          </button>
        </div>

        {renderVideoList(dDriveVideos, `D:\\Videos\\Valorant (${dDriveVideos.length} files)`)}
        {renderVideoList(otherVideos, `Other mounted videos (${otherVideos.length})`)}

        <label>
          Song (mounted Music)
          <select
            value={mountedSongPath}
            disabled={busy || !mountedSongs.length}
            onChange={(e) => setMountedSongPath(e.target.value)}
          >
            <option value="">Select a song…</option>
            {mountedSongs.map((s) => (
              <option key={s.path} value={s.path}>
                {s.name} ({formatBytes(s.size_bytes)})
              </option>
            ))}
          </select>
        </label>

        <div className="muted">
          Selected: {selectedVideoPaths.length} video(s) · {formatBytes(selectedBytes)} (linked, not uploaded)
        </div>

        <label>
          Title text
          <input value={titleText} onChange={(e) => setTitleText(e.target.value)} placeholder="Lost SI" />
        </label>
        <label>
          Layout
          <select value={layout} onChange={(e) => setLayout(e.target.value as "16:9" | "9:16")}>
            <option value="16:9">16:9</option>
            <option value="9:16">9:16</option>
          </select>
        </label>
        <label>
          Duration mode
          <select
            value={durationMode}
            onChange={(e) => setDurationMode(e.target.value as "fixed" | "clip_driven")}
          >
            <option value="clip_driven">Clip-driven (recommended)</option>
            <option value="fixed">Fixed target</option>
          </select>
        </label>
        <label>
          Curation density
          <select value={density} onChange={(e) => setDensity(e.target.value as "standard" | "dense")}>
            <option value="standard">Standard</option>
            <option value="dense">Dense</option>
          </select>
        </label>

        {busy || phase ? <ProgressBar percent={percent} label={phase || "Working…"} /> : null}
        {error ? <div className="error">{error}</div> : null}

        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button
            className="btn btn-primary"
            type="button"
            disabled={busy || !canStartMounted}
            onClick={() => void aiMontageMounted()}
          >
            {busy ? "AI working…" : "AI Montage Maker (mounted)"}
          </button>
          <button
            className="btn"
            type="button"
            disabled={busy || !canStartMounted}
            onClick={() => void startDetectMounted()}
          >
            Manual: detect only (mounted)
          </button>
        </div>
      </div>

      <div className="panel" style={{ marginTop: 16 }}>
        <button className="btn btn-ghost" type="button" onClick={() => setShowLegacy((v) => !v)}>
          {showLegacy ? "Hide" : "Show"} legacy browser upload (slow · copies GB · can corrupt)
        </button>
        {showLegacy ? (
          <div style={{ marginTop: 12, display: "grid", gap: 14 }}>
            <p className="muted">
              Avoid this for multi‑GB VODs. Prefer mounted media above.
            </p>
            <label>
              Gameplay videos
              <input
                type="file"
                accept="video/*"
                multiple
                disabled={busy}
                onChange={(e) => setLegacyVideos(Array.from(e.target.files || []))}
              />
              <div className="muted">{legacyVideos.length} file(s)</div>
            </label>
            <label>
              Song
              <input
                type="file"
                accept="audio/*"
                disabled={busy}
                onChange={(e) => setLegacySong(e.target.files?.[0] || null)}
              />
            </label>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button
                className="btn"
                type="button"
                disabled={busy || !canStartLegacy}
                onClick={() => void aiMontageLegacy()}
              >
                AI Montage Maker (browser copy)
              </button>
              <button
                className="btn"
                type="button"
                disabled={busy || !canStartLegacy}
                onClick={() => void startDetectLegacy()}
              >
                Manual: detect only (browser copy)
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
