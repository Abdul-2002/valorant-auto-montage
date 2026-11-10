import { useEffect, useMemo, useRef, useState } from "react";
import type { MontageScript, TimelineProject } from "../api/types";
import { effectLabel, recipeLabel, transitionLabel } from "./fxLabels";
import { summarizePlayhead } from "./playheadSummary";

type Props = {
  taskId: string;
  script: MontageScript;
  timeline: TimelineProject | null;
  activeClip: number;
  onActiveClip: (i: number) => void;
  playheadSec: number;
  onPlayhead: (sec: number) => void;
};

type Segment = {
  clipIndex: number;
  videoIndex: number;
  srcStart: number;
  srcEnd: number;
  outStart: number;
  outEnd: number;
  recipe: string;
  transition?: string;
  transitionDur: number;
  ghost?: boolean;
  gun?: boolean;
};

function buildSegments(script: MontageScript): Segment[] {
  const raw: Segment[] = [];
  script.clips.forEach((c, i) => {
    if (c.enabled === false) return;
    const outStart = Number(c.output_start_sec ?? 0);
    const outEnd = Number(c.output_end_sec ?? outStart + Math.max(0.2, c.end_sec - c.start_sec));
    raw.push({
      clipIndex: i,
      videoIndex: c.video_index,
      srcStart: Number(c.start_sec),
      srcEnd: Number(c.end_sec),
      outStart,
      outEnd,
      recipe: c.recipe || "clean",
      transition: c.transition_to_next?.type,
      transitionDur: Math.max(0.35, Number(c.transition_to_next?.duration_sec || 0.55)),
      ghost: Boolean(c.ghost_candidate),
      gun: Boolean(c.gun_candidate),
    });
  });
  // Composer may stamp absolute song-phase times (e.g. start at 48s). Preview
  // playhead is 0-based like the timeline UI — normalize so clip #1 is at t=0.
  if (!raw.length) return raw;
  const t0 = Math.min(...raw.map((s) => s.outStart));
  return raw.map((s) => ({
    ...s,
    outStart: s.outStart - t0,
    outEnd: s.outEnd - t0,
  }));
}

function segmentAt(segments: Segment[], t: number): Segment | null {
  if (!segments.length) return null;
  if (t <= segments[0].outStart + 0.001) return segments[0];
  for (const s of segments) {
    if (t >= s.outStart && t < s.outEnd - 0.001) return s;
  }
  return segments[segments.length - 1];
}

function srcForPlayhead(seg: Segment, playhead: number): number {
  const span = Math.max(0.05, seg.outEnd - seg.outStart);
  const srcSpan = Math.max(0.05, seg.srcEnd - seg.srcStart);
  const local = Math.max(0, Math.min(span, playhead - seg.outStart));
  return seg.srcStart + (local / span) * srcSpan;
}

function playheadFromSrc(seg: Segment, srcTime: number): number {
  const span = Math.max(0.05, seg.outEnd - seg.outStart);
  const srcSpan = Math.max(0.05, seg.srcEnd - seg.srcStart);
  const local = Math.max(0, Math.min(srcSpan, srcTime - seg.srcStart));
  return seg.outStart + (local / srcSpan) * span;
}

function rateForSeg(seg: Segment): number {
  const span = Math.max(0.05, seg.outEnd - seg.outStart);
  const srcSpan = Math.max(0.05, seg.srcEnd - seg.srcStart);
  // out longer than source (slow) → rate < 1
  return Math.max(0.25, Math.min(2.5, srcSpan / span));
}

export function SequencePlayer({
  taskId,
  script,
  timeline,
  activeClip,
  onActiveClip,
  playheadSec,
  onPlayhead,
}: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const playheadRef = useRef(playheadSec);
  const playingRef = useRef(false);
  const segRef = useRef<Segment | null>(null);
  const [playing, setPlaying] = useState(false);
  const [showMaster, setShowMaster] = useState(false);
  const [masterMissing, setMasterMissing] = useState(false);
  const masterSrc = `/montage/${encodeURIComponent(taskId)}/media/render`;
  const segments = useMemo(() => buildSegments(script), [script]);
  // Playback length follows the clip sequence (normalized). Do not let a stale
  // timeline duration inflate the scrubber past the last clip.
  const duration = Math.max(0.1, segments.length ? segments[segments.length - 1].outEnd : timeline?.duration_sec || 1);
  const hits = useMemo(
    () => summarizePlayhead(script, timeline, playheadSec),
    [script, timeline, playheadSec]
  );

  playheadRef.current = playheadSec;
  playingRef.current = playing;

  const activeSeg = segmentAt(segments, playheadSec) || segments.find((s) => s.clipIndex === activeClip) || null;
  segRef.current = activeSeg;
  const videoSrc = activeSeg
    ? `/montage/${encodeURIComponent(taskId)}/media/video/${activeSeg.videoIndex}`
    : undefined;
  const musicSrc = `/montage/${encodeURIComponent(taskId)}/media/music`;

  const inTransition = Boolean(
    activeSeg?.transition &&
      playheadSec >= activeSeg.outEnd - activeSeg.transitionDur &&
      playheadSec <= activeSeg.outEnd + 0.05
  );
  const isJigsaw = inTransition && activeSeg?.transition === "jigsaw";
  const clip = activeSeg ? script.clips[activeSeg.clipIndex] : null;
  const killLocal = clip?.kill_output_times_sec?.[0] ?? Math.max(0.4, ((activeSeg?.outEnd ?? 1) - (activeSeg?.outStart ?? 0)) * 0.35);
  const gunLocal = playheadSec - (activeSeg?.outStart ?? 0);
  const inGunWindow = Boolean(activeSeg?.gun) && Math.abs(gunLocal - Number(killLocal)) < 1.35;

  /** Seek video/audio to match playhead — only when paused or entering a clip. */
  function snapMediaToPlayhead(seg: Segment, playhead: number) {
    const v = videoRef.current;
    if (!v) return;
    const target = srcForPlayhead(seg, playhead);
    try {
      v.playbackRate = rateForSeg(seg);
      if (Math.abs(v.currentTime - target) > 0.05) v.currentTime = target;
    } catch {
      /* ignore seek race while loading */
    }
    const a = audioRef.current;
    if (a) {
      try {
        const musicStart = timeline?.tracks.music[0]?.start_sec ?? 0;
        a.currentTime = Math.max(0, Math.min(a.duration || duration, playhead - musicStart));
      } catch {
        /* ignore */
      }
    }
  }

  // When paused / scrubbing: sync frame once. Never seek every tick while playing.
  useEffect(() => {
    if (playing || !activeSeg) return;
    snapMediaToPlayhead(activeSeg, playheadSec);
  }, [playing, activeSeg?.clipIndex, activeSeg?.videoIndex, playheadSec, videoSrc]);

  // After src swap, snap once metadata is ready.
  useEffect(() => {
    const v = videoRef.current;
    if (!v || !activeSeg) return;
    const onReady = () => {
      if (!playingRef.current) snapMediaToPlayhead(activeSeg, playheadRef.current);
    };
    v.addEventListener("loadedmetadata", onReady);
    return () => v.removeEventListener("loadedmetadata", onReady);
  }, [videoSrc, activeSeg?.clipIndex]);

  // Smooth playback: drive timeline FROM the video clock (no per-frame seeking).
  useEffect(() => {
    if (!playing) return;
    const v = videoRef.current;
    const a = audioRef.current;
    const seg0 = segmentAt(segments, playheadRef.current);
    if (v && seg0) {
      snapMediaToPlayhead(seg0, playheadRef.current);
      void v.play().catch(() => undefined);
    }
    if (a) {
      try {
        a.currentTime = Math.min(a.duration || duration, playheadRef.current);
      } catch {
        /* ignore */
      }
      void a.play().catch(() => undefined);
    }

    let raf = 0;
    const tick = () => {
      const seg = segRef.current || segmentAt(segments, playheadRef.current);
      const video = videoRef.current;
      if (!seg || !video) {
        raf = requestAnimationFrame(tick);
        return;
      }

      // Clip boundary — advance or stop (do not scrub frame-by-frame).
      if (video.currentTime >= seg.srcEnd - 0.02 || playheadRef.current >= seg.outEnd - 0.02) {
        const nextSeg = segments.find((s) => s.outStart >= seg.outEnd - 0.001) || null;
        if (!nextSeg) {
          setPlaying(false);
          video.pause();
          audioRef.current?.pause();
          onPlayhead(duration);
          return;
        }
        onPlayhead(nextSeg.outStart);
        onActiveClip(nextSeg.clipIndex);
        // src change handled by React; play resumes after metadata via playing still true
        raf = requestAnimationFrame(tick);
        return;
      }

      const next = playheadFromSrc(seg, video.currentTime);
      if (Math.abs(next - playheadRef.current) > 0.02) {
        onPlayhead(next);
        if (seg.clipIndex !== activeClip) onActiveClip(seg.clipIndex);
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, segments, duration, onPlayhead, onActiveClip, activeClip]);

  // Resume play after clip/video element remounts while still in playing state.
  useEffect(() => {
    if (!playing || !activeSeg) return;
    const v = videoRef.current;
    if (!v) return;
    const start = () => {
      snapMediaToPlayhead(activeSeg, playheadRef.current);
      void v.play().catch(() => undefined);
    };
    if (v.readyState >= 1) start();
    else v.addEventListener("loadeddata", start, { once: true });
  }, [playing, videoSrc, activeSeg?.clipIndex]);

  useEffect(() => {
    if (playing) return;
    videoRef.current?.pause();
    audioRef.current?.pause();
  }, [playing]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
      if (e.code === "Space") {
        e.preventDefault();
        setPlaying((p) => !p);
      } else if (e.code === "ArrowLeft") {
        e.preventDefault();
        seekBy(e.shiftKey ? -5 : -1);
      } else if (e.code === "ArrowRight") {
        e.preventDefault();
        seekBy(e.shiftKey ? 5 : 1);
      } else if (e.code === "Home") {
        e.preventDefault();
        seekTo(0);
      } else if (e.code === "End") {
        e.preventDefault();
        seekTo(duration);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  function seekTo(t: number) {
    setPlaying(false);
    const next = Math.max(0, Math.min(duration, t));
    onPlayhead(next);
    const seg = segmentAt(segments, next);
    if (seg) onActiveClip(seg.clipIndex);
  }

  function seekBy(delta: number) {
    seekTo(playheadRef.current + delta);
  }

  function seekNextFx() {
    const marks = segments
      .filter((s) => s.transition === "jigsaw" || s.gun)
      .map((s) => {
        if (s.transition === "jigsaw") return Math.max(0, s.outEnd - s.transitionDur * 0.55);
        return s.outStart + Math.min(1.0, (s.outEnd - s.outStart) * 0.35);
      })
      .filter((t) => t > playheadRef.current + 0.15);
    if (!marks.length) {
      seekTo(0);
      return;
    }
    seekTo(marks[0]);
  }

  // Fragment: preview + controls become separate grid cells in the studio layout
  // (parent uses display:grid areas). Controls never sit inside the preview box.
  return (
    <>
      <div
        className="seq-preview"
        aria-label="Preview"
        onClick={() => {
          if (!showMaster) setPlaying((p) => !p);
        }}
        title={showMaster ? "Rendered montage" : "Rough cut. Click to play or pause the source clips."}
      >
        <div className="ai-placement-badge">
          {showMaster ? "Rendered master" : "Rough cut — effects are not shown"}
        </div>
        <div className={`seq-stage ${inTransition ? "seq-stage-fx" : ""} ${isJigsaw ? "seq-stage-jigsaw" : ""}`}>
          {showMaster ? (
            <video
              key={masterSrc}
              src={masterSrc}
              controls
              playsInline
              onError={() => {
                setMasterMissing(true);
                setShowMaster(false);
              }}
            />
          ) : videoSrc ? (
            <video
              key={`v${activeSeg?.videoIndex ?? "x"}`}
              ref={videoRef}
              src={videoSrc}
              playsInline
              muted
              preload="auto"
            />
          ) : (
            <div className="muted">No clips in sequence</div>
          )}
          {showMaster ? null : <audio ref={audioRef} src={musicSrc} preload="auto" />}
          {!showMaster && isJigsaw ? (
            <div className="seq-jigsaw-overlay" aria-hidden>
              <div className="seq-jigsaw-pieces">
                {[0, 1, 2, 3, 4, 5].map((n) => (
                  <div key={n} className={`seq-jigsaw-piece p${n}`} />
                ))}
              </div>
              <div className="seq-jigsaw-caption">Puzzle cut</div>
            </div>
          ) : null}
          {!showMaster && inTransition && !isJigsaw && activeSeg?.transition ? (
            <div className={`seq-fx-banner seq-fx-${String(activeSeg.transition)}`}>
              <div className="seq-fx-banner-title">{transitionLabel(activeSeg.transition)}</div>
            </div>
          ) : null}
          {!showMaster && inGunWindow ? (
            <div className="seq-gun-outline" aria-hidden>
              <svg viewBox="0 0 200 120" className="seq-gun-svg">
                <path
                  d="M28 68 h70 l12-10 h22 l18 10 h22 v12 h-18 l-10 14 h-30 l-14-14 h-72 z"
                  fill="none"
                  stroke="#f5c542"
                  strokeWidth="3.5"
                  strokeLinejoin="round"
                />
                <path d="M40 80 h36" stroke="#ffe08a" strokeWidth="2.5" />
                <circle cx="155" cy="74" r="5" fill="none" stroke="#f5c542" strokeWidth="2.5" />
              </svg>
            </div>
          ) : null}
          {!showMaster
            ? hits
                .filter((h) => h.kind === "text")
                .map((t, i) => (
                  <div key={`tx-${i}`} className="seq-text-overlay">
                    {t.label}
                  </div>
                ))
            : null}
        </div>
      </div>

      <div className="seq-controls seq-controls-compact" aria-label="Playback and clip info">
        <div className="seq-dock-play">
          <div className="seq-dock">
          <div className="seq-transport" role="toolbar">
            <button className="btn transport-btn" type="button" title="Go to start (Home)" onClick={() => seekTo(0)}>
              ⏮
            </button>
            <button className="btn transport-btn" type="button" title="Back 5s" onClick={() => seekBy(-5)}>
              −5s
            </button>
            <button className="btn transport-btn" type="button" title="Back 1s" onClick={() => seekBy(-1)}>
              ⏪
            </button>
            <button
              className="btn btn-primary transport-btn transport-play"
              type="button"
              title="Play / Pause (Space)"
              onClick={() => setPlaying((p) => !p)}
            >
              {playing ? "⏸" : "▶"}
            </button>
            <button
              className="btn transport-btn"
              type="button"
              title="Stop and return to start"
              onClick={() => {
                setPlaying(false);
                seekTo(0);
              }}
            >
              ⏹
            </button>
            <button className="btn transport-btn" type="button" title="Forward 1s" onClick={() => seekBy(1)}>
              ⏩
            </button>
            <button className="btn transport-btn" type="button" title="Forward 5s" onClick={() => seekBy(5)}>
              +5s
            </button>
            <button className="btn transport-btn" type="button" title="Go to end" onClick={() => seekTo(duration)}>
              ⏭
            </button>
            <button className="btn transport-btn transport-fx" type="button" title="Next FX" onClick={() => seekNextFx()}>
              Next FX
            </button>
            <button
              className="btn transport-btn"
              type="button"
              title="Play the finished file. The window above is only the source clips."
              onClick={() => {
                setMasterMissing(false);
                setPlaying(false);
                setShowMaster((on) => !on);
              }}
            >
              {showMaster ? "Rough cut" : "Rendered"}
            </button>
          </div>

          </div>
          <label className="seq-scrub">
            <span className="seq-time">
              {showMaster ? "Finished file" : `${fmt(playheadSec)} / ${fmt(duration)}`}
              {!showMaster && activeSeg ? ` · Clip ${activeSeg.clipIndex + 1} · ${recipeLabel(activeSeg.recipe)}` : ""}
              {masterMissing ? " · Rendered file is not available" : ""}
            </span>
            <input
              type="range"
              min={0}
              max={duration}
              step={0.05}
              value={Math.min(playheadSec, duration)}
              onChange={(e) => seekTo(Number(e.target.value))}
              aria-label="Scrub timeline"
            />
          </label>
        </div>

        <aside className="seq-now" aria-label="Kills and effects at playhead">
          <strong>Now</strong>
          {hits.length ? (
            <ul>
              {hits.map((h, i) => (
                <li key={`${h.kind}-${i}`}>
                  <span className={`hit-kind hit-${h.kind}`}>{h.kind === "transition" ? "fx" : h.kind}</span>{" "}
                  {effectLabel(h.label)}
                  {h.detail ? <span className="muted"> — {h.detail}</span> : null}
                </li>
              ))}
            </ul>
          ) : (
            <div className="muted">No kill or FX at this time</div>
          )}
        </aside>
      </div>
    </>
  );
}

function fmt(sec: number): string {
  const s = Math.max(0, sec);
  const m = Math.floor(s / 60);
  const r = s - m * 60;
  return `${m}:${r.toFixed(1).padStart(4, "0")}`;
}
