import { useCallback, useRef, useState } from "react";

import CompetitorAccountCard from "../components/competitors/CompetitorAccountCard.jsx";
import CompetitorAddModal from "../components/competitors/CompetitorAddModal.jsx";
import { useCompetitorMonitoring } from "../hooks/useCompetitorMonitoring.js";
import "../styles/competitor-monitor.css";

export default function CompetitorMonitor({ app }) {
  const [showAddModal, setShowAddModal] = useState(false);
  const [refreshAllBusy, setRefreshAllBusy] = useState(false);
  const refreshAllInFlightRef = useRef(false);
  const accountId = app.currentAccount?.id || "";
  const monitoring = useCompetitorMonitoring({ accountId, addToast: app.addToast });
  const items = monitoring.accounts;
  const refreshSummary = items.reduce((summary, item) => {
    if (item.refreshStatus === "succeeded") summary.succeeded += 1;
    else if (item.refreshStatus === "failed") summary.failed += 1;
    else if (item.refreshStatus === "pending" || item.refreshStatus === "running") summary.refreshing += 1;
    return summary;
  }, { succeeded: 0, refreshing: 0, failed: 0 });
  const allRefreshing = items.length > 0 && items.every(
    (item) => item.refreshStatus === "pending" || item.refreshStatus === "running"
  );

  const closeAddModal = useCallback(() => setShowAddModal(false), []);
  const openAddModal = () => setShowAddModal(true);
  const addTarget = useCallback(
    (reference) => monitoring.addAccount(reference),
    [monitoring.addAccount]
  );
  const refreshAll = async () => {
    if (refreshAllInFlightRef.current) return;
    refreshAllInFlightRef.current = true;
    setRefreshAllBusy(true);
    try {
      await monitoring.refreshAccounts();
    } catch (_error) {
      // 数据层保留旧数据并展示错误；这里仅负责释放提交锁。
    } finally {
      refreshAllInFlightRef.current = false;
      setRefreshAllBusy(false);
    }
  };

  return (
    <div className="competitor-page">
      <header className="section-header competitor-monitor-header">
        <div className="competitor-monitor-heading">
          <h2>竞品监控 · <span className="hl">{app.currentAccount?.name || "未选择账号"}</span></h2>
          <p className="muted">后台定时采集公开账号数据，也可以随时主动刷新。</p>
        </div>
        <div className="competitor-monitor-actions">
          <button type="button" className="btn" disabled={!accountId || monitoring.loading || items.length === 0 || allRefreshing || refreshAllBusy} onClick={refreshAll}>
            {refreshAllBusy ? "刷新提交中…" : "↻ 刷新全部"}
          </button>
          <button type="button" className="btn btn-primary" disabled={!accountId} onClick={openAddModal}>＋ 添加监控</button>
        </div>
      </header>

      <div className="competitor-refresh-summary glass-card" aria-label="刷新状态概览">
        <span>监控账号</span>
        <div className="competitor-summary" aria-label="刷新状态概览">
          <span>已更新 <strong>{refreshSummary.succeeded}</strong></span>
          <span>刷新中 <strong>{refreshSummary.refreshing}</strong></span>
          <span>失败 <strong>{refreshSummary.failed}</strong></span>
        </div>
      </div>

      {monitoring.error ? (
        <div className="competitor-notice" role="alert">{monitoring.error}<button className="btn btn-xs" onClick={() => monitoring.reload()}>重试</button></div>
      ) : null}

      {monitoring.loading && items.length === 0 ? <div className="competitor-empty">正在加载监控数据…</div> : null}
      {!monitoring.loading && accountId && items.length === 0 ? (
        <div className="competitor-empty glass-card">
          <span>👤</span>
          <h3>还没有监控账号</h3>
          <p>添加公开账号主页后，系统会立即抓取一次，并按计划定时更新。</p>
          <button className="btn btn-primary" onClick={openAddModal}>添加第一个监控目标</button>
        </div>
      ) : null}
      {!accountId ? <div className="competitor-empty glass-card">请先选择一个运营账号。</div> : null}

      <div className="monitor-grid">
        {monitoring.accounts.map((item) => (
          <CompetitorAccountCard
            key={item.id}
            item={item}
            onRefresh={monitoring.refreshAccount}
            onDelete={monitoring.deleteAccount}
          />
        ))}
      </div>

      <CompetitorAddModal open={showAddModal} onClose={closeAddModal} onSubmit={addTarget} />
    </div>
  );
}
