import { downloadMedia } from "../../../utils/mediaLightbox";

const RATIOS = ["1:1", "3:4", "9:16", "4:3", "16:9"];

export default function KimLinkPromptStep({
  rows,
  ratio,
  submitting,
  onBack,
  onRowPromptChange,
  onRatioChange,
  onGenerate,
  onPreview,
}) {
  return <div className="wizard-step-content">
    <div className="wizard-step-nav"><button className="btn btn-sm" type="button" onClick={onBack}>← 更换链接</button></div>
    <div className="link-prompt-table-step">
      <div className="section-row"><div><h4>逐图反推提示词</h4><p className="muted">已解析 {rows.length} 张图片，最多支持前 8 张。每张图片都会使用对应提示词生成。</p></div></div>
      <div className="link-flow-table-wrap"><table className="link-flow-table prompt-table"><thead><tr><th>序号</th><th>图片</th><th>对应提示词</th></tr></thead><tbody>
        {rows.map((row, index) => (
          <tr key={row.id}>
            <td>{index + 1}</td>
            <td>
              <div className="link-flow-thumb-cell">
                {row.imageUrl ? (
                  <button
                    type="button"
                    className="link-flow-thumb media-preview-trigger"
                    title="点击预览"
                    onClick={() => onPreview?.(index)}
                  >
                    <img src={row.imageUrl} alt={`解析图片 ${index + 1}`} referrerPolicy="no-referrer" />
                  </button>
                ) : (
                  <div className="link-flow-thumb link-flow-thumb-empty">暂无图片</div>
                )}
                {row.imageUrl ? (
                  <button
                    type="button"
                    className="btn btn-xs"
                    onClick={() => downloadMedia(row.imageUrl, `starx-prompt-ref-${index + 1}.png`)}
                  >
                    ⬇️ 下载
                  </button>
                ) : null}
              </div>
            </td>
            <td>
              <textarea
                value={row.prompt}
                onChange={(event) => onRowPromptChange(row.id, event.target.value)}
                rows={6}
                placeholder="填写或修改这张图的生成提示词"
              />
            </td>
          </tr>
        ))}
      </tbody></table></div>
      <div className="prompt-advanced-grid link-flow-controls"><div><label className="field-label">图片比例</label><div className="ratio-options">{RATIOS.map((value) => <button type="button" key={value} className={`ratio-btn ${ratio === value ? "active" : ""}`} onClick={() => onRatioChange(value)}>{value}</button>)}</div></div></div>
      <button className="btn btn-primary full-btn" type="button" disabled={submitting || rows.length === 0} onClick={onGenerate}>{submitting ? "生成中..." : "下一步：生成图片"}</button>
    </div>
  </div>;
}
