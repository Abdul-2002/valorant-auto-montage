import type { TimelineOverlay, TimelineProject } from "../api/types";

type Props = {
  timeline: TimelineProject;
  active: number;
  onSelectClip: (i: number) => void;
};

function Track({
  name,
  items,
  duration,
  active,
  onSelectClip,
}: {
  name: string;
  items: TimelineOverlay[];
  duration: number;
  active: number;
  onSelectClip: (i: number) => void;
}) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>
        {name}
      </div>
      <div
        className="tl-track"
        style={{
          position: "relative",
          minHeight: 40,
          background: "#0e121a",
          borderRadius: 6,
          border: "1px solid var(--border)",
        }}
      >
        {items.map((item) => {
          const left = (item.start_sec / duration) * 100;
          const width = Math.max(0.8, ((item.end_sec - item.start_sec) / duration) * 100);
          const isVid = item.kind === "video";
          const selected = isVid && item.clip_index === active;
          return (
            <button
              key={item.id}
              type="button"
              className={`tl-clip ${selected ? "active" : ""}`}
              title={item.label}
              style={{
                position: "absolute",
                left: `${left}%`,
                width: `${width}%`,
                top: 4,
                bottom: 4,
                background: item.color || "#2b3348",
                borderColor: selected ? "var(--accent)" : "transparent",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
              onClick={() => {
                if (typeof item.clip_index === "number") onSelectClip(item.clip_index);
              }}
            >
              {item.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function Timeline({ timeline, active, onSelectClip }: Props) {
  const d = Math.max(0.1, timeline.duration_sec);
  return (
    <div className="editor-timeline">
      <div className="muted" style={{ marginBottom: 8 }}>
        AI timeline · {d.toFixed(1)}s · phase offset {timeline.phase_offset_sec.toFixed(2)}s
      </div>
      <Track name="VIDEO" items={timeline.tracks.video} duration={d} active={active} onSelectClip={onSelectClip} />
      <Track name="MUSIC" items={timeline.tracks.music} duration={d} active={active} onSelectClip={onSelectClip} />
      <Track name="TEXT / TITLES" items={timeline.tracks.text} duration={d} active={active} onSelectClip={onSelectClip} />
      <Track name="FX / KILLS / TRANSITIONS" items={timeline.tracks.effects} duration={d} active={active} onSelectClip={onSelectClip} />
    </div>
  );
}
