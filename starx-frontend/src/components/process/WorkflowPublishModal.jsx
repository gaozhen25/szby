import { useEffect, useRef } from "react";

import MediaLightbox, { useMediaLightbox } from "../MediaLightbox";
import WorkflowLocalMediaUpload from "./WorkflowLocalMediaUpload";
import { createImageSlide, createVideoSlide } from "../../utils/mediaLightbox";
import { isPublishDeviceConfigurationError } from "../../utils/workflowPublish";
import ModalOverlay from "../ModalOverlay";

const PUBLISH_STEPS = [
  { status: "pending", label: "已提交" },
  { status: "queued", label: "设备处理中" },
  { status: "running", label: "发布中" },
  { status: "succeeded", label: "发布成功" },
];

const PUBLISH_STATUS_LABELS = {
  pending: "已创建",
  queued: "排队中",
  running: "发布中",
  succeeded: "已发布",
  failed: "发布失败",
  cancelled: "已取消",
};

const ACTIVE_PUBLISH_STATUSES = new Set(["pending", "queued", "running"]);
const PUBLISH_PLATFORMS = ["小红书", "抖音", "快手"];

function getCandidateUrl(candidate) {
  return typeof candidate === "string" ? candidate : String(candidate?.url || "");
}

function isHttpsCandidate(candidate) {
  return /^https:\/\//i.test(getCandidateUrl(candidate).trim());
}

function candidateLabel(candidate, index, fallbackType) {
  if (typeof candidate === "object" && candidate?.label) return String(candidate.label);
  return `${candidateKind(candidate, fallbackType) === "video" ? "视频" : "图片"} ${index + 1}`;
}

function candidateKind(candidate, fallbackType) {
  if (typeof candidate === "object" && ["image", "video"].includes(candidate?.kind)) {
    return candidate.kind;
  }
  return fallbackType === "video" ? "video" : "image";
}

export default function WorkflowPublishModal({ draft, publishState, deviceConfigured, platformSupported, busy, uploading = false, suspended = false, error, onChange, onUploadImages, onUploadVideo, onConfirm, onRefresh, onConfigureDevice, onClose }) {
  const mediaLightbox = useMediaLightbox();
  const dialogRef = useRef(null);
  const onCloseRef = useRef(onClose);
  const busyRef = useRef(busy);
  const suspendedRef = useRef(suspended);
  onCloseRef.current = onClose;
  busyRef.current = busy;
  suspendedRef.current = suspended;

  const requestClose = () => {
    if (busyRef.current) return;
    if (suspended) return;
    onCloseRef.current?.();
  };

  useEffect(() => {
    if (!draft || suspended) return undefined;

    const previouslyFocused = document.activeElement;
    const focusTimer = window.setTimeout(() => dialogRef.current?.focus(), 0);

    const handleKeyDown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        if (mediaLightbox.open) {
          mediaLightbox.closeMedia();
          return;
        }
        requestClose();
        return;
      }
      const focusScope = dialogRef.current;
      if (event.key !== "Tab" || !focusScope) return;

      const focusable = Array.from(focusScope.querySelectorAll(
        'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), video[controls], [tabindex]:not([tabindex="-1"])',
      )).filter((element) => !element.hasAttribute("hidden"));

      if (focusable.length === 0) {
        event.preventDefault();
        focusScope.focus();
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!focusScope.contains(document.activeElement) || document.activeElement === focusScope) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
        return;
      }
      if (event.shiftKey && document.activeElement === first) {
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
      if (!suspendedRef.current && previouslyFocused instanceof HTMLElement && document.contains(previouslyFocused)) {
        previouslyFocused.focus();
      }
    };
  }, [draft?.creationId, suspended, mediaLightbox.open, mediaLightbox.closeMedia]);

  if (!draft) return null;

  const mediaCandidates = Array.isArray(draft.mediaCandidates) ? draft.mediaCandidates : [];
  const httpsCandidates = mediaCandidates.filter(isHttpsCandidate);
  const selectedMediaUrls = Array.isArray(draft.selectedMediaUrls) ? draft.selectedMediaUrls : [];
  const selectedMediaUrlSet = new Set(selectedMediaUrls);
  const selectedMediaIsAvailable = selectedMediaUrls.length > 0 && selectedMediaUrls.every(
    (url) => httpsCandidates.some((candidate) => getCandidateUrl(candidate) === url),
  );
  const status = publishState?.status || "";
  const statusIndex = PUBLISH_STEPS.findIndex((step) => step.status === status);
  const publishIsActive = ACTIVE_PUBLISH_STATUSES.has(status);
  const publishHasFinished = status === "succeeded";
  const publishFailed = status === "failed";
  const displayError = error || publishState?.errorMessage || "";
  const publishNeedsConfiguration = isPublishDeviceConfigurationError(error, publishState?.errorMessage);
  const deviceNeedsConfiguration = !deviceConfigured || publishNeedsConfiguration;
  const descriptionReady = Boolean(String(draft.description || "").trim());
  const canConfirm = Boolean(
    platformSupported
    && deviceConfigured
    && selectedMediaIsAvailable
    && descriptionReady
    && !busy
    && !publishIsActive
    && !publishHasFinished,
  );
  const updateDraft = (patch) => onChange?.({ ...draft, ...patch });
  const selectMedia = (url) => {
    if (draft.type === "video") {
      updateDraft({ selectedMediaUrls: [url] });
      return;
    }
    const nextSelected = new Set(selectedMediaUrls);
    if (nextSelected.has(url)) nextSelected.delete(url);
    else nextSelected.add(url);
    updateDraft({
      selectedMediaUrls: mediaCandidates
        .map(getCandidateUrl)
        .filter((candidateUrl) => nextSelected.has(candidateUrl)),
    });
  };

  return (
    <ModalOverlay
      className="workflow-publish-overlay"
      aria-hidden={suspended || undefined}
      inert={suspended ? "" : undefined}
    >
      <section
        ref={dialogRef}
        className="modal workflow-publish-modal"
        role="dialog"
        aria-modal={suspended ? undefined : "true"}
        aria-labelledby="workflow-publish-title"
        aria-describedby="workflow-publish-description"
        aria-busy={busy}
        tabIndex={-1}
      >
        <header className="workflow-publish-modal-header">
          <div>
            <span className="workflow-publish-eyebrow">流程发布</span>
            <h3 id="workflow-publish-title">发布前确认</h3>
            <p id="workflow-publish-description">确认流程中保存的素材与文案后，再交给发布设备执行。</p>
          </div>
          <button
            type="button"
            className="btn btn-xs workflow-publish-close"
            aria-label={busy ? "发布请求处理中，暂时无法关闭" : "关闭发布窗口"}
            disabled={busy}
            onClick={requestClose}
          >
            ×
          </button>
        </header>

        <label className="workflow-publish-platform">
          <span>发布平台</span>
          <select
            aria-label="发布平台"
            value={draft.targetPlatform || ""}
            disabled={busy || publishIsActive || publishHasFinished}
            onChange={(event) => updateDraft({ targetPlatform: event.target.value })}
          >
            <option value="" disabled>请选择发布平台</option>
            {PUBLISH_PLATFORMS.map((platform) => (
              <option value={platform} key={platform}>{platform}</option>
            ))}
          </select>
          <small>默认使用流程平台，发布前可以切换。</small>
        </label>

        {!platformSupported ? (
          <div className="workflow-publish-notice warning" role="alert">
            <strong>当前平台暂不支持自动发布</strong>
            <span>请保留任务和素材，待平台接入后再从流程管理发布。</span>
          </div>
        ) : deviceNeedsConfiguration ? (
          <div className="workflow-publish-notice warning" role="alert">
            <div>
              <strong>{deviceConfigured ? "发布设备配置需要检查" : "发布设备尚未配置"}</strong>
              <span>
                {deviceConfigured
                  ? "当前错误指向发布设备配置，请检查后再重新发布。"
                  : `需要先为 ${draft.targetPlatform || "当前平台"} 配置 Android 设备 ID。`}
              </span>
            </div>
            <button type="button" className="btn btn-sm" disabled={busy} onClick={onConfigureDevice}>
              {deviceConfigured ? "检查设备配置" : "去配置设备"}
            </button>
          </div>
        ) : (
          <div className="workflow-publish-notice success" role="status">
            <strong>发布设备已就绪</strong>
            <span>确认后会提交到已配置的自动发布设备。</span>
          </div>
        )}

        <div className="workflow-publish-body">
          <fieldset className="workflow-publish-media">
            <legend>{draft.type === "image" ? "选择发布图片（可多选）" : "选择发布视频"}</legend>
            <WorkflowLocalMediaUpload
              type={draft.type}
              uploading={uploading}
              disabled={busy || publishIsActive || publishHasFinished}
              onSelect={(files) => draft.type === "image"
                ? onUploadImages?.(files)
                : onUploadVideo?.(files[0])}
            />
            {mediaCandidates.length > 0 ? (
              <div className="workflow-publish-media-grid">
                {mediaCandidates.map((candidate, index) => {
                  const url = getCandidateUrl(candidate);
                  const isHttps = isHttpsCandidate(candidate);
                  const kind = candidateKind(candidate, draft.type);
                  const selected = selectedMediaUrlSet.has(url);
                  return (
                    <label
                      className={`workflow-publish-media-option ${selected ? "selected" : ""} ${isHttps ? "" : "unavailable"}`}
                      key={`${url}-${index}`}
                      title={isHttps ? "点击预览" : undefined}
                      onDoubleClick={(event) => {
                        if (!isHttps) return;
                        event.preventDefault();
                        const label = candidateLabel(candidate, index, draft.type);
                        mediaLightbox.openMedia([
                          kind === "video"
                            ? createVideoSlide(url, { title: label, downloadFilename: `starx-publish-${index + 1}.mp4` })
                            : createImageSlide(url, { title: label, downloadFilename: `starx-publish-${index + 1}.png` }),
                        ], 0);
                      }}
                      onClick={(event) => {
                        if (!isHttps) return;
                        if (event.target instanceof HTMLInputElement) return;
                        // Keep selection via checkbox/radio; preview via explicit preview chip below.
                      }}
                    >
                      <input
                        type={draft.type === "image" ? "checkbox" : "radio"}
                        name="workflow-publish-media"
                        value={url}
                        checked={selected}
                        disabled={!isHttps || busy || publishIsActive || publishHasFinished}
                        onChange={() => selectMedia(url)}
                      />
                      <span className="workflow-publish-media-preview" aria-hidden="true">
                        {isHttps && kind === "image" ? <img src={url} alt="" /> : null}
                        {isHttps && kind === "video" ? <video src={url} muted preload="metadata" /> : null}
                        {!isHttps ? <span>!</span> : null}
                      </span>
                      <span className="workflow-publish-media-copy">
                        <strong>{candidateLabel(candidate, index, draft.type)}</strong>
                        <small title={url}>{url || "素材地址为空"}</small>
                        {isHttps ? (
                          <button
                            type="button"
                            className="btn btn-xs workflow-publish-media-preview-btn"
                            onClick={(event) => {
                              event.preventDefault();
                              event.stopPropagation();
                              const label = candidateLabel(candidate, index, draft.type);
                              mediaLightbox.openMedia([
                                kind === "video"
                                  ? createVideoSlide(url, { title: label, downloadFilename: `starx-publish-${index + 1}.mp4` })
                                  : createImageSlide(url, { title: label, downloadFilename: `starx-publish-${index + 1}.png` }),
                              ], 0);
                            }}
                          >
                            预览
                          </button>
                        ) : null}
                        {!isHttps ? <em>仅支持 HTTPS 素材</em> : null}
                      </span>
                    </label>
                  );
                })}
              </div>
            ) : (
              <p className="workflow-publish-empty">流程中暂无素材，可从本地选择文件上传。</p>
            )}
            {httpsCandidates.length === 0 ? (
              <p className="inline-error" role="alert">
                {draft.type === "video" ? "请选择本地 MP4 视频上传，或返回创作页保存视频素材。" : "请选择本地图片上传，或返回创作页保存图片素材。"}
              </p>
            ) : null}
          </fieldset>

          <div className="workflow-publish-fields">
            <label>
              <span className="field-label">作品标题 <em>选填</em></span>
              <input
                type="text"
                value={draft.title || ""}
                maxLength={255}
                disabled={busy || publishIsActive || publishHasFinished}
                placeholder="填写发布到平台的作品标题"
                onChange={(event) => updateDraft({ title: event.target.value })}
              />
              <small className="workflow-publish-field-hint">
                支持标题的平台将优先展示，最多 255 个字符
              </small>
            </label>
            <label>
              <span className="field-label">发布文案</span>
              <textarea
                rows={6}
                value={draft.description || ""}
                aria-invalid={!descriptionReady}
                aria-describedby={!descriptionReady ? "workflow-publish-description-error" : undefined}
                disabled={busy || publishIsActive || publishHasFinished}
                placeholder="填写发布到平台的文案"
                onChange={(event) => updateDraft({ description: event.target.value })}
              />
              {!descriptionReady ? (
                <span id="workflow-publish-description-error" className="inline-error" role="alert">
                  请填写发布文案后再发布
                </span>
              ) : null}
            </label>
            <label>
              <span className="field-label">发布可见性</span>
              <select
                value={String(draft.visibility ?? "0")}
                disabled={busy || publishIsActive || publishHasFinished}
                onChange={(event) => updateDraft({ visibility: event.target.value })}
              >
                <option value="0">默认公开</option>
                <option value="1">好友可见</option>
                <option value="2">仅自己可见</option>
              </select>
            </label>
            <label className="workflow-publish-checkbox">
              <input
                type="checkbox"
                checked={draft.copyToAlbum !== false}
                disabled={busy || publishIsActive || publishHasFinished}
                onChange={(event) => updateDraft({ copyToAlbum: event.target.checked })}
              />
              <span>发布后保存到设备相册</span>
            </label>
          </div>
        </div>

        {publishState ? (
          <section className={`workflow-publish-status ${status || "unknown"}`} aria-live="polite">
            <div className="workflow-publish-status-header">
              <div>
                <span>发布状态</span>
                <strong>{PUBLISH_STATUS_LABELS[status] || status || "未知"}</strong>
                <small>
                  {[publishState.platform, publishState.taskId || publishState.publishJobId].filter(Boolean).join(" · ")}
                </small>
              </div>
              <button type="button" className="btn btn-xs" disabled={busy} onClick={onRefresh}>
                {busy ? "刷新中..." : "刷新状态"}
              </button>
            </div>
            <ol className="workflow-publish-timeline" aria-label="发布进度">
              {PUBLISH_STEPS.map((step, index) => {
                const active = status === step.status;
                const done = status === "succeeded" ? index <= statusIndex : statusIndex > index;
                return (
                  <li className={`${active ? "active" : ""} ${done ? "done" : ""}`} key={step.status}>
                    <span aria-hidden="true">{done ? "✓" : index + 1}</span>
                    <strong>{step.label}</strong>
                  </li>
                );
              })}
              {publishFailed ? (
                <li className="failed active">
                  <span aria-hidden="true">!</span>
                  <strong>发布失败</strong>
                </li>
              ) : null}
            </ol>
            {publishNeedsConfiguration ? (
              <button type="button" className="btn btn-sm" disabled={busy} onClick={onConfigureDevice}>检查设备配置</button>
            ) : null}
          </section>
        ) : null}

        {displayError ? <p className="inline-error workflow-publish-error" role="alert">{displayError}</p> : null}

        <footer className="modal-actions workflow-publish-actions">
          <button type="button" className="btn" disabled={busy} onClick={requestClose}>
            {busy ? "发布请求处理中" : "关闭"}
          </button>
          {!publishHasFinished ? (
            <button type="button" className="btn btn-primary" disabled={!canConfirm} onClick={onConfirm}>
              {busy ? "处理中..." : publishIsActive ? "发布进行中" : publishFailed || status === "cancelled" ? "重新发布" : "确认发布"}
            </button>
          ) : null}
        </footer>

        <MediaLightbox
          open={mediaLightbox.open}
          index={mediaLightbox.index}
          slides={mediaLightbox.slides}
          onClose={mediaLightbox.closeMedia}
          onIndexChange={mediaLightbox.setMediaIndex}
        />
      </section>
    </ModalOverlay>
  );
}
