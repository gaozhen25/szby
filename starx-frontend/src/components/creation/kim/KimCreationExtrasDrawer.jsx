import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

import "../../../styles/content-creation-kim-extras.css";

export default function KimCreationExtrasDrawer({ open, onClose, children }) {
  const closeButtonRef = useRef(null);
  const lastFocusedElement = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    lastFocusedElement.current = document.activeElement;
    closeButtonRef.current?.focus();
    const closeOnEscape = (event) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      window.removeEventListener("keydown", closeOnEscape);
      lastFocusedElement.current?.focus?.();
    };
  }, [onClose, open]);

  if (!open) return null;

  return createPortal(
    <div className="kim-extras-overlay">
      <div
        className="kim-extras-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="kim-extras-title"
      >
        <header className="kim-extras-header">
          <div>
            <span>ADVANCED</span>
            <h3 id="kim-extras-title">专业工具</h3>
          </div>
          <button
            ref={closeButtonRef}
            className="kim-extras-close"
            type="button"
            onClick={onClose}
            aria-label="关闭专业工具"
          >
            ×
          </button>
        </header>
        <div className="kim-extras-body">{children}</div>
      </div>
    </div>,
    document.body,
  );
}
