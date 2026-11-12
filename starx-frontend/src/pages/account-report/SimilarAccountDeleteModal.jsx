import { useEffect, useRef } from "react";
import ModalOverlay from "../../components/ModalOverlay";

export default function SimilarAccountDeleteModal({ account, deleting, onCancel, onConfirm }) {
  const cancelButtonRef = useRef(null);

  useEffect(() => {
    if (!account) return undefined;
    cancelButtonRef.current?.focus();
    const handleKeyDown = (event) => {
      if (event.key === "Escape" && !deleting) onCancel();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [account, deleting, onCancel]);

  if (!account) return null;

  return (
    <ModalOverlay>
      <section className="modal report-similar-delete-modal" role="alertdialog" aria-modal="true" aria-labelledby="report-similar-delete-title" aria-describedby="report-similar-delete-description">
        <h3 id="report-similar-delete-title">确认删除相似账号</h3>
        <p id="report-similar-delete-description">
          确认从账号报告中删除“{account.name || "未命名账号"}”？删除后可重新手动添加。
        </p>
        <div className="modal-actions">
          <button ref={cancelButtonRef} type="button" className="btn" disabled={deleting} onClick={onCancel}>取消</button>
          <button type="button" className="btn btn-danger" disabled={deleting} onClick={onConfirm}>{deleting ? "正在删除…" : "确认删除"}</button>
        </div>
      </section>
    </ModalOverlay>
  );
}
