function ReferenceIcon({ kind }) {
  if (kind === "link") return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 13.5a4 4 0 0 0 5.7.2l2.1-2.1a4 4 0 0 0-5.7-5.7l-1.2 1.2" /><path d="M14 10.5a4 4 0 0 0-5.7-.2l-2.1 2.1a4 4 0 0 0 5.7 5.7l1.2-1.2" /></svg>;
  if (kind === "spark") return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 2 1.8 6.2L20 10l-6.2 1.8L12 18l-1.8-6.2L4 10l6.2-1.8L12 2Z" /><path d="m19 16 .7 2.3L22 19l-2.3.7L19 22l-.7-2.3L16 19l2.3-.7L19 16Z" /></svg>;
  if (kind === "upload") return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 16V5" /><path d="m8 9 4-4 4 4" /><path d="M5 19h14" /></svg>;
  return <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="3" /><circle cx="8.5" cy="8.5" r="1.5" /><path d="m5 18 4.5-4.5 3 3 2.5-2.5L19 18" /></svg>;
}

export default function KimImageReferenceStep({
  fileInputRef,
  previews = [],
  dragging = false,
  uploadLimitBytes,
  linkPlatform = "小红书",
  linkText = "",
  extractingLink = false,
  reversing = false,
  onDraggingChange,
  onFileSelect,
  onFileDrop,
  onRemovePreview,
  onReverse,
  onLinkPlatformChange,
  onLinkTextChange,
  onExtractLink,
  onSkip,
  onPreview,
}) {
  const uploadLimitCopy = uploadLimitBytes
    ? `支持 JPG / PNG / WEBP，可多选，单张不超过 ${Math.round(uploadLimitBytes / 1024 / 1024)}MB`
    : "支持 JPG / PNG / WEBP，可一次选择多张，大小限制按当前服务配置";

  return <>
    <div className="wizard-step-content">
    <div className="wizard-step-nav" />
    <div className="creation-reference-shell">
      <div className="creation-reference-heading">
        <div>
          <span className="creation-reference-kicker">STEP 01 · START</span>
          <h3><span aria-hidden="true">✦</span> 选择你的创作起点 <span aria-hidden="true">👋</span></h3>
          <p>上传参考图或粘贴链接，AI 将提取视觉风格与要素，帮助你更快产出优质内容。</p>
        </div>
        <span className="creation-reference-orbit" aria-hidden="true">✦</span>
      </div>

      <div className="creation-reference-cards">
        <label
          className={`creation-reference-card creation-reference-upload ${dragging ? "is-dragging" : ""}`}
          tabIndex="0"
          onDragEnter={(event) => { event.preventDefault(); onDraggingChange?.(true); }}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={(event) => { if (event.currentTarget === event.target) onDraggingChange?.(false); }}
          onDrop={(event) => { event.preventDefault(); onDraggingChange?.(false); onFileDrop?.(event.dataTransfer.files); }}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              fileInputRef?.current?.click();
            }
          }}
        >
          <input ref={fileInputRef} type="file" accept="image/png,image/jpeg,image/webp" multiple hidden onChange={onFileSelect} />
          <div className="creation-reference-card-head">
            <span className="creation-reference-icon"><ReferenceIcon kind="image" /></span>
            <div className="creation-reference-card-copyblock">
              <span className="creation-reference-card-title">上传参考图 <em>✦</em></span>
              <span className="creation-reference-card-copy">上传图片自动反推提示词</span>
            </div>
          </div>
          <span className="creation-reference-dropzone">
            <strong><ReferenceIcon kind="upload" /></strong>
            <span>拖拽图片到此处，或 <b>点击上传</b></span>
            <small>{uploadLimitCopy}</small>
          </span>
          <span className="creation-reference-card-foot">AI 将识别画面风格、构图与色调</span>
        </label>

        <div className="creation-reference-card creation-reference-link">
          <div className="creation-reference-card-head">
            <span className="creation-reference-icon"><ReferenceIcon kind="link" /></span>
            <div className="creation-reference-card-copyblock">
              <span className="creation-reference-card-title">粘贴内容链接 <em>✦</em></span>
              <span className="creation-reference-card-copy">解析链接获取原始素材和文案</span>
            </div>
          </div>
          <div className="creation-reference-platforms" role="tablist" aria-label="链接平台">
            {["小红书", "抖音"].map((platform) => <button
              key={platform}
              type="button"
              role="tab"
              aria-selected={linkPlatform === platform}
              className={linkPlatform === platform ? "active" : ""}
              onClick={() => onLinkPlatformChange?.(platform)}
            >{platform === "小红书" ? "📕" : "♪"} {platform}</button>)}
          </div>
          <textarea
            value={linkText}
            onChange={(event) => onLinkTextChange?.(event.target.value)}
            rows={3}
            placeholder={`请粘贴${linkPlatform}内容链接`}
            aria-label={`请粘贴${linkPlatform}内容链接`}
          />
          <div className="creation-reference-link-actions">
            <button className="btn btn-sm btn-primary creation-reference-submit" type="button" disabled={extractingLink || !linkText.trim()} onClick={onExtractLink}>
              {extractingLink ? "解析中..." : "开始解析"}
            </button>
            <small className="creation-reference-safe">
              示例：{linkPlatform === "小红书" ? "https://www.xiaohongshu.com/explore/..." : "https://v.douyin.com/..."}
              <br />
              ◈ 仅解析公开内容，保留你的数据安全
            </small>
          </div>
        </div>

        <button className="creation-reference-card creation-reference-empty" type="button" onClick={onSkip}>
          <div className="creation-reference-card-head">
            <span className="creation-reference-icon"><ReferenceIcon kind="spark" /></span>
            <div className="creation-reference-card-copyblock">
              <span className="creation-reference-card-title">没有素材也能开始 <em>✦</em></span>
              <span className="creation-reference-card-copy">跳过参考素材，直接进入标签选择</span>
            </div>
          </div>
          <span className="creation-reference-empty-art" aria-hidden="true"><span>⌘</span><span>✦</span><span>#</span></span>
          <span className="creation-reference-empty-action">直接开始 <b>→</b></span>
        </button>
      </div>

      {previews.length > 0 && <div className="creation-reference-preview">
        <div className="creation-reference-preview-head"><strong>已上传参考图</strong><span>{previews.length} 张</span></div>
        <div className="reference-preview-grid">
          {previews.map((url, index) => <div key={url} className="reference-preview-item">
            <button type="button" className="media-preview-trigger reference-preview-thumb" title="点击预览" onClick={() => onPreview?.(index)}>
              <img src={url} alt={`参考图 ${index + 1}`} />
            </button>
            <button type="button" className="reference-preview-remove" aria-label={`删除参考图 ${index + 1}`} onClick={() => onRemovePreview?.(index)}>×</button>
          </div>)}
        </div>
        {/* <button className="btn btn-primary creation-reference-preview-action" type="button" disabled={reversing} onClick={onReverse}>
          {reversing ? "反推中..." : "反推提示词并继续 →"}
        </button> */}
      </div>}
      </div>
    </div>

  </>;
}
