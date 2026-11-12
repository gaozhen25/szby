import { downloadMedia } from "../../../utils/mediaLightbox";

export default function KimLinkResultStep({
  rows,
  groupsBySlot,
  selectedVariants,
  title,
  hashtags,
  copy,
  submitting,
  onBack,
  onTitleChange,
  onHashtagsChange,
  onCopyChange,
  onRegenerateAll,
  onRegenerateRow,
  onSelectVariant,
  onSave,
  onPreview,
}) {
  return <div className="wizard-step-content">
    <div className="wizard-step-nav"><button className="btn btn-sm" type="button" onClick={onBack}>← 修改提示词</button></div>
    <div className="link-result-table-step">
      <div className="section-row"><div><h4>生成图片结果</h4><p className="muted">每张图片都可以单独改写重新生成，改写会替换当前行结果。</p></div><button className="btn btn-primary" type="button" disabled={submitting || rows.length === 0} onClick={onRegenerateAll}>重新生成全部</button></div>
      <div className="link-publish-fields"><div><label className="field-label">链接标题 · AI 改写版</label><input value={title} onChange={(event) => onTitleChange(event.target.value)} /></div><div><label className="field-label">链接标签 · 原话题</label><input value={hashtags} onChange={(event) => onHashtagsChange(event.target.value)} /></div><div className="link-publish-copy"><label className="field-label">链接文案 · AI 改写版</label><textarea value={copy} onChange={(event) => onCopyChange(event.target.value)} rows={4} /></div></div>
      <div className="link-flow-table-wrap"><table className="link-flow-table result-table"><thead><tr><th>序号</th><th>图片</th></tr></thead><tbody>{rows.map((row, index) => {
        const group = groupsBySlot.get(row.id);
        const selectedId = selectedVariants[row.id];
        const variants = group?.variants || [];
        return (
          <tr key={row.id}>
            <td>{index + 1}</td>
            <td>
              <div className="link-generated-cell">
                <div className="link-generated-variants">
                  <div className="link-generated-variant link-generated-original">
                    <span className="link-generated-variant-label">原图</span>
                    <button
                      type="button"
                      className="link-generated-preview media-preview-trigger"
                      title="预览原图"
                      onClick={() => onPreview?.(index, 0)}
                    >
                      <img src={row.imageUrl} alt={`第 ${index + 1} 张原图`} />
                    </button>
                    <div className="link-generated-variant-actions">
                      <span className="link-original-badge">创作参考</span>
                      <button className="btn btn-xs" type="button" onClick={() => downloadMedia(row.imageUrl, `starx-original-${index + 1}.png`)}>⬇️ 下载</button>
                    </div>
                  </div>
                  {variants.length ? (
                    variants.map((image, variantIndex) => {
                      const selected = image.variantId === selectedId;
                      return <div className={`link-generated-variant${selected ? " is-selected" : ""}`} key={image.variantId || image.url}>
                        <span className="link-generated-variant-label">{variantIndex === 0 ? "生成结果 1" : `新生成 ${variantIndex + 1}`}</span>
                        <button
                          type="button"
                          className="link-generated-preview media-preview-trigger"
                          title="点击预览"
                          onClick={() => onPreview?.(index, variantIndex + 1)}
                        >
                          <img src={image.url} alt={`第 ${index + 1} 张图片的候选 ${variantIndex + 1}`} />
                        </button>
                        <div className="link-generated-variant-actions">
                          <button className="btn btn-xs" type="button" aria-pressed={selected} onClick={() => onSelectVariant?.(row.id, image.variantId)}>{selected ? "当前选用" : "选用此图"}</button>
                          <button className="btn btn-xs" type="button" onClick={() => onSave(row, image.url)}>保存</button>
                          <button className="btn btn-xs" type="button" onClick={() => downloadMedia(image.url, `starx-${index + 1}-${variantIndex + 1}.png`)}>⬇️ 下载</button>
                        </div>
                      </div>;
                    })
                  ) : <div className="link-generated-empty">暂无生成结果</div>}
                </div>
                <div className="link-generated-actions">
                  <button className="btn btn-xs btn-primary" type="button" onClick={() => onRegenerateRow(row)}>输入要求重新生成</button>
                </div>
              </div>
            </td>
          </tr>
        );
      })}</tbody></table></div>
    </div>
  </div>;
}
