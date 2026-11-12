import { useState } from "react";
import { downloadMedia, downloadMediaZip } from "../../../utils/mediaLightbox";
import { buildFieldsFromExtract } from "../../../utils/contentExtraction";

const mediaUrl = (item) => item?.previewUrl || item?.url || item?.src || item?.originalUrl || "";

async function copyToClipboard(value, onToast) {
  const text = String(value || "").trim();
  if (!text) {
    onToast?.("暂无可复制内容", "warning");
    return;
  }
  try {
    if (!navigator.clipboard?.writeText) throw new Error("clipboard unavailable");
    await navigator.clipboard.writeText(text);
    onToast?.("已复制", "success");
  } catch {
    onToast?.("复制失败", "warning");
  }
}

async function downloadAllMedia(items, onToast) {
  const list = (Array.isArray(items) ? items : [])
    .map((image, index) => ({
      url: mediaUrl(image),
      filename: `starx-parse-${index + 1}.png`,
    }))
    .filter((item) => item.url);
  if (!list.length) {
    onToast?.("暂无可下载素材", "warning");
    return false;
  }

  try {
    const { successCount, total } = await downloadMediaZip(list, "starx-parse-materials.zip");
    if (successCount === total && total > 0) {
      onToast?.(`已打包下载 ${successCount} 张素材`, "success");
      return true;
    }
    if (successCount > 0) {
      onToast?.(`已打包 ${successCount}/${total} 张，其余请逐张重试`, "warning");
      return true;
    }
    onToast?.("打包下载失败，请逐张下载", "warning");
    return false;
  } catch {
    onToast?.("打包下载失败，请逐张下载", "warning");
    return false;
  }
}

function ParseCopyButton({ copyValue, onToast, label }) {
  return (
    <button
      type="button"
      className="btn btn-xs parse-copy-btn"
      aria-label={`复制${label}`}
      onClick={() => copyToClipboard(copyValue, onToast)}
    >
      复制
    </button>
  );
}

export default function KimLinkParseResult({ data, onBack, onPreviewImage, onToast }) {
  const [downloadingAll, setDownloadingAll] = useState(false);
  if (!data) return null;
  const images = (data.images || []).filter((image) => mediaUrl(image));
  const titleText = String(data.title || "").trim();
  const { body: descriptionText, hashtags } = buildFieldsFromExtract(data);

  const handleDownloadAll = async () => {
    if (downloadingAll) return;
    setDownloadingAll(true);
    try {
      await downloadAllMedia(images, onToast);
    } finally {
      setDownloadingAll(false);
    }
  };

  return <div className="wizard-step-content parse-result-page">
    <div className="parse-result-header">
      <button className="btn btn-sm" type="button" onClick={onBack}>← 返回</button>
      <h3>解析结果</h3>
      <span aria-hidden="true" />
    </div>
    <div className="parse-result-body">
      <div className="parse-info-card">
        <h4>📋 内容信息</h4>
        {data.platform && <p className="parse-platform">{data.platform}</p>}
        {titleText ? (
          <p className="parse-title parse-copy-follow">
            <span className="parse-copy-text">{titleText}</span>
            <ParseCopyButton copyValue={titleText} onToast={onToast} label="标题" />
          </p>
        ) : null}
        {descriptionText || hashtags.length > 0 ? (
          <div className="parse-desc-block">
            {descriptionText ? (
              <p className="parse-desc parse-copy-follow">
                <span className="parse-copy-text">{descriptionText}</span>
                <ParseCopyButton copyValue={descriptionText} onToast={onToast} label="正文" />
              </p>
            ) : null}
            {hashtags.length > 0 ? (
              <div className="parse-hashtags">{hashtags.map((tag) => <span className="parse-hashtag" key={tag}>{tag}</span>)}</div>
            ) : null}
          </div>
        ) : null}
        {data.url && <a href={data.url} target="_blank" rel="noreferrer" className="parse-source-link">查看原文 ↗</a>}
      </div>
      {images.length > 0 && <div className="parse-result-images">
        <div className="parse-section-header">
          <h4>🖼️ 图片素材 ({images.length})</h4>
          <button
            type="button"
            className="btn btn-xs parse-download-all-btn"
            disabled={downloadingAll}
            onClick={handleDownloadAll}
          >
            {downloadingAll ? "下载中…" : "⬇️ 一键下载全部素材"}
          </button>
        </div>
        <div className="parse-image-grid">
          {images.map((image, index) => {
            const url = mediaUrl(image);
            return (
              <article className="parse-image-card" key={`${url}-${index}`}>
                <button type="button" className="media-preview-trigger" title="点击预览" onClick={() => onPreviewImage?.(index)}>
                  <img src={url} alt={image.title || `素材 ${index + 1}`} referrerPolicy="no-referrer" />
                </button>
                <div className="parse-image-actions">
                  <span className="parse-image-title">{image.title || `素材 ${index + 1}`}</span>
                  <button type="button" className="btn btn-xs" onClick={() => downloadMedia(url, `starx-parse-${index + 1}.png`)}>⬇️ 下载</button>
                </div>
              </article>
            );
          })}
        </div>
      </div>}
    </div>
  </div>;
}
