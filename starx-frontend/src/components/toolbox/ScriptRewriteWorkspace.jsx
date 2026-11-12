export default function ScriptRewriteWorkspace({
  app,
  videoLink,
  rewriteRequest,
  onVideoLinkChange,
  onRewriteRequestChange,
}) {
  return (
    <article className="glass-card toolbox-tool-card toolbox-workspace toolbox-workspace-script">
      <h2>📝 视频脚本改写</h2>
      <p className="muted">粘贴视频来源并描述改写方向</p>
      <label>
        <span>视频链接</span>
        <input
          value={videoLink}
          onChange={(event) => onVideoLinkChange(event.target.value)}
          placeholder="粘贴视频链接（模拟）"
        />
      </label>
      <label>
        <span>改写要求</span>
        <textarea
          rows="5"
          value={rewriteRequest}
          onChange={(event) => onRewriteRequestChange(event.target.value)}
          placeholder="描述改写需求…"
        />
      </label>
      <button
        className="btn btn-primary"
        type="button"
        onClick={() => app.addToast("脚本改写完成！", "success")}
      >
        ✨ 开始改写
      </button>
      <div className="kanban-card toolbox-script-result">
        <strong>📜 改写结果</strong>
        <span>镜头1：闹钟特写 + 城市延时</span>
        <span>镜头2：快速动作展示</span>
        <span>镜头3：产品特写与互动引导</span>
      </div>
    </article>
  );
}
