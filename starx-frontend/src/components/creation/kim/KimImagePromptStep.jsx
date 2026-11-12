import { downloadMedia } from "../../../utils/mediaLightbox";

export default function KimImagePromptStep({
  prompt, negativePrompt, selectedTagCount, ratio, creativityLevel, genCount,
  materialInputRef, materialPreviews, imageGroups, selectedVariants, referenceImages,
  reverseResult, submitting, generating, canGenerate,
  onSaveTemplate,
  onBack, onClearReverse, onPromptChange, onNegativePromptChange, onRatioChange, onCreativityChange,
  onMaterialSelect, onMaterialOpen, onCountChange, onGenerate, onSelectVariant, onPreview, onPreviewOriginal, onPreviewMaterials, onDownload,
}) {
  return <div className="wizard-step-content">
    <div className="wizard-step-nav">
      <button className="btn btn-sm" type="button" onClick={onBack}>← 重新选择风格</button>
    </div>
    <div className="prompt-input-step">
      <div className="prompt-input-section">
        {reverseResult && (
          <div className="reverse-result-card">
            <div className="section-row">
              <h4>反推结果</h4>
              <button className="btn btn-xs" type="button" onClick={onClearReverse}>收起</button>
            </div>
            {reverseResult.positive && <p className="reverse-result-text">{reverseResult.positive}</p>}
          </div>
        )}
        <div className="prompt-field-heading">
          <div><label className="field-label" htmlFor="image-generation-prompt">生图提示词</label><small>写好后可保存为模板，下次一键复用</small></div>
          <button className="btn btn-sm prompt-save-template-btn" type="button" onClick={onSaveTemplate} disabled={!prompt.trim() && selectedTagCount === 0}>✦ 保存为模板</button>
        </div>
        <textarea id="image-generation-prompt" value={prompt} onChange={(event) => onPromptChange(event.target.value)} rows={6} maxLength={500} placeholder="描述你想要生成的画面..." />
        <div className="prompt-meta-row">
          <span className="char-count">{prompt.length}/500</span>
          {selectedTagCount > 0 && <span className="tag-inject-hint">将隐式注入 {selectedTagCount} 个标签</span>}
        </div>
        <label className="field-label">负向提示词</label>
        <textarea value={negativePrompt} onChange={(event) => onNegativePromptChange(event.target.value)} rows={3} placeholder="低质量、模糊..." />
        <div className="prompt-advanced-grid">
          <div>
            <label className="field-label">图片比例</label>
            <div className="ratio-options">
              {[["1:1", "1:1"], ["3:4", "3:4"], ["9:16", "9:16"], ["4:3", "4:3"], ["16:9", "16:9"]].map(([value, label]) => (
                <button type="button" key={value} className={`ratio-btn ${ratio === value ? "active" : ""}`} onClick={() => onRatioChange(value)}>{label}</button>
              ))}
            </div>
          </div>
          <div>
            <label className="field-label">创意程度</label>
            <div className="creativity-options">
              {["低", "中", "高"].map((level) => (
                <button type="button" key={level} className={`creativity-btn ${creativityLevel === level ? "active" : ""}`} onClick={() => onCreativityChange(level)}>{level}</button>
              ))}
            </div>
          </div>
        </div>
        <label className="field-label">素材图（可选）</label>
        <input ref={materialInputRef} type="file" accept="image/png,image/jpeg,image/webp" multiple hidden onChange={onMaterialSelect} />
        <div className={`material-upload-zone${materialPreviews.length ? " has-materials" : ""}`} onClick={materialPreviews.length ? undefined : onMaterialOpen}>
          {materialPreviews.length > 0 ? (
            <div className="material-preview-grid">
              {materialPreviews.map((url, index) => (
                <button
                  key={url}
                  type="button"
                  className="material-preview-item media-preview-trigger"
                  title="点击预览"
                  onClick={(event) => {
                    event.stopPropagation();
                    onPreviewMaterials?.(index);
                  }}
                >
                  <img src={url} alt={`素材 ${index + 1}`} />
                </button>
              ))}
              <button type="button" className="btn btn-xs" onClick={onMaterialOpen}>继续添加</button>
            </div>
          ) : (
            <span>🎨 点击上传素材图（直接传给模型，不反推提示词）</span>
          )}
        </div>
        <div className="generation-controls">
          <select value={genCount} onChange={(event) => onCountChange(Number(event.target.value))}>
            {[1, 2, 3, 4].map((count) => <option key={count} value={count}>{count} 张</option>)}
          </select>
          <button className="btn btn-primary" type="button" disabled={submitting || !canGenerate} onClick={onGenerate}>
            {submitting ? "提交中..." : generating ? "继续生成" : "生成图片"}
          </button>
        </div>
      </div>

      {(imageGroups.length > 0 || generating || submitting) && (
        <div className="image-result-panel">
          <h4>生成结果</h4>
          {referenceImages.length > 0 && (
            <p className="result-hint">已根据 {referenceImages.length} 张参考图生成，每张使用对应的 prompt</p>
          )}
          <div className="image-result-grid">
            {imageGroups.map((group, groupIndex) => (
              <div key={group.slotId} className="image-result-card">
                <div className="result-card-header">
                  <h5>图片 {groupIndex + 1}</h5>
                  {group.sourcePrompt && <span className="result-source-prompt" title={group.sourcePrompt}>{group.sourcePrompt.slice(0, 40)}...</span>}
                </div>
                <div className="result-variant-grid">
                  {referenceImages[groupIndex]?.url ? (
                    <button
                      type="button"
                      className="result-variant-card result-original-card media-preview-trigger"
                      title="预览原图"
                      onClick={() => onPreviewOriginal?.(referenceImages[groupIndex], groupIndex)}
                    >
                      <img src={referenceImages[groupIndex].url} alt={`图片 ${groupIndex + 1} 的原图`} />
                      <span className="variant-label">原图</span>
                    </button>
                  ) : null}
                  {(group.variants || []).map((variant, variantIndex) => (
                    <button
                      key={variant.variantId}
                      type="button"
                      className={`result-variant-card media-preview-trigger ${selectedVariants[group.slotId] === variant.variantId ? "selected" : ""}`}
                      title="点击预览 / 选中"
                      onClick={() => {
                        onSelectVariant(group.slotId, variant.variantId);
                        onPreview?.(variant, variantIndex, group, groupIndex);
                      }}
                    >
                      <img src={variant.url} alt={`变体 ${variantIndex + 1}`} />
                      <span className="variant-label">{`生成 ${variantIndex + 1}`}</span>
                    </button>
                  ))}
                </div>
                <div className="result-card-actions">
                  <button
                    className="btn btn-xs"
                    type="button"
                    onClick={() => {
                      if (onDownload) {
                        onDownload(group, groupIndex);
                        return;
                      }
                      const variant = group.variants?.find((item) => item.variantId === selectedVariants[group.slotId]) || group.variants?.[0];
                      if (variant?.url) downloadMedia(variant.url, `AI生图_${groupIndex + 1}.png`);
                    }}
                  >
                    ⬇️ 下载
                  </button>
                </div>
              </div>
            ))}
            {submitting && referenceImages.slice(imageGroups.length).map((image, index) => (
              <div key={`placeholder-${index}`} className="image-result-card placeholder-card">
                <div className="result-card-header"><h5>图片 {imageGroups.length + index + 1}</h5></div>
                <div className="image-placeholder">
                  <span className="btn-spinner" />
                  <p>生成中...</p>
                  {image.prompt && <p className="placeholder-prompt">{image.prompt.slice(0, 50)}...</p>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  </div>;
}
