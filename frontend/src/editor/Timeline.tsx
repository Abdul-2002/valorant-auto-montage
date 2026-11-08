import { useRef } from "react";
import type { MontageScript, TimelineOverlay, TimelineProject } from "../api/types";
import { recipeLabel } from "./fxLabels";

type Props = {
  timeline: TimelineProject;
  script: MontageScript;
  active: number;
  playheadSec: number;
  onSelectClip: (i: number) => void;
  onPlayhead: (sec: number) => void;
  onTrimClip: (index: number, edge: "in" | "out", deltaSec: number) => void;
  onSlipClip: (index: number, deltaSec: number) => void;
  onMoveOverlay: (track: "text" | "music" | "effects" | "video", id: string, deltaSec: number) => void;
  onResizeOverlay: (
    track: "text" | "music" | "effects" | "video",
    id: string,
    edge: "in" | "out",
    deltaSec: number
  ) => void;
};

type DragMode = "move" | "in" | "out";

function usePxToSec(duration: number) {
  const ref = useRef<HTMLDivElement>(null);
  function pxToSec(dx: number): number {
    const el = ref.current;
    if (!el) return 0;
    return (dx / Math.max(1, el.clientWidth)) * duration;
  }
  return { ref, pxToSec };
}

function Tile({
  item,
  duration,
  selected,
  hot,
  draggable,
  resizable,
  onSelect,
  onDrag,
}: {
  item: TimelineOverlay;
  duration: number;
  selected?: boolean;
  hot?: boolean;
  draggable: boolean;
  resizable: boolean;
  onSelect: () => void;
  onDrag: (mode: DragMode, deltaPx: number) => void;
}) {
  const left = (item.start_sec / duration) * 100;
  const width = Math.max(1.2, ((item.end_sec - item.start_sec) / duration) * 100);

  function startPointer(mode: DragMode, ev: React.PointerEvent) {
    if (!draggable && mode === "move") return;
    if (!resizable && (mode === "in" || mode === "out")) return;
    ev.preventDefault();
    ev.stopPropagation();
    const target = ev.currentTarget as HTMLElement;
    target.setPointerCapture(ev.pointerId);
    let lastX = ev.clientX;
    const move = (e: PointerEvent) => {
      const dx = e.clientX - lastX;
      lastX = e.clientX;
      onDrag(mode, dx);
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    onSelect();
  }

  return (
    <div
      className={`tl-tile ${selected ? "active" : ""} ${hot ? "tl-tile-hot" : ""}`}
      style={{ left: `${left}%`, width: `${width}%`, background: item.color || "#2b3348" }}
      title={`${item.label}\n${item.start_sec.toFixed(2)}s – ${item.end_sec.toFixed(2)}s\nDrag body to move · drag edges to trim`}
      onPointerDown={(e) => startPointer("move", e)}
      onClick={(e) => {
        e.stopPropagation();
        onSelect();
      }}
    >
      {resizable ? (
        <span
          className="tl-handle tl-handle-in"
          onPointerDown={(e) => startPointer("in", e)}
          title="Trim start"
        />
      ) : null}
      <span className="tl-tile-label">{item.label}</span>
      {resizable ? (
        <span
          className="tl-handle tl-handle-out"
          onPointerDown={(e) => startPointer("out", e)}
          title="Trim end"
        />
      ) : null}
    </div>
  );
}

function Lane({
  name,
  items,
  duration,
  active,
  playheadSec,
  editable,
  onSelectClip,
  onPlayhead,
  onTileDrag,
}: {
  name: string;
  items: TimelineOverlay[];
  duration: number;
  active: number;
  playheadSec: number;
  editable: boolean;
  onSelectClip: (i: number) => void;
  onPlayhead: (sec: number) => void;
  onTileDrag: (item: TimelineOverlay, mode: DragMode, deltaPx: number) => void;
}) {
  const { ref, pxToSec } = usePxToSec(duration);

  const tall = name === "Effects";
  return (
    <div className={`tl-lane ${tall ? "tl-lane-fx" : ""}`}>
      <div className="tl-lane-label">{name}</div>
      <div
        ref={ref}
        className={`tl-track ${tall ? "tl-track-fx" : ""}`}
        onClick={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          const t = ((e.clientX - rect.left) / rect.width) * duration;
          onPlayhead(Math.max(0, Math.min(duration, t)));
        }}
      >
        <div className="tl-playhead" style={{ left: `${(playheadSec / duration) * 100}%` }} />
        {items.map((item) => {
          const hot = playheadSec >= item.start_sec && playheadSec < item.end_sec;
          const selected = item.kind === "video" && item.clip_index === active;
          return (
            <Tile
              key={item.id}
              item={item}
              duration={duration}
              selected={selected}
              hot={hot}
              draggable={editable}
              resizable={editable}
              onSelect={() => {
                if (typeof item.clip_index === "number") onSelectClip(item.clip_index);
                onPlayhead(item.start_sec);
              }}
              onDrag={(mode, deltaPx) => {
                const deltaSec = pxToSec(deltaPx);
                if (Math.abs(deltaSec) < 0.0005) return;
                onTileDrag(item, mode, deltaSec);
              }}
            />
          );
        })}
      </div>
    </div>
  );
}

export function Timeline({
  timeline,
  script,
  active,
  playheadSec,
  onSelectClip,
  onPlayhead,
  onTrimClip,
  onSlipClip,
  onMoveOverlay,
  onResizeOverlay,
}: Props) {
  const d = Math.max(0.1, timeline.duration_sec);
  const { ref: videoRef, pxToSec } = usePxToSec(d);

  const enabledSpans = (script.clips || [])
    .map((c, i) => {
      if (c.enabled === false) return null;
      const start = Number(c.output_start_sec ?? 0);
      const end = Number(c.output_end_sec ?? start + Math.max(0.2, c.end_sec - c.start_sec));
      return { i, start, end, c };
    })
    .filter(Boolean) as { i: number; start: number; end: number; c: (typeof script.clips)[number] }[];
  const t0 = enabledSpans.length ? Math.min(...enabledSpans.map((s) => s.start)) : 0;
  const videoItems: TimelineOverlay[] = enabledSpans.map(({ i, start, end, c }) => ({
    id: `v-${i}`,
    kind: "video" as const,
    label: `Clip ${i + 1} · ${recipeLabel(c.recipe)}`,
    start_sec: start - t0,
    end_sec: end - t0,
    clip_index: i,
    color: undefined,
  }));

  function videoTileDrag(item: TimelineOverlay, mode: DragMode, deltaSec: number) {
    const index = item.clip_index;
    if (typeof index !== "number") return;
    if (mode === "in") onTrimClip(index, "in", deltaSec);
    else if (mode === "out") onTrimClip(index, "out", deltaSec);
    else onSlipClip(index, deltaSec);
  }

  return (
    <div className="editor-timeline">
      <div className="tl-header">
        <strong>Timeline</strong>
        <span className="muted">
          {d.toFixed(1)}s · {playheadSec.toFixed(1)}s · drag red edges to trim · drag clip body to slip
        </span>
      </div>

      <div className="tl-lane tl-lane-clips">
        <div className="tl-lane-label">Clips</div>
        <div
          ref={videoRef}
          className="tl-track tl-track-video"
          onClick={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            const t = ((e.clientX - rect.left) / rect.width) * d;
            onPlayhead(Math.max(0, Math.min(d, t)));
          }}
        >
          <div className="tl-playhead" style={{ left: `${(playheadSec / d) * 100}%` }} />
          {videoItems.map((item) => {
            const i = item.clip_index ?? 0;
            const hot = playheadSec >= item.start_sec && playheadSec < item.end_sec;
            return (
              <Tile
                key={item.id}
                item={item}
                duration={d}
                selected={i === active}
                hot={hot}
                draggable
                resizable
                onSelect={() => {
                  onSelectClip(i);
                  onPlayhead(item.start_sec);
                }}
                onDrag={(mode, deltaPx) => {
                  const deltaSec = pxToSec(deltaPx);
                  if (Math.abs(deltaSec) < 0.0005) return;
                  videoTileDrag(item, mode, deltaSec);
                }}
              />
            );
          })}
        </div>
      </div>
      <Lane
        name="Song"
        items={timeline.tracks.music}
        duration={d}
        active={active}
        playheadSec={playheadSec}
        editable
        onSelectClip={onSelectClip}
        onPlayhead={onPlayhead}
        onTileDrag={(item, mode, deltaSec) => {
          if (mode === "move") onMoveOverlay("music", item.id, deltaSec);
          else onResizeOverlay("music", item.id, mode, deltaSec);
        }}
      />
      <Lane
        name="Effects"
        items={timeline.tracks.effects}
        duration={d}
        active={active}
        playheadSec={playheadSec}
        editable={false}
        onSelectClip={onSelectClip}
        onPlayhead={onPlayhead}
        onTileDrag={() => undefined}
      />
      {timeline.tracks.text.length ? (
        <Lane
          name="Text"
          items={timeline.tracks.text}
          duration={d}
          active={active}
          playheadSec={playheadSec}
          editable
          onSelectClip={onSelectClip}
          onPlayhead={onPlayhead}
          onTileDrag={(item, mode, deltaSec) => {
            if (mode === "move") onMoveOverlay("text", item.id, deltaSec);
            else onResizeOverlay("text", item.id, mode, deltaSec);
          }}
        />
      ) : null}
    </div>
  );
}
