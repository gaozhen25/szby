import { useMemo } from "react";
import { buildVideoPreviewUrl } from "../../../utils/mediaPreview";
import { downloadMedia } from "../../../utils/mediaLightbox";

export default function KimVideoReferenceStep({
  linkText,
  busy,
  reference,
  activeJob,
  onLinkTextChange,
  onAnalyze,
  onSkip,
  onPreviewCover,
  onPreviewVideo,
}) {
  const analyzing = busy === "video-extract" || busy === "video-analysis";
  const coverUrl = reference?.cover
    || reference?.coverUrl
    || reference?.images?.[0]?.previewUrl
    || reference?.images?.[0]?.url
    || "";
  const sourceVideoUrl = reference?.videos?.[0]?.url || "";
  const previewVideoUrl = useMemo(
    () => sourceVideoUrl ? buildVideoPreviewUrl(sourceVideoUrl, Date.now()) : "",
    [sourceVideoUrl],
  );

  return (
    <div className="wizard-step-content">
      <div className="video-reference-step">
        <h4>视频素材参考</h4>
        <p className="muted">粘贴视频分享链接，解析完成后先确认原视频，再进入脚本创作。</p>
        <textarea
          value={linkText}
          onChange={(event) => onLinkTextChange(event.target.value)}
          rows={4}
          placeholder="粘贴抖音 / 小红书 / 快手视频分享文本..."
          className="full-width-textarea"
        />
        <button className="btn btn-primary btn-lg full-btn" type="button" disabled={analyzing || !linkText.trim()} onClick={onAnalyze}>
          {analyzing ? "解析中..." : "开始解析"}
        </button>
        <button className="btn btn-lg full-btn" type="button" disabled={analyzing} onClick={onSkip}>跳过参考链接，直接写脚本</button>

        {reference ? (
          <div className="link-reference-card video-reference-result">
            {coverUrl || previewVideoUrl ? (
              <div className="video-reference-media">
                {coverUrl ? (
                  <button type="button" className="video-reference-cover-btn media-preview-trigger" title="点击预览封面" onClick={() => onPreviewCover?.(coverUrl)}>
                    <img className="video-reference-cover" src={coverUrl} alt={reference.title ? `${reference.title}封面` : "视频封面预览"} />
                  </button>
                ) : null}
                {previewVideoUrl ? (
                  <div className="video-reference-player-wrap">
                    <video className="video-reference-player" src={previewVideoUrl} poster={coverUrl || undefined} controls playsInline preload="metadata">你的浏览器暂不支持视频预览</video>
                    <div className="video-reference-player-actions">
                      <button type="button" className="btn btn-xs" onClick={() => onPreviewVideo?.(previewVideoUrl, coverUrl)}>放大预览</button>
                      <button type="button" className="btn btn-xs" onClick={() => downloadMedia(sourceVideoUrl || previewVideoUrl, "starx-video.mp4")}>下载</button>
                    </div>
                  </div>
                ) : null}
              </div>
            ) : null}
            <div className="video-reference-meta">
              <strong>{reference.title || "已解析内容"}</strong>
              <small>{reference.platform} · {(reference.images || []).length} 图 · {(reference.videos || []).length} 视频</small>
              {reference.description ? <p className="link-reference-desc">{reference.description}</p> : null}
            </div>
          </div>
        ) : null}

        {activeJob?.status === "completed" ? <div className="image-result-status">分析完成。请先确认原视频，再点击下一步进入脚本创作。</div> : null}
        {activeJob && ["pending", "running"].includes(activeJob.status) ? <div className="image-result-status"><span className="btn-spinner" /> 正在分析视频内容...</div> : null}
        {activeJob?.status === "failed" ? <div className="image-result-status error">视频音轨分析失败：{activeJob.error || "请点击下一步重试"}</div> : null}
      </div>
    </div>
  );
}
