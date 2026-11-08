import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getScript, saveScript } from "../api/montage";
import { buildTimelineFromScript } from "../editor/buildTimeline";
import { MediaBin } from "../editor/MediaBin";
import { SequencePlayer } from "../editor/SequencePlayer";
import { clamp, loadStudioSplit, saveStudioSplit } from "../editor/studioSplit";
import { Timeline } from "../editor/Timeline";
import { useProjectStore } from "../state/projectStore";
import { runAiMontageFromTask } from "../studio/runAiMontage";

export function Edit() {
  const { taskId = "" } = useParams();
  const nav = useNavigate();
  const {
    script,
    timeline,
    setScript,
    setTimeline,
    setTaskId,
    activeClip,
    setActiveClip,
    patchClip,
    trimClip,
    slipClip,
    reorderClip,
    moveOverlay,
    resizeOverlay,
    fitToSong,
    titleText,
    songName,
    density,
    applyAiResult,
  } = useProjectStore();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState("");
  const [playheadSec, setPlayheadSec] = useState(0);
  const [songDur, setSongDur] = useState(0);
  const [savedMsg, setSavedMsg] = useState("");
  const [split, setSplit] = useState(loadStudioSplit);

  useEffect(() => {
    if (taskId) setTaskId(taskId);
  }, [taskId, setTaskId]);

  useEffect(() => {
    saveStudioSplit(split);
  }, [split]);

  useEffect(() => {
    const audio = new Audio(`/montage/${encodeURIComponent(taskId)}/media/music`);
    const onMeta = () => setSongDur(Number(audio.duration) || 0);
    audio.addEventListener("loadedmetadata", onMeta);
    return () => audio.removeEventListener("loadedmetadata", onMeta);
  }, [taskId]);

  useEffect(() => {
    let cancel = false;
    setError("");
    void getScript(taskId)
      .then((r) => {
        if (cancel) return;
        const clips = r.script.clips.map((c) => ({ ...c, enabled: c.enabled !== false }));
        const next = { ...r.script, clips };
        setScript(next);
        setActiveClip(0);
        setTimeline(
          buildTimelineFromScript(next, {
            titleText,
            songName,
            engagement: true,
          })
        );
        setPlayheadSec(0);
      })
      .catch((e: unknown) => {
        if (!cancel) setError(e instanceof Error ? e.message : "Script not ready — run AI place");
      });
    return () => {
      cancel = true;
    };
  }, [taskId, setScript, setTimeline, titleText, songName, setActiveClip]);

  const startBinDrag = useCallback((ev: React.PointerEvent<HTMLDivElement>) => {
    ev.preventDefault();
    const startX = ev.clientX;
    const startW = split.binWidth;
    const move = (e: PointerEvent) => {
      setSplit((s) => ({ ...s, binWidth: clamp(startW + (e.clientX - startX), 180, 420) }));
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }, [split.binWidth]);

  const startTimelineDrag = useCallback((ev: React.PointerEvent<HTMLDivElement>) => {
    ev.preventDefault();
    const startY = ev.clientY;
    const startH = split.timelineHeight;
    const move = (e: PointerEvent) => {
      // Dragging the handle up grows the timeline (preview shrinks).
      setSplit((s) => ({ ...s, timelineHeight: clamp(startH - (e.clientY - startY), 120, 460) }));
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }, [split.timelineHeight]);

  async function rerunAi() {
    setBusy(true);
    setError("");
    try {
      const result = await runAiMontageFromTask(taskId, {
        density,
        titleText,
        songName,
        onProgress: setPhase,
      });
      applyAiResult(result);
      setPlayheadSec(0);
    } catch (e) {
      setError(e instanceof Error ? e.message : "AI remake failed");
    } finally {
      setBusy(false);
      setPhase("");
    }
  }

  async function persist(goReview: boolean) {
    if (!script) return;
    setBusy(true);
    setError("");
    setSavedMsg("");
    try {
      await saveScript(taskId, script, false);
      setSavedMsg("Saved");
      if (goReview) nav(`/jobs/${taskId}/review`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="studio-page">
      <div className="studio-toolbar" role="toolbar" aria-label="Studio actions">
        <div className="studio-toolbar-meta muted">
          {phase || savedMsg || (songName ? songName : taskId.slice(0, 8))}
          <span className="studio-hint"> · drag pane edges to resize</span>
        </div>
        <div className="studio-cta">
          <button className="btn" type="button" disabled={busy} onClick={() => void rerunAi()}>
            {busy ? "AI…" : "AI place"}
          </button>
          <button
            className="btn"
            type="button"
            disabled={!script || !songDur}
            onClick={() => fitToSong(songDur)}
            title={songDur ? `Fit to ${songDur.toFixed(1)}s song` : "Song duration loading…"}
          >
            Fit song
          </button>
          <button className="btn" type="button" disabled={busy || !script} onClick={() => void persist(false)}>
            Save
          </button>
          <button className="btn btn-primary" type="button" disabled={!script} onClick={() => void persist(true)}>
            Export
          </button>
          <Link className="btn btn-ghost" to={`/jobs/${taskId}/select`}>
            Picks
          </Link>
        </div>
      </div>

      {error ? <div className="studio-error error">{error}</div> : null}

      {!error || script ? (
        <div
          className="studio-layout"
          style={{
            gridTemplateColumns: `${split.binWidth}px 6px minmax(0, 1fr)`,
            gridTemplateRows: `minmax(0, 1fr) auto 6px ${split.timelineHeight}px`,
            gridTemplateAreas: `
              "bin vsplit preview"
              "transport transport transport"
              "hsplit hsplit hsplit"
              "timeline timeline timeline"
            `,
          }}
        >
          {script ? (
            <MediaBin
              taskId={taskId}
              script={script}
              timeline={timeline}
              activeClip={activeClip}
              songDur={songDur}
              songName={songName}
              onSelectClip={setActiveClip}
              onReorder={reorderClip}
              onPatchClip={patchClip}
              onSeek={setPlayheadSec}
            />
          ) : (
            <aside className="media-bin">
              <div className="media-bin-body muted">Loading clips…</div>
            </aside>
          )}

          <div
            className="studio-split studio-split-v"
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize media bin"
            title="Drag to resize videos / effects panel"
            onPointerDown={startBinDrag}
          />

          {script ? (
            <SequencePlayer
              taskId={taskId}
              script={script}
              timeline={timeline}
              activeClip={activeClip}
              onActiveClip={setActiveClip}
              playheadSec={playheadSec}
              onPlayhead={setPlayheadSec}
            />
          ) : (
            <div className="seq-preview studio-preview-empty muted">No montage yet — click AI place</div>
          )}

          <div
            className="studio-split studio-split-h"
            role="separator"
            aria-orientation="horizontal"
            aria-label="Resize timeline"
            title="Drag to resize timeline"
            onPointerDown={startTimelineDrag}
          />

          {timeline && script ? (
            <Timeline
              timeline={timeline}
              script={script}
              active={activeClip}
              playheadSec={playheadSec}
              onSelectClip={setActiveClip}
              onPlayhead={setPlayheadSec}
              onTrimClip={trimClip}
              onSlipClip={slipClip}
              onMoveOverlay={moveOverlay}
              onResizeOverlay={resizeOverlay}
            />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
