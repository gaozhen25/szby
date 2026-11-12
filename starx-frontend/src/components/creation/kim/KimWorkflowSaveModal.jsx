import { useEffect, useRef } from "react";
import ModalOverlay from "../../ModalOverlay";

export default function KimWorkflowSaveModal({
  open,
  type,
  handoff,
  priorityLabels,
  workflowStages,
  assetPersistenceState,
  assetPersistenceText,
  readyForCompletion,
  saving,
  onChange,
  onCancel,
  onConfirm,
}) {
  const cancelButtonRef = useRef(null);
  const lastFocusedElement = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    lastFocusedElement.current = document.activeElement;
    cancelButtonRef.current?.focus();
    const closeOnEscape = (event) => {
      if (event.key === "Escape" && !saving) onCancel();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      window.removeEventListener("keydown", closeOnEscape);
      lastFocusedElement.current?.focus?.();
    };
  }, [onCancel, open, saving]);

  if (!open) return null;
  const isImageCompletion = readyForCompletion && type === "image";
  const modalTitle = isImageCompletion ? "完成创作，进入审核" : readyForCompletion ? "完成脚本，进入流程" : "保存到流程管理";
  const confirmLabel = isImageCompletion ? "完成并进入审核" : readyForCompletion ? "完成并进入流程" : "确认保存";

  return <ModalOverlay>
    <div
      className="modal modal-wide workflow-save-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="workflow-save-title"
    >
      <h3 id="workflow-save-title">{modalTitle}</h3>
      <p className="muted">{readyForCompletion
        ? `确认交接信息后，内容将进入「${type === "video" ? "脚本" : "审核"}」阶段，之后仍可返回继续修改。`
        : `填写交接信息后，将进入「${type === "video" ? "脚本" : "审核"}」阶段`}</p>
      {assetPersistenceState ? <div className={`publish-config-status ${assetPersistenceState.status || "pending"}`}>
        <span>{assetPersistenceText[assetPersistenceState.status] || assetPersistenceState.status}</span>
        {assetPersistenceState.error ? <small>{assetPersistenceState.error}</small> : null}
      </div> : null}
      <div className="handoff-grid">
        <label><span>负责人</span><input value={handoff.assignee} onChange={(event) => onChange("assignee", event.target.value)} placeholder="如：剪辑A" /></label>
        <label><span>截止日期</span><input type="date" value={handoff.dueDate} onChange={(event) => onChange("dueDate", event.target.value)} /></label>
        <label><span>优先级</span><select value={handoff.priority} onChange={(event) => onChange("priority", event.target.value)}>{Object.entries(priorityLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
        <label><span>初始阶段</span><select value={handoff.status} onChange={(event) => onChange("status", event.target.value)}>{workflowStages.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
      </div>
      <label className="handoff-note"><span>交接备注</span><textarea value={handoff.handoffNote} onChange={(event) => onChange("handoffNote", event.target.value)} rows={3} placeholder="补充拍摄或审核要求..." /></label>
      <div className="modal-actions">
        <button ref={cancelButtonRef} className="btn" type="button" disabled={saving} onClick={onCancel}>取消</button>
        <button className="btn btn-primary" type="button" disabled={saving} onClick={onConfirm}>{saving ? "保存中..." : confirmLabel}</button>
      </div>
    </div>
  </ModalOverlay>;
}
