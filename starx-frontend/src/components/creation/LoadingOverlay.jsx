import { useEffect, useRef, useState } from "react";

const LOADING_MESSAGES = [
  "AI 正在分析素材...",
  "正在理解内容结构...",
  "正在组织创作结果...",
  "即将完成...",
];

const clampProgress = (value) => Math.min(100, Math.max(0, Number(value) || 0));

export default function LoadingOverlay({
  message,
  statusMessage,
  subMessage,
  progress,
  showProgress = true,
  contained = false,
  embedded = false,
}) {
  const dialogRef = useRef(null);
  const [messageIndex, setMessageIndex] = useState(0);
  const [visualProgress, setVisualProgress] = useState(() => progress == null ? 8 : clampProgress(progress));
  const isPanel = contained || embedded;

  useEffect(() => {
    if (isPanel) return undefined;
    const dialog = dialogRef.current;
    if (!dialog) return undefined;
    const preventCancel = (event) => event.preventDefault();
    dialog.addEventListener("cancel", preventCancel);
    if (!dialog.open) dialog.showModal();
    dialog.focus();
    return () => {
      dialog.removeEventListener("cancel", preventCancel);
      if (dialog.open) dialog.close();
    };
  }, [isPanel]);

  useEffect(() => {
    if (progress != null) {
      setVisualProgress(clampProgress(progress));
      return undefined;
    }

    setVisualProgress(8);
    const timer = window.setInterval(() => {
      setVisualProgress((current) => current >= 90 ? current : Math.min(90, current + 4));
    }, 600);
    return () => window.clearInterval(timer);
  }, [progress]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setMessageIndex((current) => (current + 1) % LOADING_MESSAGES.length);
    }, 2500);
    return () => window.clearInterval(timer);
  }, []);

  const content = (
    <>
      <div className="loading-backdrop" aria-hidden="true" />
      <div className="loading-content">
        <div className="loading-spinner-ring" aria-hidden="true">
          <span className="ring ring-1" />
          <span className="ring ring-2" />
          <span className="ring ring-3" />
          <span className="loading-core">✦</span>
        </div>

        <h3 className="loading-title" id="creation-loading-title">{message || "正在处理"}</h3>
        <p className="loading-message" id="creation-loading-description">
          {statusMessage || LOADING_MESSAGES[messageIndex]}
        </p>
        {subMessage ? <p className="loading-submessage">{subMessage}</p> : null}

        {showProgress ? (
          <div
            className="loading-progress-bar"
            role="progressbar"
            aria-label="处理进度"
            aria-valuemin="0"
            aria-valuemax="100"
            aria-valuenow={Math.round(visualProgress)}
          >
            <span className="loading-progress-fill" style={{ "--progress": visualProgress / 100 }} />
          </div>
        ) : null}

        <div className="loading-particles" aria-hidden="true">
          {Array.from({ length: 6 }, (_, index) => <span className={`particle particle-${index + 1}`} key={index} />)}
        </div>
      </div>
    </>
  );

  if (isPanel) {
    return (
      <section
        className={`loading-overlay ${embedded ? "loading-overlay-embedded" : "loading-overlay-contained"}`}
        aria-busy="true"
        aria-labelledby="creation-loading-title"
        aria-describedby="creation-loading-description"
      >
        {content}
      </section>
    );
  }

  return (
    <dialog
      ref={dialogRef}
      className="loading-overlay"
      aria-modal="true"
      aria-busy="true"
      aria-labelledby="creation-loading-title"
      aria-describedby="creation-loading-description"
      tabIndex={-1}
    >
      {content}
    </dialog>
  );
}
