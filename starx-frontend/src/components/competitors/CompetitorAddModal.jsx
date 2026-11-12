import { useEffect, useRef, useState } from "react";
import ModalOverlay from "../ModalOverlay";

const PLATFORMS = [
  {
    key: "抖音",
    label: "抖音",
    placeholder: "抖音号或者抖音主页链接",
  },
  {
    key: "小红书",
    label: "小红书",
    placeholder: "小红书号或者小红书主页链接",
  },
];

export default function CompetitorAddModal({ open, onClose, onSubmit }) {
  const [platform, setPlatform] = useState("抖音");
  const [value, setValue] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const dialogRef = useRef(null);
  const submittingRef = useRef(false);

  useEffect(() => {
    if (open) {
      setPlatform("抖音");
      setValue("");
    }
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;
    const previouslyFocused = document.activeElement;
    const dialog = dialogRef.current;
    const focusableSelector = [
      'a[href]',
      'button:not([disabled])',
      'input:not([disabled])',
      'select:not([disabled])',
      'textarea:not([disabled])',
      '[tabindex]:not([tabindex="-1"])',
    ].join(",");
    const initialFocus = dialog?.querySelector("input:not([disabled])");
    initialFocus?.focus();

    const onKeyDown = (event) => {
      if (event.key === "Escape" && !submittingRef.current) {
        onClose();
        return;
      }
      if (event.key !== "Tab" || !dialog) return;
      const focusable = Array.from(dialog.querySelectorAll(focusableSelector));
      if (focusable.length === 0) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      if (previouslyFocused instanceof HTMLElement && document.contains(previouslyFocused)) {
        previouslyFocused.focus();
      }
    };
  }, [onClose, open]);

  if (!open) return null;
  const requestClose = () => {
    if (submittingRef.current) return;
    onClose();
  };
  const submit = async (event) => {
    event.preventDefault();
    if (submittingRef.current) return;
    const normalizedValue = value.trim();
    if (!normalizedValue) return;
    submittingRef.current = true;
    setSubmitting(true);
    try {
      await onSubmit({ platform, reference: normalizedValue });
      onClose();
    } catch (_error) {
      // 数据层展示错误；保留当前输入，方便用户修正后重试。
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  };

  return (
    <ModalOverlay className="monitor-add-overlay">
      <section
        ref={dialogRef}
        className="modal monitor-add-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="competitor-add-title"
        tabIndex={-1}
      >
        <header className="monitor-add-header">
          <button
            type="button"
            className="btn btn-xs monitor-add-close"
            aria-label="关闭"
            disabled={submitting}
            onClick={requestClose}
          >
            ×
          </button>
          <div>
            <span className="monitor-add-eyebrow">新增监控目标</span>
            <h3 id="competitor-add-title">添加竞品监控</h3>
            <p>选择平台并填写账号号值或公开主页链接，系统会自动识别并持续更新。</p>
          </div>
        </header>

        <form className="monitor-add-form" onSubmit={submit}>
          <div className="monitor-add-platform" role="group" aria-label="账号平台">
            {PLATFORMS.map((item) => (
              <button
                key={item.key}
                type="button"
                className={`pill ${platform === item.key ? "active" : ""}`}
                aria-pressed={platform === item.key}
                disabled={submitting}
                onClick={() => {
                  setPlatform(item.key);
                  setValue("");
                }}
              >
                {item.label}
              </button>
            ))}
          </div>
          <label className="monitor-url-field">
            <span className="field-label">{platform}号或主页链接</span>
            <input
              type="text"
              required
              disabled={submitting}
              value={value}
              onChange={(event) => setValue(event.target.value)}
              placeholder={PLATFORMS.find((item) => item.key === platform)?.placeholder}
              autoComplete="off"
            />
            <small>后台会自动判断输入的是{platform}号还是公开主页链接。</small>
          </label>
          <div className="modal-actions monitor-add-actions">
            <button type="button" className="btn" disabled={submitting} onClick={requestClose}>取消</button>
            <button type="submit" className="btn btn-primary" disabled={submitting || !value.trim()}>
              {submitting ? "正在添加…" : "添加并刷新"}
            </button>
          </div>
        </form>
      </section>
    </ModalOverlay>
  );
}
