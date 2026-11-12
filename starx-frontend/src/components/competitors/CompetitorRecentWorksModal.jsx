import { useEffect, useRef, useState } from "react";

import CompetitorCoverImage from "./CompetitorCoverImage.jsx";
import ModalOverlay from "../ModalOverlay";

function safeExternalUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" ? url.toString() : "";
  } catch {
    return "";
  }
}

function filterRecentWorks(works, days) {
  const cutoff = Date.now() - days * 24 * 60 * 60 * 1000;
  return (works || [])
    .filter((work) => {
      const publishedAt = new Date(work.publishedAt).getTime();
      return Number.isFinite(publishedAt) && publishedAt >= cutoff;
    })
    .sort((left, right) => new Date(right.publishedAt) - new Date(left.publishedAt));
}

function formatPublishedAt(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "发布时间未知";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function metricEntries(metrics = {}) {
  return [
    ["赞", metrics.likes],
    ["评", metrics.comments],
    ["藏", metrics.collects],
    ["分享", metrics.shares],
  ].filter(([, value]) => Number.isFinite(value));
}

export default function CompetitorRecentWorksModal({ open, accountName, works, onClose }) {
  const [days, setDays] = useState(7);
  const dialogRef = useRef(null);

  useEffect(() => {
    if (open) setDays(7);
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;
    const previouslyFocused = document.activeElement;
    const dialog = dialogRef.current;
    const focusableSelector = 'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])';
    dialog?.querySelector("button")?.focus();

    const onKeyDown = (event) => {
      if (event.key === "Escape") {
        onClose();
        return;
      }
      if (event.key !== "Tab" || !dialog) return;
      const focusable = Array.from(dialog.querySelectorAll(focusableSelector));
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable.at(-1);
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
  const filteredWorks = filterRecentWorks(works, days);

  return (
    <ModalOverlay className="competitor-recent-overlay">
      <section
        ref={dialogRef}
        className="modal competitor-recent-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="competitor-recent-title"
        tabIndex={-1}
      >
        <header className="competitor-recent-header">
          <div>
            <span>近期作品</span>
            <h3 id="competitor-recent-title">{accountName || "监控博主"}</h3>
          </div>
          <button type="button" className="btn btn-xs" aria-label="关闭近期作品" onClick={onClose}>×</button>
        </header>

        <div className="competitor-recent-filters" aria-label="作品发布时间范围">
          {[1, 2, 7].map((option) => <button
            type="button"
            key={option}
            className={days === option ? "active" : ""}
            aria-pressed={days === option}
            onClick={() => setDays(option)}
          >{option === 7 ? "一周内" : `${option}天内`}</button>)}
          <span>{filteredWorks.length} 条作品</span>
        </div>

        <div className="competitor-recent-list">
          {filteredWorks.map((work) => {
            const contentUrl = safeExternalUrl(work.contentUrl);
            return <article className="competitor-recent-work" key={work.platformContentId || contentUrl}>
              <div className="competitor-recent-cover">
                <CompetitorCoverImage url={work.coverUrl} />
              </div>
              <div className="competitor-recent-copy">
                <strong>{work.title || "未命名作品"}</strong>
                <time dateTime={work.publishedAt}>{formatPublishedAt(work.publishedAt)}</time>
                <div className="competitor-recent-metrics">
                  {metricEntries(work.metrics).map(([label, value]) => (
                    <span key={label}>{label} <b>{value.toLocaleString("zh-CN")}</b></span>
                  ))}
                </div>
              </div>
              {contentUrl ? <a className="btn btn-xs" href={contentUrl} target="_blank" rel="noreferrer">查看 ↗</a> : null}
            </article>;
          })}
          {!filteredWorks.length ? <div className="competitor-recent-empty">该时间范围内暂无作品</div> : null}
        </div>
      </section>
    </ModalOverlay>
  );
}
