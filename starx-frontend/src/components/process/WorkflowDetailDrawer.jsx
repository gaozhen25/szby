import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

import "../../styles/workflow-detail.css";

const formatDate = (value) => {
  if (!value) return "未设置";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
};

const getMaterialCount = (task) => {
  if (Number.isFinite(Number(task.materialCount))) return Number(task.materialCount);
  if (Number.isFinite(Number(task.assetsCount))) return Number(task.assetsCount);
  if (Array.isArray(task.materials)) return task.materials.length;
  if (Array.isArray(task.assets)) return task.assets.length;
  return 0;
};

const normalizeStageKey = (status) => ({
  pending: "pending_review",
  pending_publish: "pending_review",
  completed: "done",
}[status] || status);

export default function WorkflowDetailDrawer({ task, stages, canPublish, transitioning, duplicating = false, suspended = false, onClose, onAdvance, onRetreat, onMove, onDelete, onDuplicate, onOpen, onPublish }) {
  const dialogRef = useRef(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!task || suspended) return undefined;

    const previouslyFocused = document.activeElement;
    const focusTimer = window.setTimeout(() => dialogRef.current?.focus(), 0);
    const handleKeyDown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current?.();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;

      const focusable = Array.from(dialogRef.current.querySelectorAll(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
      ));
      if (!focusable.length) {
        event.preventDefault();
        dialogRef.current.focus();
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!dialogRef.current.contains(document.activeElement) || document.activeElement === dialogRef.current) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener("keydown", handleKeyDown);
      if (previouslyFocused instanceof HTMLElement && document.contains(previouslyFocused)) {
        previouslyFocused.focus();
      }
    };
  }, [task?.id, suspended]);

  if (!task) return null;

  const safeStages = Array.isArray(stages) ? stages : [];
  const currentStatus = normalizeStageKey(task.status);
  const currentIndex = safeStages.findIndex((stage) => stage.key === currentStatus);
  const currentStage = safeStages[currentIndex] || { key: currentStatus, label: currentStatus || "未知阶段", color: "#7b879f" };
  const previousStage = currentIndex > 0 ? safeStages[currentIndex - 1] : null;
  const nextStage = currentIndex >= 0 ? safeStages[currentIndex + 1] : null;
  const history = Array.isArray(task.statusHistory) && task.statusHistory.length
    ? task.statusHistory
    : [{ status: task.status, enteredAt: task.updated || "" }];
  const dueAt = task.dueDate || task.publishAt || task.scheduledAt || "";
  const metaItems = [
    { label: "内容类型", value: task.type === "video" ? "视频" : "图文" },
    { label: "发布平台", value: task.targetPlatform || "未设置" },
    { label: "负责人", value: task.assignee || "未分配" },
    { label: "截止时间", value: formatDate(dueAt) },
    { label: "素材数量", value: String(getMaterialCount(task)) },
  ];

  return createPortal(
    <div
      className="workflow-detail-layer"
      data-suspended={suspended || undefined}
    >
      <div
        className="workflow-drawer-backdrop"
        aria-hidden="true"
      />
      <aside
        ref={dialogRef}
        className="workflow-drawer workflow-detail-modal"
        role="dialog"
        aria-modal={suspended ? undefined : "true"}
        aria-hidden={suspended || undefined}
        aria-labelledby="workflow-drawer-title"
        aria-busy={transitioning || undefined}
        tabIndex={-1}
      >
        <header className="workflow-drawer-head">
          <div>
            <p className="workflow-detail-kicker">任务详情</p>
            <h3 id="workflow-drawer-title" title={task.title || "未命名任务"}>{task.title || "未命名任务"}</h3>
            <span className="workflow-current-label" style={{ "--stage-color": currentStage.color }}>
              当前阶段：{currentStage.label}
            </span>
            {transitioning ? <small className="workflow-transitioning" role="status">阶段更新中…</small> : null}
          </div>
          <button type="button" className="btn btn-xs" aria-label="关闭" onClick={() => onClose?.()}>×</button>
        </header>

        <div className="workflow-detail-body">
          <div className="workflow-detail-main">
            <section className="workflow-drawer-section">
              <h4>任务信息</h4>
              <dl className="workflow-detail-list workflow-detail-meta">
                {metaItems.map((item) => (
                  <div key={item.label}>
                    <dt>{item.label}</dt>
                    <dd>{item.value}</dd>
                  </div>
                ))}
              </dl>
            </section>

            <section className="workflow-drawer-section">
              <div className="workflow-drawer-section-title">
                <h4>阶段进度</h4>
                {safeStages.length ? (
                  <select
                    value={currentStatus}
                    aria-label="直达阶段"
                    disabled={transitioning}
                    onChange={(event) => onMove?.(task, event.target.value)}
                  >
                    {safeStages.map((stage) => <option value={stage.key} key={stage.key}>{stage.label}</option>)}
                  </select>
                ) : null}
              </div>
              <div className="workflow-progress-track">
                {safeStages.map((stage, index) => (
                  <div
                    className={`workflow-progress-node ${index < currentIndex ? "done" : ""} ${index === currentIndex ? "active" : ""}`}
                    style={{ "--stage-color": stage.color }}
                    key={stage.key}
                  >
                    <span>{index < currentIndex ? "✓" : index + 1}</span>
                    <small>{stage.label}</small>
                  </div>
                ))}
              </div>
            </section>

            <section className="workflow-drawer-section workflow-detail-note-section">
              <h4>阶段备注</h4>
              <p className="workflow-note">{task.handoffNote || task.body || "暂无交接备注"}</p>
            </section>
          </div>

          <aside className="workflow-detail-side">
            <section className="workflow-drawer-section">
              <h4>流转记录</h4>
              <div className="workflow-history">
                {history.map((item, index) => {
                  const stage = safeStages.find((candidate) => candidate.key === normalizeStageKey(item.status));
                  return (
                    <div className="workflow-history-item" key={`${item.status || "unknown"}-${item.enteredAt || item.updated || index}`}>
                      <i className={index === history.length - 1 ? "active" : ""} />
                      <div>
                        <strong>{stage?.label || item.status || "未知阶段"}</strong>
                        <small>{formatDate(item.enteredAt || item.updatedAt || item.updated)}</small>
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>

            <footer className="workflow-drawer-actions">
              {canPublish ? (
                <button type="button" className="btn btn-primary full-btn workflow-publish-btn" disabled={transitioning} onClick={() => onPublish?.(task)}>
                  发布作品
                </button>
              ) : null}
              {previousStage || nextStage ? (
                <div className="workflow-stage-actions">
                  {previousStage ? (
                    <button type="button" className="btn" disabled={transitioning} onClick={() => onRetreat?.(task)}>
                      ← 退回{previousStage.label}
                    </button>
                  ) : null}
                  {nextStage ? (
                    <button type="button" className="btn btn-primary" disabled={transitioning} onClick={() => onAdvance?.(task)}>
                      推进到{nextStage.label} →
                    </button>
                  ) : null}
                </div>
              ) : null}
              <button type="button" className="btn full-btn" disabled={transitioning || duplicating} onClick={() => onDuplicate?.(task)}>
                {duplicating ? "正在复制流程…" : "⧉ 快速复制流程"}
              </button>
              <button type="button" className="btn full-btn" onClick={() => onOpen?.(task)}>打开任务 ↗</button>
              <button type="button" className="btn btn-danger full-btn" disabled={transitioning} onClick={() => onDelete?.(task)}>删除任务</button>
            </footer>
          </aside>
        </div>
      </aside>
    </div>,
    document.body,
  );
}
