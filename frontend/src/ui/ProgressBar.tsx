type Props = {
  percent: number;
  label: string;
};

/** Determinate progress: percent 0–100 plus a phase label. */
export function ProgressBar({ percent, label }: Props) {
  const pct = Math.max(0, Math.min(100, Math.round(percent)));
  return (
    <div className="progress-wrap" role="status" aria-live="polite">
      <div className="progress-meta">
        <span>{label || "Working…"}</span>
        <span className="muted">{pct}%</span>
      </div>
      <div className="progress-track" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} role="progressbar">
        <div className="progress-fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
