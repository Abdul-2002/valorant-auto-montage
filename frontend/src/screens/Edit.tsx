import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getScript } from "../api/montage";
import { buildTimelineFromScript } from "../editor/buildTimeline";
import { PreviewPlayer } from "../editor/PreviewPlayer";
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
    activeClip,
    setActiveClip,
    patchClip,
    titleText,
    songName,
    density,
    applyAiResult,
  } = useProjectStore();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState("");

  useEffect(() => {
    if (script && timeline) return;
    let cancel = false;
    void getScript(taskId)
      .then((r) => {
        if (cancel) return;
        const clips = r.script.clips.map((c) => ({ ...c, enabled: c.enabled !== false }));
        const next = { ...r.script, clips };
        setScript(next);
        setTimeline(
          buildTimelineFromScript(next, {
            titleText,
            songName,
            engagement: true,
          })
        );
      })
      .catch((e: unknown) => {
        if (!cancel) setError(e instanceof Error ? e.message : "Script not ready — run AI Montage Maker");
      });
    return () => {
      cancel = true;
    };
  }, [taskId, script, timeline, setScript, setTimeline, titleText, songName]);

  // Rebuild timeline when clips are edited (trim/recipe).
  useEffect(() => {
    if (!script) return;
    setTimeline(
      buildTimelineFromScript(script, {
        titleText,
        songName,
        engagement: true,
      })
    );
  }, [script, titleText, songName, setTimeline]);

  const clip = script?.clips[activeClip] ?? null;

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
    } catch (e) {
      setError(e instanceof Error ? e.message : "AI remake failed");
    } finally {
      setBusy(false);
      setPhase("");
    }
  }

  return (
    <div>
      <div className="topbar" style={{ borderBottom: "1px solid var(--border)" }}>
        <div>
          <strong>Editor</strong> <span className="muted">{taskId.slice(0, 10)}…</span>
          {phase ? <span className="muted"> · {phase}</span> : null}
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button className="btn" type="button" disabled={busy} onClick={() => void rerunAi()}>
            {busy ? "AI…" : "AI Montage Maker"}
          </button>
          <Link className="btn btn-ghost" to={`/jobs/${taskId}/select`}>
            Select
          </Link>
          <button className="btn btn-primary" type="button" disabled={!script} onClick={() => nav(`/jobs/${taskId}/review`)}>
            Review & render
          </button>
        </div>
      </div>
      {error ? <div className="page error">{error}</div> : null}
      {!error || script ? (
        <div className="editor-layout">
          <aside className="editor-media">
            <h3 style={{ marginTop: 0 }}>Clips</h3>
            <div className="muted" style={{ marginBottom: 8 }}>
              {script?.clips.length ?? 0} video · {timeline?.tracks.text.length ?? 0} text ·{" "}
              {timeline?.tracks.effects.length ?? 0} fx
            </div>
            {(script?.clips || []).map((c, i) => (
              <button
                key={i}
                type="button"
                className={`btn ${i === activeClip ? "btn-primary" : ""}`}
                style={{ display: "block", width: "100%", marginBottom: 6, textAlign: "left" }}
                onClick={() => setActiveClip(i)}
              >
                #{i + 1} V{c.video_index} · {c.recipe || "clean"}
                {c.ghost_candidate ? " · ghost" : ""}
              </button>
            ))}
            <h4>Text track</h4>
            {(timeline?.tracks.text || []).map((t) => (
              <div key={t.id} className="muted" style={{ fontSize: 12, marginBottom: 4 }}>
                {t.label} ({t.start_sec.toFixed(1)}–{t.end_sec.toFixed(1)})
              </div>
            ))}
            <h4>Music</h4>
            <div className="muted" style={{ fontSize: 12 }}>
              {timeline?.tracks.music[0]?.label || "—"} · {timeline?.duration_sec.toFixed(1) ?? "—"}s
            </div>
          </aside>
          <div className="editor-preview">
            <PreviewPlayer
              clip={clip}
              src={clip ? `/montage/${encodeURIComponent(taskId)}/media/video/${clip.video_index}` : undefined}
            />
          </div>
          <aside className="editor-side">
            <h3 style={{ marginTop: 0 }}>Inspector</h3>
            {clip ? (
              <div style={{ display: "grid", gap: 10 }}>
                <label>
                  Enabled
                  <input
                    type="checkbox"
                    checked={clip.enabled !== false}
                    onChange={(e) => patchClip(activeClip, { enabled: e.target.checked })}
                  />
                </label>
                <label>
                  In (source sec)
                  <input
                    type="number"
                    step="0.05"
                    value={clip.start_sec}
                    onChange={(e) => patchClip(activeClip, { start_sec: Number(e.target.value) })}
                  />
                </label>
                <label>
                  Out (source sec)
                  <input
                    type="number"
                    step="0.05"
                    value={clip.end_sec}
                    onChange={(e) => patchClip(activeClip, { end_sec: Number(e.target.value) })}
                  />
                </label>
                <label>
                  Recipe / FX pack
                  <select
                    value={clip.recipe || "clean"}
                    onChange={(e) => patchClip(activeClip, { recipe: e.target.value })}
                  >
                    <option value="clean">clean</option>
                    <option value="slow">slow</option>
                    <option value="punch">punch</option>
                    <option value="cinematic">cinematic</option>
                  </select>
                </label>
                <label>
                  Hit style
                  <select
                    value={clip.hit_style || "flash_blur"}
                    onChange={(e) => patchClip(activeClip, { hit_style: e.target.value })}
                  >
                    <option value="flash_blur">flash_blur</option>
                    <option value="impact">impact</option>
                    <option value="none">none</option>
                  </select>
                </label>
                <div className="muted" style={{ fontSize: 12 }}>
                  Arc: {clip.arc_phase || "build"}
                  <br />
                  Ghost: {clip.ghost_candidate ? "yes" : "no"} · Gun outline: {clip.gun_candidate ? "yes" : "no"}
                  <br />
                  Transition: {clip.transition_to_next?.type || "hard_cut"}
                </div>
              </div>
            ) : (
              <div className="muted">Select a clip</div>
            )}
          </aside>
          {timeline ? <Timeline timeline={timeline} active={activeClip} onSelectClip={setActiveClip} /> : null}
        </div>
      ) : null}
    </div>
  );
}
