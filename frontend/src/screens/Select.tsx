import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { confirmRecommendations, getRecommendations } from "../api/montage";
import { useProjectStore } from "../state/projectStore";

export function Select() {
  const { taskId = "" } = useParams();
  const nav = useNavigate();
  const density = useProjectStore((s) => s.density);
  const { setPlays, setSelectedIds, selectedIds, setTaskId, togglePlay } = useProjectStore();
  const [seq, setSeq] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const plays = useProjectStore((s) => s.plays);

  useEffect(() => {
    setTaskId(taskId);
    let cancel = false;
    void getRecommendations(taskId, density)
      .then((r) => {
        if (cancel) return;
        setPlays(r.plays);
        setSelectedIds(r.recommended_ids);
        const sf = r.sequence_flow;
        setSeq(
          `flow ${sf.combined.toFixed(2)} · pacing ${(sf as { pacing?: number }).pacing?.toFixed(2) ?? "—"} · arc ${(sf as { arc?: number }).arc?.toFixed(2) ?? "—"}`
        );
      })
      .catch((e: unknown) => {
        if (!cancel) setError(e instanceof Error ? e.message : "Failed to load recommendations");
      });
    return () => {
      cancel = true;
    };
  }, [taskId, density, setPlays, setSelectedIds, setTaskId]);

  async function continueCompose() {
    setBusy(true);
    setError("");
    try {
      await confirmRecommendations(taskId, selectedIds, density);
      nav(`/jobs/${taskId}/compose`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Compose failed");
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <h1>Recommended plays</h1>
      <p className="muted">{seq || "Scoring…"} — toggle clips, then compose for the editor.</p>
      {error ? <div className="error">{error}</div> : null}
      <div className="grid-cards" style={{ marginTop: 16 }}>
        {plays.map((p) => {
          const on = selectedIds.includes(p.id);
          return (
            <button
              key={p.id}
              type="button"
              className={`play-card ${on ? "on" : ""}`}
              onClick={() => togglePlay(p.id)}
            >
              <div style={{ fontWeight: 700 }}>
                {p.play_label || "unlabeled"} · {p.kill_count}k
              </div>
              <div className="muted">
                V{p.video_index} @ {p.kill_timestamps_sec.map((t) => t.toFixed(1)).join(", ")}s
              </div>
              <div style={{ marginTop: 6 }}>
                flow {p.flow.combined.toFixed(2)} (impact {p.flow.impact.toFixed(2)})
              </div>
              {p.recommended ? <div style={{ color: "var(--accent-2)" }}>AI pick</div> : null}
            </button>
          );
        })}
      </div>
      <div style={{ marginTop: 16, display: "flex", gap: 8 }}>
        <button className="btn btn-primary" type="button" disabled={busy || !selectedIds.length} onClick={() => void continueCompose()}>
          {busy ? "Composing…" : `Compose ${selectedIds.length} plays`}
        </button>
      </div>
    </div>
  );
}
