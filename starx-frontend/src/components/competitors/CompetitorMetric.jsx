function formatMetric(value) {
  if (value === null || value === undefined) return "—";
  const numericValue = Number(value);
  if (!Number.isFinite(numericValue)) return "—";
  return new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 1 }).format(numericValue);
}

export default function CompetitorMetric({ label, value, delta }) {
  const numericDelta = Number(delta);
  const hasDelta = delta !== null && delta !== undefined && Number.isFinite(numericDelta) && numericDelta !== 0;
  const isUp = numericDelta > 0;
  const deltaLabel = `较上次更新${isUp ? "增长" : "减少"} ${formatMetric(Math.abs(numericDelta))}`;

  return (
    <div className="monitor-metric">
      <span>{label}</span>
      <strong>{formatMetric(value)}</strong>
      {hasDelta ? (
        <small className={`monitor-metric-trend ${isUp ? "is-up" : "is-down"}`} aria-label={deltaLabel} title={deltaLabel}>
          <span className="monitor-trend-icon" aria-hidden="true">{isUp ? "↗" : "↘"}</span>
          <span>{formatMetric(Math.abs(numericDelta))}</span>
        </small>
      ) : null}
    </div>
  );
}
