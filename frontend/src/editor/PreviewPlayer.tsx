import { useEffect, useRef } from "react";
import type { ScriptClip } from "../api/types";

type Props = {
  clip: ScriptClip | null;
  src?: string;
};

export function PreviewPlayer({ clip, src }: Props) {
  const ref = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    const v = ref.current;
    if (!v || !clip || !src) return;
    const onMeta = () => {
      try {
        v.currentTime = Math.max(0, clip.start_sec);
      } catch {
        /* ignore */
      }
    };
    v.addEventListener("loadedmetadata", onMeta);
    if (v.readyState >= 1) onMeta();
    return () => v.removeEventListener("loadedmetadata", onMeta);
  }, [clip, src]);

  if (!clip) {
    return <div className="muted">No clip selected</div>;
  }

  return (
    <div style={{ width: "100%", height: "100%", display: "grid", placeItems: "center", position: "relative" }}>
      {src ? (
        <video
          key={src}
          ref={ref}
          src={src}
          controls
          playsInline
          style={{ maxWidth: "100%", maxHeight: "100%" }}
        />
      ) : (
        <div className="muted" style={{ padding: 24, textAlign: "center" }}>
          V{clip.video_index} · {clip.start_sec.toFixed(2)}–{clip.end_sec.toFixed(2)}s
        </div>
      )}
      <div
        style={{
          position: "absolute",
          left: 12,
          top: 12,
          background: "rgba(0,0,0,0.65)",
          padding: "6px 10px",
          borderRadius: 6,
          fontSize: 12,
        }}
      >
        Rough cut — source clip only
      </div>
      <div
        style={{
          position: "absolute",
          left: 12,
          bottom: 12,
          background: "rgba(0,0,0,0.65)",
          padding: "6px 10px",
          borderRadius: 6,
          fontSize: 12,
        }}
      >
        {clip.recipe || "clean"} · {clip.hit_style || "hit"}
        {clip.ghost_candidate ? " · ghost" : ""}
      </div>
    </div>
  );
}
