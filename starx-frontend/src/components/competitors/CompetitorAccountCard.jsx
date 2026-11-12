import { useEffect, useRef, useState } from "react";

import CompetitorMetric from "./CompetitorMetric.jsx";
import CompetitorAccountHistory from "./CompetitorAccountHistory.jsx";
import CompetitorRecentWorksModal from "./CompetitorRecentWorksModal.jsx";
import { browserCompatibleImageUrl } from "../../utils/publicImageUrl.js";

const STATUS_LABELS = {
  pending: "等待刷新",
  running: "刷新中",
  succeeded: "已更新",
  failed: "刷新失败",
};

function formatTime(value) {
  if (!value) return "尚未完成首次刷新";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "更新时间未知";
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "short" }).format(date);
}

export default function CompetitorAccountCard({ item, onRefresh, onDelete }) {
  const [actionBusy, setActionBusy] = useState("");
  const [showRecentWorks, setShowRecentWorks] = useState(false);
  const [avatarFailed, setAvatarFailed] = useState(false);
  const actionInFlightRef = useRef(false);
  const statusRefreshing = item.refreshStatus === "pending" || item.refreshStatus === "running";
  const refreshing = statusRefreshing || actionBusy === "refresh";
  const statusLabel = item.refreshStatus === "running" && item.name
    ? "作品刷新中"
    : (STATUS_LABELS[item.refreshStatus] || item.refreshStatus || "等待刷新");
  const avatarUrl = browserCompatibleImageUrl(item.avatarUrl);
  const recentWorks = Array.isArray(item.newVideos) ? item.newVideos : [];

  useEffect(() => setAvatarFailed(false), [avatarUrl]);

  const runAction = async (kind, action) => {
    if (actionInFlightRef.current) return;
    actionInFlightRef.current = true;
    setActionBusy(kind);
    try {
      await action();
    } catch (_error) {
      // 错误由监控数据层统一展示，卡片只负责释放本地操作锁。
    } finally {
      actionInFlightRef.current = false;
      setActionBusy("");
    }
  };

  const remove = async () => {
    if (!window.confirm(`确认删除监控账号“${item.name || item.profileUrl}”吗？`)) return;
    await runAction("delete", () => onDelete(item.id));
  };

  return (
    <article className="glass-card monitor-card monitor-account-card">
      <div className="monitor-card-top">
        <div className="monitor-thumb monitor-account-thumb">
          {avatarUrl && !avatarFailed
            ? <img src={avatarUrl} alt="" onError={() => setAvatarFailed(true)} />
            : (item.name || "账").slice(0, 1)}
        </div>
        <div className="monitor-card-heading">
          <h3 title={item.name || "等待获取账号信息"}>{item.name || "等待获取账号信息"}</h3>
          <p>
            <span className="monitor-platform">{item.platform || "平台待识别"}</span>
            <span className={`monitor-status ${item.refreshStatus || "unknown"}`}>
              {statusLabel}
            </span>
          </p>
        </div>
      </div>

      <p className="monitor-desc">{item.bio || "首次刷新完成后将展示账号简介。"}</p>

      <div className="monitor-metrics" aria-label="账号公开指标">
        <CompetitorMetric label="粉丝" value={item.followers} delta={item.deltaMetrics?.followers} />
        <CompetitorMetric label="关注" value={item.following} delta={item.deltaMetrics?.following} />
        <CompetitorMetric label="作品" value={item.works} delta={item.deltaMetrics?.works} />
        <CompetitorMetric label="获赞" value={item.liked} delta={item.deltaMetrics?.liked} />
      </div>

      <CompetitorAccountHistory history={item.metricHistory} />

      {recentWorks.length ? <button
        type="button"
        className="monitor-recent-trigger"
        onClick={() => setShowRecentWorks(true)}
      >
        <span><strong>发现近期作品</strong><small>近7天共 {recentWorks.length} 条</small></span>
        <b>查看作品 →</b>
      </button> : null}

      <CompetitorRecentWorksModal
        open={showRecentWorks && recentWorks.length > 0}
        accountName={item.name}
        works={recentWorks}
        onClose={() => setShowRecentWorks(false)}
      />

      {item.refreshErrorMessage ? <p className="monitor-error" role="alert">{item.refreshErrorMessage}</p> : null}
      <span className="monitor-updated">最近更新：{formatTime(item.lastRefreshedAt)}</span>

      <div className="monitor-card-actions">
        <a className="btn btn-sm btn-primary" href={item.profileUrl} target="_blank" rel="noreferrer">查看主页</a>
        <button
          type="button"
          className="btn btn-sm"
          disabled={refreshing || Boolean(actionBusy)}
          onClick={() => runAction("refresh", () => onRefresh(item.id))}
        >
          {refreshing ? "刷新中…" : "刷新数据"}
        </button>
        <button type="button" className="btn btn-sm btn-danger" disabled={Boolean(actionBusy)} onClick={remove}>
          {actionBusy === "delete" ? "删除中…" : "删除"}
        </button>
      </div>
    </article>
  );
}
