import { useRef, useState } from "react";

import CompetitorCoverImage from "./CompetitorCoverImage.jsx";
import CompetitorMetric from "./CompetitorMetric.jsx";

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

export default function CompetitorVideoCard({ item, onRefresh, onDelete }) {
  const [actionBusy, setActionBusy] = useState("");
  const actionInFlightRef = useRef(false);
  const statusRefreshing = item.refreshStatus === "pending" || item.refreshStatus === "running";
  const refreshing = statusRefreshing || actionBusy === "refresh";

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
    if (!window.confirm(`确认删除监控视频“${item.title || item.contentUrl}”吗？`)) return;
    await runAction("delete", () => onDelete(item.id));
  };

  return (
    <article className="glass-card monitor-card monitor-video-card">
      <div className="monitor-card-top">
        <div className="monitor-thumb monitor-video-thumb">
          <CompetitorCoverImage url={item.coverUrl} />
        </div>
        <div className="monitor-card-heading">
          <h3 title={item.title || "等待获取视频信息"}>{item.title || "等待获取视频信息"}</h3>
          <p>
            <span className="monitor-platform">{item.platform || "平台待识别"}</span>
            <span className={`monitor-status ${item.refreshStatus || "unknown"}`}>
              {STATUS_LABELS[item.refreshStatus] || item.refreshStatus || "等待刷新"}
            </span>
          </p>
        </div>
      </div>

      <p className="monitor-desc">
        {item.authorName ? `作者：${item.authorName}` : (item.description || "首次刷新完成后将展示视频信息。")}
      </p>

      <div className="monitor-metrics" aria-label="视频公开指标">
        <CompetitorMetric label="播放" value={item.plays} delta={item.deltaMetrics?.plays} />
        <CompetitorMetric label="点赞" value={item.likes} delta={item.deltaMetrics?.likes} />
        <CompetitorMetric label="评论" value={item.comments} delta={item.deltaMetrics?.comments} />
        <CompetitorMetric label="分享" value={item.shares} delta={item.deltaMetrics?.shares} />
        <CompetitorMetric label="收藏" value={item.collects} delta={item.deltaMetrics?.collects} />
      </div>

      {item.refreshErrorMessage ? <p className="monitor-error" role="alert">{item.refreshErrorMessage}</p> : null}
      <span className="monitor-updated">最近更新：{formatTime(item.lastRefreshedAt)}</span>

      <div className="monitor-card-actions">
        <a className="btn btn-sm btn-primary" href={item.contentUrl} target="_blank" rel="noreferrer">查看视频</a>
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
