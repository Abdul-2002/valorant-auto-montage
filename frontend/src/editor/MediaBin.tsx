import { useState } from "react";
import type { MontageScript, TimelineProject } from "../api/types";
import { effectLabel, hitLabel, recipeLabel, transitionLabel } from "./fxLabels";

export type MediaBinTab = "videos" | "effects" | "other";

type Props = {
  taskId: string;
  script: MontageScript;
  timeline: TimelineProject | null;
  activeClip: number;
  songDur: number;
  songName: string;
  onSelectClip: (i: number) => void;
  onReorder: (from: number, to: number) => void;
  onPatchClip: (index: number, patch: Partial<MontageScript["clips"][number]>) => void;
  onSeek: (sec: number) => void;
};

export function MediaBin({
  taskId,
  script,
  timeline,
  activeClip,
  songDur,
  songName,
  onSelectClip,
  onReorder,
  onPatchClip,
  onSeek,
}: Props) {
  const [tab, setTab] = useState<MediaBinTab>("videos");
  const clip = script.clips[activeClip] ?? null;
  const enabledCount = script.clips.filter((c) => c.enabled !== false).length;

  return (
    <aside className="media-bin">
      <div className="media-bin-rail" role="tablist" aria-label="Media library">
        {(
          [
            ["videos", "Videos"],
            ["effects", "Effects"],
            ["other", "Other"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            className={`media-bin-tab ${tab === id ? "active" : ""}`}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="media-bin-body" role="tabpanel">
        {tab === "videos" ? (
          <>
            <div className="media-bin-hint">
              {enabledCount} clip{enabledCount === 1 ? "" : "s"} · AI placed · click to select
            </div>
            <div className="media-bin-grid">
              {script.clips.map((c, i) => {
                const off = c.enabled === false;
                const thumb = `/montage/${encodeURIComponent(taskId)}/media/video/${c.video_index}`;
                return (
                  <button
                    key={i}
                    type="button"
                    className={`media-card ${i === activeClip ? "active" : ""} ${off ? "off" : ""}`}
                    onClick={() => {
                      onSelectClip(i);
                      onSeek(Math.max(0, Number(c.output_start_sec ?? 0) - (timeline?.phase_offset_sec ?? 0)));
                    }}
                  >
                    <div className="media-card-thumb">
                      <video src={thumb} muted preload="metadata" playsInline />
                      <span className="media-card-num">#{i + 1}</span>
                    </div>
                    <div className="media-card-meta">
                      <strong>{recipeLabel(c.recipe)}</strong>
                      <span className="muted">
                        {c.transition_to_next?.type ? transitionLabel(c.transition_to_next.type) : "End"}
                      </span>
                    </div>
                    <div className="media-card-actions" onClick={(e) => e.stopPropagation()}>
                      <button
                        className="btn"
                        type="button"
                        disabled={i === 0}
                        title="Move earlier"
                        onClick={() => onReorder(i, i - 1)}
                      >
                        ↑
                      </button>
                      <button
                        className="btn"
                        type="button"
                        disabled={i >= script.clips.length - 1}
                        title="Move later"
                        onClick={() => onReorder(i, i + 1)}
                      >
                        ↓
                      </button>
                      <button
                        className="btn"
                        type="button"
                        title={off ? "Enable clip" : "Disable clip"}
                        onClick={() => onPatchClip(i, { enabled: off })}
                      >
                        {off ? "On" : "Off"}
                      </button>
                    </div>
                  </button>
                );
              })}
            </div>
          </>
        ) : null}

        {tab === "effects" ? (
          <>
            <div className="media-bin-hint">
              {clip ? (
                <>
                  Effects on clip #{activeClip + 1}. Toggle what AI placed — full bake on Export.
                </>
              ) : (
                "Select a clip first"
              )}
            </div>
            {clip ? (
              <div className="fx-catalog">
                <FxToggle
                  title="Puzzle cut (jigsaw)"
                  detail="Assembles next clip from scene pieces"
                  on={clip.transition_to_next?.type === "jigsaw"}
                  onChange={(on) =>
                    onPatchClip(activeClip, {
                      transition_to_next: on
                        ? { type: "jigsaw", duration_sec: 0.75 }
                        : clip.transition_to_next?.type === "jigsaw"
                          ? { type: "whip_pan", duration_sec: 0.14 }
                          : clip.transition_to_next,
                    })
                  }
                />
                <FxToggle
                  title="Weapon glow"
                  detail="Neon outline on the gun during slow-mo"
                  on={Boolean(clip.gun_candidate)}
                  onChange={(on) => onPatchClip(activeClip, { gun_candidate: on })}
                />
                <FxToggle
                  title="Ghost freeze"
                  detail="Enemy silhouette freeze after the kill"
                  on={Boolean(clip.ghost_candidate)}
                  onChange={(on) => onPatchClip(activeClip, { ghost_candidate: on })}
                />
                <label className="fx-field">
                  Style pack
                  <select
                    value={clip.recipe || "clean"}
                    onChange={(e) => onPatchClip(activeClip, { recipe: e.target.value })}
                  >
                    <option value="clean">Clean hit</option>
                    <option value="slow">Slow-mo</option>
                    <option value="punch">Punch zoom</option>
                    <option value="cinematic">Cinematic</option>
                  </select>
                </label>
                <label className="fx-field">
                  Kill flash
                  <select
                    value={clip.hit_style || "flash_blur"}
                    onChange={(e) => onPatchClip(activeClip, { hit_style: e.target.value })}
                  >
                    <option value="glow">Glow flash</option>
                    <option value="flash_blur">Flash blur</option>
                    <option value="flash_shake">Flash shake</option>
                    <option value="impact">Impact</option>
                    <option value="none">No hit FX</option>
                  </select>
                </label>
                <label className="fx-field">
                  Next transition
                  <select
                    value={clip.transition_to_next?.type || "hard_cut"}
                    onChange={(e) => {
                      const type = e.target.value;
                      if (type === "hard_cut") {
                        onPatchClip(activeClip, { transition_to_next: null });
                        return;
                      }
                      const dur = type === "jigsaw" ? 0.75 : type === "pop_slam" ? 0.22 : 0.14;
                      onPatchClip(activeClip, { transition_to_next: { type, duration_sec: dur } });
                    }}
                  >
                    <option value="hard_cut">Hard cut</option>
                    <option value="jigsaw">Puzzle cut</option>
                    <option value="whip_pan">Whip pan</option>
                    <option value="push">Push zoom</option>
                    <option value="pop_slam">Pop slam</option>
                    <option value="flash_white">White flash</option>
                  </select>
                </label>
                <div className="muted" style={{ fontSize: 12 }}>
                  Now: {recipeLabel(clip.recipe)} · {hitLabel(clip.hit_style)} ·{" "}
                  {transitionLabel(clip.transition_to_next?.type)}
                </div>
              </div>
            ) : null}
          </>
        ) : null}

        {tab === "other" ? (
          <div className="fx-catalog">
            <div className="media-bin-hint">Song & titles</div>
            <div className="other-row">
              <strong>Song</strong>
              <span className="muted">
                {timeline?.tracks.music[0]?.label || songName || "—"}
                {songDur ? ` · ${songDur.toFixed(1)}s` : ""}
              </span>
            </div>
            <div className="other-row">
              <strong>Text overlays</strong>
              <span className="muted">{timeline?.tracks.text.length ?? 0}</span>
            </div>
            {(timeline?.tracks.text || []).map((t) => (
              <div key={t.id} className="other-text-item">
                {effectLabel(t.label)} · {t.start_sec.toFixed(1)}–{t.end_sec.toFixed(1)}s
              </div>
            ))}
            {clip ? (
              <>
                <div className="media-bin-hint" style={{ marginTop: 12 }}>
                  Advanced trim (clip #{activeClip + 1})
                </div>
                <label className="fx-field">
                  In (source sec)
                  <input
                    type="number"
                    step="0.05"
                    value={Number(clip.start_sec.toFixed(3))}
                    onChange={(e) => onPatchClip(activeClip, { start_sec: Number(e.target.value) })}
                  />
                </label>
                <label className="fx-field">
                  Out (source sec)
                  <input
                    type="number"
                    step="0.05"
                    value={Number(clip.end_sec.toFixed(3))}
                    onChange={(e) => onPatchClip(activeClip, { end_sec: Number(e.target.value) })}
                  />
                </label>
              </>
            ) : null}
          </div>
        ) : null}
      </div>
    </aside>
  );
}

function FxToggle({
  title,
  detail,
  on,
  onChange,
}: {
  title: string;
  detail: string;
  on: boolean;
  onChange: (on: boolean) => void;
}) {
  return (
    <label className={`fx-toggle ${on ? "on" : ""}`}>
      <input type="checkbox" checked={on} onChange={(e) => onChange(e.target.checked)} />
      <span>
        <strong>{title}</strong>
        <span className="muted">{detail}</span>
      </span>
    </label>
  );
}
