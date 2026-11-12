import { useEffect, useMemo, useState } from "react";

import { starxApi } from "../api/starx";
import "../styles/data-dashboard.css";

const PIE_COLORS = ["#4ecfe6", "#c4b6ff", "#6adb9a", "#f2d28a"];
const TREND_METRICS = [
  ["likes", "点赞", "#4ecfe6"],
  ["comments", "评论", "#c4b6ff"],
  ["favorites", "收藏", "#6adb9a"],
  ["shares", "分享", "#f2d28a"],
];
const METRIC_META = {
  contents: { icon: "▦" },
  likes: { icon: "♥" },
  comments: { icon: "◌" },
  favorites: { icon: "★" },
  shares: { icon: "↗" },
};

function formatMetric(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
  const number = Number(value);
  return Math.abs(number) >= 10000
    ? `${(number / 10000).toFixed(number % 10000 === 0 ? 0 : 1)}万`
    : new Intl.NumberFormat("zh-CN").format(number);
}

function formatDelta(value) {
  if (value === null || value === undefined) return "待积累";
  return `${Number(value) > 0 ? "+" : ""}${formatMetric(value)}`;
}

function formatDateTime(value, fallback = "尚未更新") {
  if (!value) return fallback;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return fallback;
  return date.toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function formatPublishedAt(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
}

function DeltaValue({ value }) {
  const state = value === null || value === undefined
    ? "pending"
    : Number(value) > 0 ? "positive" : Number(value) < 0 ? "negative" : "neutral";
  return <span className={`dashboard-delta dashboard-delta-${state}`}>{formatDelta(value)}</span>;
}

function DashboardEmpty({ app, social }) {
  return (
    <article className="dashboard-empty" role="status">
      <div className="dashboard-empty-icon" aria-hidden="true">↗</div>
      <div>
        <h3>{social?.status === "unconfigured" ? "尚未配置平台账号" : "平台数据暂不可用"}</h3>
        <p>请确认账号档案中的平台账号或主页链接正确，小时采集完成后会自动生成作品趋势。</p>
        {(social?.notices || []).map((notice) => <p key={notice}>{notice}</p>)}
      </div>
      <button className="btn btn-primary" type="button" onClick={() => app.openAccountModal?.(app.currentAccount)}>
        去填写账号
      </button>
    </article>
  );
}

function DashboardLoadingPage() {
  return (
    <section className="dashboard-loading-page" role="status" aria-live="polite">
      <div className="dashboard-loading-copy">
        <span className="dashboard-loading-kicker">DATA DASHBOARD</span>
        <h2>正在加载作品互动数据</h2>
        <p>正在读取点赞、评论、收藏和分享快照，请稍候…</p>
      </div>
      <div className="dashboard-loading-progress" aria-hidden="true"><span /></div>
    </section>
  );
}

function TopContentCover({ content }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [content.coverUrl]);
  return (
    <div className="thumb">
      {content.coverUrl && !failed
        ? <img src={content.coverUrl} alt="" referrerPolicy="no-referrer" onError={() => setFailed(true)} />
        : <span aria-hidden="true">📄</span>}
    </div>
  );
}

function buildPieSegments(data, cx = 80, cy = 80, radius = 65) {
  let cumulative = 0;
  return data.map((item, index) => {
    const start = (cumulative / 100) * 360;
    cumulative += item.percentage;
    const end = (cumulative / 100) * 360;
    const point = (angle) => {
      const rad = ((angle - 90) * Math.PI) / 180;
      return [cx + radius * Math.cos(rad), cy + radius * Math.sin(rad)];
    };
    const [x1, y1] = point(start);
    const [x2, y2] = point(end);
    const isFullCircle = item.percentage >= 99.999;
    return {
      ...item,
      color: PIE_COLORS[index % PIE_COLORS.length],
      path: isFullCircle
        ? `M${cx},${cy - radius} A${radius},${radius} 0 1 1 ${cx},${cy + radius} A${radius},${radius} 0 1 1 ${cx},${cy - radius} Z`
        : `M${cx},${cy} L${x1},${y1} A${radius},${radius} 0 ${item.percentage > 50 ? 1 : 0} 1 ${x2},${y2} Z`,
    };
  });
}

function ContentTrend({
  trend,
  range,
  onRangeChange,
}) {
  const width = 620;
  const height = 270;
  const padding = { top: 24, right: 18, bottom: 20, left: 48 };
  const points = trend?.points || [];
  const available = TREND_METRICS.filter(([key]) => points.some((item) => item[key] !== null));
  const maximum = Math.max(
    ...available.flatMap(([key]) => points.map((item) => Number(item[key] || 0))),
    1,
  );
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const x = (index) => padding.left + (points.length <= 1 ? plotWidth / 2 : index * (plotWidth / (points.length - 1)));
  const y = (value) => padding.top + plotHeight - (Number(value || 0) / maximum) * plotHeight;
  const hasTrend = points.length >= 2 && available.length > 0;
  const latestPoint = points.at(-1);

  return (
    <div className="chart-card own-content-trend-card">
      <div className="chart-card-header">
        <div>
          <span className="section-kicker">数据轨迹</span>
          <h3>{trend?.title || "选择作品查看趋势"}</h3>
          <p>平台累计互动数据，按小时记录</p>
        </div>
        <div className="trend-range-switch" role="group" aria-label="趋势时间范围">
          {[[1, "24小时"], [7, "7天"], [30, "30天"]].map(([value, label]) => (
            <button
              key={value}
              type="button"
              className={range === value ? "active" : ""}
              aria-pressed={range === value}
              onClick={() => onRangeChange(value)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <div className="chart-legend chart-legend-values">
        {available.map(([key, label, color]) => (
          <span key={key}>
            <span className="dot" style={{ background: color }} />
            <span>{label}</span>
            <strong>{formatMetric(latestPoint?.[key])}</strong>
          </span>
        ))}
      </div>
      {hasTrend ? (
        <>
          <svg className="chart-svg own-content-trend" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="作品互动累计值趋势">
            {[0, 0.25, 0.5, 0.75, 1].map((pct) => {
              const lineY = padding.top + pct * plotHeight;
              const value = maximum * (1 - pct);
              return (
                <g key={pct}>
                  <line x1={padding.left} y1={lineY} x2={width - padding.right} y2={lineY} className="chart-grid-line" />
                  {pct !== 0.25 && pct !== 0.75
                    ? <text x={padding.left - 10} y={lineY + 4} textAnchor="end" className="chart-axis-label">{formatMetric(value)}</text>
                    : null}
                </g>
              );
            })}
            {available.map(([key, , color]) => (
              <g key={key}>
                <polyline
                  points={points.map((item, index) => `${x(index)},${y(item[key])}`).join(" ")}
                  fill="none"
                  stroke={color}
                  strokeWidth="3"
                  vectorEffect="non-scaling-stroke"
                />
                <circle cx={x(points.length - 1)} cy={y(points.at(-1)?.[key])} r="4" fill={color} />
              </g>
            ))}
          </svg>
          <div className="trend-axis">
            <span>{formatDateTime(points[0]?.timestamp, "")}</span>
            <span>{formatDateTime(points.at(-1)?.timestamp, "")}</span>
          </div>
        </>
      ) : (
        <div className="trend-empty">
          <span className="trend-empty-visual" aria-hidden="true">↗</span>
          <strong>{points.length === 1 ? "已记录首个数据快照" : "趋势正在积累"}</strong>
          <p>至少需要两次小时采集后才能形成变化趋势。</p>
        </div>
      )}
      {hasTrend ? (
        <p className="chart-footnote">每个点是平台累计值；相邻点的差值代表对应小时的新增或回落。</p>
      ) : null}
    </div>
  );
}

function InteractionOverview({ metrics, days }) {
  const byKey = Object.fromEntries((metrics || []).map((metric) => [metric.key, metric]));
  const interactionMetrics = TREND_METRICS.map(([key, label]) => ({
    key,
    label,
    value: byKey[key]?.value,
    change: byKey[key]?.change,
    note: byKey[key]?.note,
    icon: METRIC_META[key]?.icon,
  }));
  const availableChanges = interactionMetrics
    .map((metric) => metric.change)
    .filter((value) => value !== null && value !== undefined && Number.isFinite(Number(value)));
  const totalChange = availableChanges.length
    ? availableChanges.reduce((total, value) => total + Number(value), 0)
    : null;
  const contents = byKey.contents;

  return (
    <section className="dashboard-overview" aria-labelledby="dashboard-overview-title">
      <div className="dashboard-overview-lead">
        <span className="section-kicker">互动概览</span>
        <h3 id="dashboard-overview-title">过去 24 小时</h3>
        <div className="dashboard-overview-value">{formatDelta(totalChange)}</div>
        <p>新增互动总量</p>
        <div className="dashboard-overview-context">
          <span><strong>{formatMetric(contents?.value)}</strong> 篇近期作品</span>
          <span>统计范围：近 {days} 天发布</span>
        </div>
      </div>
      <div className="dashboard-overview-metrics">
        {interactionMetrics.map((metric) => (
          <article className="dashboard-overview-metric" key={metric.key}>
            <div>
              <span className="metric-icon" aria-hidden="true">{metric.icon}</span>
              <span>{metric.label}</span>
            </div>
            <strong>{formatMetric(metric.value)}</strong>
            <small>
              <DeltaValue value={metric.change} />
              <span>24h</span>
            </small>
          </article>
        ))}
      </div>
    </section>
  );
}

function ContentNavigator({ contents, selectedContentId, onSelect }) {
  return (
    <aside className="dashboard-content-navigator" aria-label="近期作品">
      <div className="dashboard-content-navigator-heading">
        <div>
          <span className="section-kicker">近期作品</span>
          <h3>选择作品</h3>
        </div>
        <span>{contents.length} 篇</span>
      </div>
      <div className="dashboard-content-list">
        {contents.map((content) => {
          const selected = String(selectedContentId) === String(content.contentId);
          return (
            <button
              className={`dashboard-content-option${selected ? " selected" : ""}`}
              type="button"
              key={content.contentId}
              aria-pressed={selected}
              onClick={() => onSelect(content.contentId)}
            >
              <TopContentCover content={content} />
              <span className="dashboard-content-option-copy">
                <strong>{content.title}</strong>
                <span>
                  {content.contentType}
                  {content.publishedAt ? ` · ${formatPublishedAt(content.publishedAt)}` : ""}
                </span>
              </span>
              <span className="dashboard-content-option-delta">
                <small>24h</small>
                <DeltaValue value={content.delta24h} />
              </span>
            </button>
          );
        })}
      </div>
    </aside>
  );
}

export default function DataDashboard({ app }) {
  const initialPlatforms = app.dashboard?.availablePlatforms || [];
  const [platform, setPlatform] = useState(initialPlatforms[0] || "抖音");
  const [days, setDays] = useState(30);
  const [dashboard, setDashboard] = useState(app.dashboard);
  const [loading, setLoading] = useState(false);
  const [selectedContentId, setSelectedContentId] = useState(null);
  const [trendDays, setTrendDays] = useState(7);
  const [trend, setTrend] = useState(null);
  const [refreshJob, setRefreshJob] = useState(null);
  const structure = dashboard?.social?.contentStructure || [];
  const pieSegments = useMemo(() => buildPieSegments(structure), [structure]);
  const configuredPlatforms = ["抖音", "小红书"].filter(
    (item) => app.currentAccount?.platforms?.includes(item)
      && app.currentAccount?.platformAccounts?.[item],
  );
  const availablePlatforms = dashboard?.availablePlatforms?.length
    ? dashboard.availablePlatforms
    : configuredPlatforms.length
      ? configuredPlatforms
      : app.dashboard?.availablePlatforms || [];
  const effectivePlatform = availablePlatforms.includes(platform)
    ? platform
    : availablePlatforms[0] || "";

  useEffect(() => {
    const available = app.dashboard?.availablePlatforms || [];
    setPlatform((current) => available.includes(current) ? current : available[0] || "");
    setDashboard(app.dashboard);
    setSelectedContentId(null);
    setTrend(null);
    setRefreshJob(null);
  }, [app.currentAccountId, app.dashboard]);

  useEffect(() => {
    if (!app.currentAccountId || !effectivePlatform) return undefined;
    let active = true;
    setLoading(true);
    starxApi.getDashboard(app.currentAccountId, { platform: effectivePlatform, days })
      .then(async (value) => {
        if (!active) return;
        setDashboard(value);
        setSelectedContentId((current) => current || value.social?.topContents?.[0]?.contentId || null);
        if (
          value.social?.status === "unavailable"
          && value.social?.notices?.includes("尚未完成首次小时数据采集")
        ) {
          const job = await starxApi.startDashboardRefresh(
            app.currentAccountId,
            effectivePlatform,
          );
          if (active) setRefreshJob(job);
        }
      })
      .catch((error) => active && app.addToast(error?.message || "数据看板加载失败", "warning"))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [app.currentAccountId, effectivePlatform, days]);

  useEffect(() => {
    if (!app.currentAccountId || !selectedContentId) {
      setTrend(null);
      return undefined;
    }
    let active = true;
    starxApi.getDashboardContentTrend(app.currentAccountId, selectedContentId, trendDays)
      .then((value) => active && setTrend(value))
      .catch((error) => active && app.addToast(error?.message || "作品趋势加载失败", "warning"));
    return () => { active = false; };
  }, [app.currentAccountId, selectedContentId, trendDays]);

  useEffect(() => {
    const refreshId = refreshJob?.refreshId;
    if (
      !app.currentAccountId
      || !refreshId
      || !["pending", "running"].includes(refreshJob.status)
    ) return undefined;
    let active = true;
    let timer;
    const poll = async () => {
      try {
        const job = await starxApi.getDashboardRefresh(
          app.currentAccountId,
          refreshId,
        );
        if (!active) return;
        setRefreshJob(job);
        if (job.status === "succeeded") {
          const value = await starxApi.getDashboard(app.currentAccountId, {
            platform: effectivePlatform,
            days,
          });
          if (!active) return;
          setDashboard(value);
          setSelectedContentId((current) => current || value.social?.topContents?.[0]?.contentId || null);
          app.addToast(job.message || "作品互动数据已刷新", "success");
          return;
        }
        if (job.status === "failed") {
          app.addToast(job.message || "数据看板刷新失败", "warning");
          return;
        }
        timer = window.setTimeout(poll, 1500);
      } catch (error) {
        if (!active) return;
        setRefreshJob(null);
        app.addToast(error?.message || "刷新状态查询失败", "warning");
      }
    };
    timer = window.setTimeout(poll, 500);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [app.currentAccountId, refreshJob?.refreshId, effectivePlatform, days]);

  const refreshDashboard = async () => {
    if (
      !app.currentAccountId
      || !effectivePlatform
      || loading
      || ["pending", "running"].includes(refreshJob?.status)
    ) return;
    try {
      const job = await starxApi.startDashboardRefresh(
        app.currentAccountId,
        effectivePlatform,
      );
      setRefreshJob(job);
      app.addToast("刷新任务已提交，可继续使用其他功能", "success");
    } catch (error) {
      app.addToast(error?.message || "数据看板刷新失败", "warning");
    }
  };

  if (!dashboard) return <DashboardLoadingPage />;
  const social = dashboard.social || { status: "unconfigured", notices: [] };
  const updatedAt = formatDateTime(social.updatedAt);
  const nextRefreshAt = formatDateTime(social.nextRefreshAt, "等待调度");
  const providerLabel = social.provider ? `数据源 ${social.provider}` : "";
  const structureTotal = structure.reduce((total, item) => total + Number(item.count || 0), 0);
  const refreshing = ["pending", "running"].includes(refreshJob?.status);
  const refreshLabel = refreshJob?.status === "pending"
    ? "等待刷新…"
    : refreshJob?.status === "running" ? "采集中…" : "主动刷新";

  return (
    <div className="dashboard-page">
      <header className="dashboard-hero">
        <div className="dashboard-title-group">
          <span className="dashboard-eyebrow">账号数据看板</span>
          <h2>{app.currentAccount?.name || "未知账号"}</h2>
          <div className="dashboard-meta">
            {social.platform ? <span className="dashboard-platform-badge">{social.platform}</span> : null}
            {social.platformAccount ? <span>{social.platformAccount}</span> : null}
            {providerLabel ? <span>{providerLabel}</span> : null}
            <span className="dashboard-auto-sync"><i aria-hidden="true" />每小时自动更新</span>
          </div>
        </div>
        <div className="dashboard-sync-summary" aria-label="数据同步状态">
          <span>最近同步 <strong>{updatedAt}</strong></span>
          <span>下次预计 <strong>{nextRefreshAt}</strong></span>
        </div>
      </header>

      <section className="dashboard-toolbar" aria-label="看板筛选与操作">
        <div className="dashboard-filter-group">
          <label>
            <span>账号</span>
            <select value={app.currentAccountId || ""} onChange={(event) => event.target.value && app.switchAccount(event.target.value)}>
              {app.accounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
            </select>
          </label>
          <label>
            <span>平台</span>
            <select value={effectivePlatform} onChange={(event) => {
              setRefreshJob(null);
              setPlatform(event.target.value);
            }}>
              {availablePlatforms.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
          <label>
            <span>作品范围</span>
            <select className="date-picker" value={days} onChange={(event) => setDays(Number(event.target.value))}>
              <option value={7}>近7天作品</option>
              <option value={30}>近30天作品</option>
              <option value={90}>近90天作品</option>
            </select>
          </label>
        </div>
        <div className="dashboard-toolbar-actions">
          {refreshing ? (
            <div className="dashboard-refresh-status" role="status" aria-live="polite">
              <span>{refreshJob.message || "正在刷新数据"}</span>
              <div aria-hidden="true"><i style={{ width: `${Math.max(refreshJob.progress || 0, 8)}%` }} /></div>
            </div>
          ) : null}
          <button className="btn dashboard-refresh-button" type="button" disabled={loading || refreshing || !effectivePlatform} onClick={refreshDashboard}>
            <span aria-hidden="true">↻</span>{refreshLabel}
          </button>
          <button className="btn dashboard-export-button" type="button" onClick={() => window.print()}>导出报告</button>
        </div>
      </section>

      {social.status !== "ready" ? <DashboardEmpty app={app} social={social} /> : (
        <>
          {(social.notices || []).map((notice) => <p className="report-notice warning" key={notice}>{notice}</p>)}
          <InteractionOverview metrics={social.metrics || []} days={days} />

          <section className="dashboard-tracking-section" aria-labelledby="dashboard-tracking-title">
            <div className="dashboard-section-heading dashboard-tracking-heading">
              <div>
                <span className="section-kicker">增长追踪</span>
                <h3 id="dashboard-tracking-title">每篇作品，发生了什么变化</h3>
                <p>从左侧选择作品，右侧查看点赞、评论、收藏和分享的小时轨迹。</p>
              </div>
              <span className="dashboard-live-badge"><i aria-hidden="true" />小时快照持续记录</span>
            </div>
            <div className="dashboard-tracking-workspace">
              <ContentNavigator
                contents={social.topContents || []}
                selectedContentId={selectedContentId}
                onSelect={setSelectedContentId}
              />
            <ContentTrend
              trend={trend}
              range={trendDays}
              onRangeChange={setTrendDays}
            />
            </div>
          </section>

          <section className="dashboard-context-grid" aria-label="内容结构与增长洞察">
            <div className="chart-card dashboard-structure-card">
                <div className="chart-card-header">
                  <div>
                    <span className="section-kicker">内容分布</span>
                    <h3>内容形式结构</h3>
                  </div>
                </div>
                {pieSegments.length ? (
                  <div className="pie-chart-container">
                    <svg className="pie-chart" viewBox="0 0 160 160">
                      {pieSegments.map((item) => <path key={item.label} d={item.path} fill={item.color} opacity="0.85" />)}
                      <circle cx="80" cy="80" r="39" className="pie-chart-center" />
                      <text x="80" y="77" textAnchor="middle" className="pie-chart-total">{structureTotal}</text>
                      <text x="80" y="96" textAnchor="middle" className="pie-chart-caption">篇作品</text>
                    </svg>
                    <div className="pie-legend">
                      {pieSegments.map((item) => (
                        <div className="pie-legend-item" key={item.label}>
                          <span className="dot" style={{ background: item.color }} />
                          <span>{item.label}</span>
                          <strong>{item.percentage}%</strong>
                          <small>{item.count} 篇</small>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : <p className="muted">暂无可分类的公开内容。</p>}
            </div>
            <div className="insights-card">
              <div className="dashboard-section-heading">
                <div>
                  <span className="section-kicker">自动解读</span>
                  <h3>增长洞察</h3>
                  <p>基于当前作品快照，优先提示值得关注的变化。</p>
                </div>
              </div>
              <div className="dashboard-insight-list">
                {(social.insights || []).length
                  ? (social.insights || []).map((item, index) => (
                    <div className="insight-item" key={item.title}>
                      <div className="insight-index">{String(index + 1).padStart(2, "0")}</div>
                      <div className="insight-content"><h4>{item.title}</h4><p>{item.description}</p></div>
                    </div>
                  ))
                  : <div className="insights-empty"><span aria-hidden="true">✦</span><p>完成更多小时快照后，这里会自动提炼增长最快的作品。</p></div>}
              </div>
            </div>
          </section>

          <div className="dashboard-bottom dashboard-table-section">
            <div className="top-content-card">
              <div className="dashboard-section-heading">
                <div>
                  <span className="section-kicker">作品明细</span>
                  <h3>近期作品互动变化</h3>
                  <p>选择一条作品，即可在上方查看它的小时变化趋势。</p>
                </div>
                <span className="dashboard-item-count">{social.topContents?.length || 0} 篇</span>
              </div>
              <div className="top-content-table-wrap">
                <table className="top-content-table">
                  <colgroup>
                    <col className="top-content-title-column" />
                    <col className="top-content-value-column" />
                    <col className="top-content-value-column" />
                    <col className="top-content-value-column" />
                    <col className="top-content-value-column" />
                    <col className="top-content-value-column" />
                    <col className="top-content-value-column" />
                  </colgroup>
                  <thead><tr><th>作品</th><th>点赞</th><th>评论</th><th>收藏</th><th>分享</th><th>1h变化</th><th>24h变化</th></tr></thead>
                  <tbody>
                    {(social.topContents || []).map((content) => (
                      <tr
                        key={content.contentId}
                        className={String(selectedContentId) === String(content.contentId) ? "selected" : ""}
                        aria-selected={String(selectedContentId) === String(content.contentId)}
                        tabIndex={0}
                        onClick={() => setSelectedContentId(content.contentId)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            setSelectedContentId(content.contentId);
                          }
                        }}
                      >
                        <td>
                          <div className="top-content-main">
                            <TopContentCover content={content} />
                            <div className="top-content-copy">
                              <strong title={content.title}>{content.title}</strong>
                              <span className="top-content-meta">
                                <span className="content-type-tag">{content.contentType}</span>
                                {content.publishedAt ? <span>{formatPublishedAt(content.publishedAt)} 发布</span> : null}
                                {String(selectedContentId) === String(content.contentId)
                                  ? <span className="selected-content-indicator">趋势查看中</span>
                                  : null}
                              </span>
                            </div>
                          </div>
                        </td>
                        <td>{formatMetric(content.likes)}</td>
                        <td>{formatMetric(content.comments)}</td>
                        <td>{formatMetric(content.favorites)}</td>
                        <td>{formatMetric(content.shares)}</td>
                        <td><DeltaValue value={content.delta1h} /></td>
                        <td><DeltaValue value={content.delta24h} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
