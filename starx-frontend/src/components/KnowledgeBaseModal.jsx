import { useEffect, useRef, useState } from "react";

import KnowledgeBaseEditor from "./knowledge-base/KnowledgeBaseEditor";
import KnowledgeBaseManager from "./knowledge-base/KnowledgeBaseManager";
import "../styles/knowledge-base.css";
import ModalOverlay from "./ModalOverlay";

const focusableSelector = [
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "a[href]",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

export default function KnowledgeBaseModal({ app }) {
  const [mode, setMode] = useState("manager");
  const [isBusy, setIsBusy] = useState(false);
  const dialogRef = useRef(null);
  const busyRef = useRef(false);
  const closeRef = useRef(app.closeKnowledgeBaseModal);

  closeRef.current = app.closeKnowledgeBaseModal;
  busyRef.current = isBusy;

  useEffect(() => {
    if (!app.showKnowledgeBaseModal) return;
    setMode(app.editingKnowledgeBase?.id ? "editor" : "manager");
  }, [app.editingKnowledgeBase?.id, app.showKnowledgeBaseModal]);

  useEffect(() => {
    if (!app.showKnowledgeBaseModal) return undefined;

    const previouslyFocused = document.activeElement;
    const focusInitialControl = () => {
      const preferred = dialogRef.current?.querySelector("[data-autofocus]");
      const firstFocusable = dialogRef.current?.querySelector(focusableSelector);
      (preferred || firstFocusable || dialogRef.current)?.focus();
    };
    const animationFrame = window.requestAnimationFrame(focusInitialControl);

    const handleKeyDown = (event) => {
      if (event.key === "Escape") {
        if (!busyRef.current) {
          event.preventDefault();
          closeRef.current?.();
        }
        return;
      }
      if (event.key !== "Tab") return;

      const focusableElements = dialogRef.current?.querySelectorAll(focusableSelector) || [];
      if (focusableElements.length === 0) {
        event.preventDefault();
        dialogRef.current?.focus();
        return;
      }

      const firstElement = focusableElements[0];
      const lastElement = focusableElements[focusableElements.length - 1];
      if (!dialogRef.current?.contains(document.activeElement)) {
        event.preventDefault();
        (event.shiftKey ? lastElement : firstElement).focus();
      } else if (event.shiftKey && document.activeElement === firstElement) {
        event.preventDefault();
        lastElement.focus();
      } else if (!event.shiftKey && document.activeElement === lastElement) {
        event.preventDefault();
        firstElement.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      window.cancelAnimationFrame(animationFrame);
      document.removeEventListener("keydown", handleKeyDown);
      if (previouslyFocused && typeof previouslyFocused.focus === "function") {
        previouslyFocused.focus();
      }
    };
  }, [app.showKnowledgeBaseModal]);

  useEffect(() => {
    if (!app.showKnowledgeBaseModal) return undefined;
    const animationFrame = window.requestAnimationFrame(() => {
      const preferred = dialogRef.current?.querySelector("[data-autofocus]");
      (preferred || dialogRef.current)?.focus();
    });
    return () => window.cancelAnimationFrame(animationFrame);
  }, [app.editingKnowledgeBase?.id, app.showKnowledgeBaseModal, mode]);

  if (!app.showKnowledgeBaseModal) return null;

  const closeModal = () => {
    if (!busyRef.current) app.closeKnowledgeBaseModal();
  };

  const openCreateEditor = () => {
    if (isBusy) return;
    app.openKnowledgeBaseModal();
    setMode("editor");
  };

  const returnToManager = () => {
    if (isBusy) return;
    app.openKnowledgeBaseModal();
    setMode("manager");
  };

  const modalTitle = mode === "manager"
    ? "品牌知识库"
    : app.editingKnowledgeBase?.id
      ? "编辑知识库"
      : "新建知识库";

  return (
    <ModalOverlay className="knowledge-modal-ux">
      <div
        ref={dialogRef}
        className={`modal ${mode === "manager" ? "knowledge-library-modal" : "knowledge-editor-modal"}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby="knowledge-modal-title"
        tabIndex={-1}
      >
        <div className="knowledge-modal-titlebar">
          <span id="knowledge-modal-title" className="sr-only">{modalTitle}</span>
          <button
            className="knowledge-modal-close"
            type="button"
            aria-label="关闭知识库窗口"
            disabled={isBusy}
            onClick={closeModal}
          >
            ×
          </button>
        </div>

        {mode === "manager" ? (
          <KnowledgeBaseManager
            app={app}
            onCreate={openCreateEditor}
            onBusyChange={setIsBusy}
          />
        ) : (
          <KnowledgeBaseEditor
            app={app}
            onCancel={returnToManager}
            onBusyChange={setIsBusy}
          />
        )}
      </div>
    </ModalOverlay>
  );
}
