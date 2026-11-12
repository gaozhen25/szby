import { useEffect, useRef, useState } from "react";

import ModalOverlay from "./ModalOverlay";

import {
  CONTENT_GOAL_OPTIONS,
  DURATION_OPTIONS,
  TONE_STYLE_OPTIONS,
  VIDEO_FORMAT_OPTIONS,
  getInitialCreationPreferences,
  getInitialImagePreferences,
  normalizeCreationPreferences,
  normalizeImagePreferences,
  resolveCreationPreferenceVariant,
  updateImagePreference,
} from "../utils/creationPreferences";
import ImagePreferenceFields from "./ImagePreferenceFields";

const renderOptions = (options) => options.map(({ value, label }) => (
  <option key={value} value={value}>{label}</option>
));

export default function CreationPreferenceModal({ variant, topic, account, initialPreferences, isSubmitting = false, onCancel, onConfirm }) {
  const isVideo = resolveCreationPreferenceVariant(variant) === "video";
  const normalizePreferences = isVideo ? normalizeCreationPreferences : normalizeImagePreferences;
  const getInitialPreferences = isVideo ? getInitialCreationPreferences : getInitialImagePreferences;
  const [preferences, setPreferences] = useState(() => normalizePreferences(
    initialPreferences || getInitialPreferences(topic, account), topic, account
  ));
  const dialogRef = useRef(null);
  const onCancelRef = useRef(onCancel);
  const submittingRef = useRef(isSubmitting);
  onCancelRef.current = onCancel;
  submittingRef.current = isSubmitting;

  useEffect(() => {
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
    const initialFocus = dialog?.querySelector("#creation-target-platform");
    (initialFocus || dialog)?.focus();

    const handleKeyDown = (event) => {
      if (event.key === "Escape" && !submittingRef.current) {
        onCancelRef.current?.();
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
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      if (previouslyFocused instanceof HTMLElement && document.contains(previouslyFocused)) {
        previouslyFocused.focus();
      }
    };
  }, [topic?.id, variant]);

  const configuredPlatforms = account?.platforms?.length
    ? account.platforms
    : [account?.platform].filter(Boolean);
  const platformOptions = configuredPlatforms.length
    ? configuredPlatforms
    : [preferences.targetPlatform];
  const requirementsTooLong = preferences.customRequirements.length > 500;

  const updatePreference = (key, value) => {
    setPreferences((current) => (
      isVideo
        ? { ...current, [key]: value }
        : updateImagePreference(current, key, value)
    ));
  };

  const confirm = (event) => {
    event.preventDefault();
    if (requirementsTooLong) return;
    onConfirm(normalizePreferences(preferences, topic, account));
  };

  const requestCancel = () => {
    if (submittingRef.current) return;
    onCancelRef.current?.();
  };

  return (
    <ModalOverlay className="creation-preference-overlay">
      <div
        ref={dialogRef}
        className="modal creation-preference-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="creation-preference-title"
        tabIndex={-1}
      >
        <div className="creation-preference-header">
          <div>
            <h3 id="creation-preference-title">{isVideo ? "视频创作偏好" : "图片创作偏好"}</h3>
            <p>新手可直接使用推荐值</p>
          </div>
          <button type="button" className="creation-preference-close" aria-label="关闭创作偏好" onClick={requestCancel} disabled={isSubmitting}>×</button>
        </div>

        <p className="creation-preference-topic">{topic?.title}</p>

        <form onSubmit={confirm}>
          <div className="creation-preference-grid">
            <div>
              <label htmlFor="creation-target-platform">目标平台</label>
              <select
                id="creation-target-platform"
                value={preferences.targetPlatform}
                onChange={(event) => updatePreference("targetPlatform", event.target.value)}
              >
                {platformOptions.map((platform) => <option key={platform} value={platform}>{platform}</option>)}
              </select>
            </div>
            {isVideo ? <>
              <div>
                <label htmlFor="creation-duration">视频时长</label>
                <select
                  id="creation-duration"
                  value={preferences.durationSeconds}
                  onChange={(event) => updatePreference("durationSeconds", Number(event.target.value))}
                >
                  {renderOptions(DURATION_OPTIONS)}
                </select>
              </div>
              <div>
                <label htmlFor="creation-content-goal">内容目的</label>
                <select
                  id="creation-content-goal"
                  value={preferences.contentGoal}
                  onChange={(event) => updatePreference("contentGoal", event.target.value)}
                >
                  {renderOptions(CONTENT_GOAL_OPTIONS)}
                </select>
              </div>
              <div>
                <label htmlFor="creation-video-format">视频形式</label>
                <select
                  id="creation-video-format"
                  value={preferences.videoFormat}
                  onChange={(event) => updatePreference("videoFormat", event.target.value)}
                >
                  {renderOptions(VIDEO_FORMAT_OPTIONS)}
                </select>
              </div>
              <div className="creation-preference-full">
                <label htmlFor="creation-tone-style">表达风格</label>
                <select
                  id="creation-tone-style"
                  value={preferences.toneStyle}
                  onChange={(event) => updatePreference("toneStyle", event.target.value)}
                >
                  {renderOptions(TONE_STYLE_OPTIONS)}
                </select>
              </div>
            </> : <ImagePreferenceFields preferences={preferences} onChange={updatePreference} />}
            <div className="creation-preference-full">
              <label htmlFor="creation-custom-requirements">补充要求（选填）</label>
              <textarea
                id="creation-custom-requirements"
                rows="4"
                value={preferences.customRequirements}
                aria-invalid={requirementsTooLong}
                aria-describedby="creation-requirements-help"
                onChange={(event) => updatePreference("customRequirements", event.target.value)}
                placeholder={isVideo ? "例如：更口语化，避免行业术语…" : "例如：奶油色调，人物保持一致…"}
              />
              <div className="creation-preference-help" id="creation-requirements-help">
                <span className={requirementsTooLong ? "creation-preference-error" : ""}>
                  {requirementsTooLong ? "补充要求不能超过 500 个字符" : "仅作为创作约束，不会覆盖账号或产品资料"}
                </span>
                <span>{preferences.customRequirements.length}/500</span>
              </div>
            </div>
          </div>

          <div className="modal-actions">
            <button type="button" className="btn" onClick={requestCancel} disabled={isSubmitting}>取消</button>
            <button type="submit" className="btn btn-primary" disabled={requirementsTooLong || isSubmitting}>
              {isSubmitting ? "正在创建…" : isVideo ? "确认偏好并生成 →" : "确认偏好并生成提示词 →"}
            </button>
          </div>
        </form>
      </div>
    </ModalOverlay>
  );
}
