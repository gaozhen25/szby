const SERIES = [
  { key: "followers", label: "粉丝", color: "#00d8ff" },
  { key: "following", label: "关注", color: "#a78bfa" },
  { key: "works", label: "作品", color: "#40d080" },
  { key: "liked", label: "获赞", color: "#ffb454" },
];

function formatMetric(value) {
  return new Intl.NumberFormat("zh-CN", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

function seriesValues(history, key) {
  return (history || [])
    .map((point) => ({
      capturedAt: point.capturedAt,
      value: Number(point.metrics?.[key]),
    }))
    .filter((point) => Number.isFinite(point.value));
}

function sparklinePoints(values, width = 150, height = 34) {
  if (!values.length) return `0,${height / 2} ${width},${height / 2}`;
  if (values.length === 1) {
    const y = height / 2;
    return `0,${y.toFixed(1)} ${width},${y.toFixed(1)}`;
  }
  const min = Math.min(...values.map((point) => point.value));
  const max = Math.max(...values.map((point) => point.value));
  const spread = max - min || 1;
  return values.map((point, index) => {
    const x = values.length === 1 ? width / 2 : (index / (values.length - 1)) * width;
    const y = height - 3 - ((point.value - min) / spread) * (height - 6);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
}

export default function CompetitorAccountHistory({ history = [] }) {
  return (
    <section className="monitor-account-history" aria-label="博主历史数据变化">
      <div className="monitor-history-title">
        <strong>博主数据趋势</strong>
        <span>近30天 · {history.length} 个快照</span>
      </div>
      <div className="monitor-history-grid">
        {SERIES.map((series) => {
          const values = seriesValues(history, series.key);
          const latest = values.at(-1)?.value;
          return <div className="monitor-history-series" key={series.key}>
            <span>{series.label}</span>
            <strong>{Number.isFinite(latest) ? formatMetric(latest) : "—"}</strong>
            <svg
              viewBox="0 0 150 34"
              role="img"
              aria-label={`${series.label}${values.length ? "变化" : "待采集基线"}曲线`}
              className={values.length ? undefined : "is-baseline"}
            >
              <polyline
                points={sparklinePoints(values)}
                fill="none"
                stroke={series.color}
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </div>;
        })}
      </div>
      {history.length < 2 ? <p>{history.length ? "当前仅有一次快照，曲线以水平线展示。" : "首次刷新完成前，曲线以水平基线展示。"}</p> : null}
    </section>
  );
}
