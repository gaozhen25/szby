const PROMPT_EXAMPLES = ["🌺 花瓣柔光", "💎 高端护肤品", "🌃 城市夜景"];

export default function AiImageWorkspace({
  app,
  message,
  messages,
  onMessageChange,
  onSend,
  onReset,
}) {
  const materials = Array.isArray(app.materials) ? app.materials.slice(0, 8) : [];

  return (
    <section className="tool-layout toolbox-image-layout toolbox-workspace toolbox-workspace-ai">
      <aside className="glass-card tool-panel">
        <h3>参考图</h3>
        <button
          type="button"
          className="upload-zone toolbox-upload-action"
          onClick={() => app.addToast("参考图已上传，已自动反推提示词")}
        >
          <span aria-hidden="true">＋</span>
          上传参考图
        </button>
        <div className="tool-list toolbox-prompt-examples">
          {PROMPT_EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => onMessageChange(example.replace(/^\S+\s*/, ""))}
            >
              {example}
            </button>
          ))}
        </div>
      </aside>

      <section className="glass-card chat-panel toolbox-chat">
        <div className="section-row">
          <div>
            <h2>AI 对话生图</h2>
            <p className="muted">像和设计师聊天一样描述画面</p>
          </div>
          <button className="btn btn-xs" type="button" onClick={onReset}>＋ 新对话</button>
        </div>
        <div className="chat-messages" aria-live="polite">
          {messages.map((item, index) => (
            <div className={`chat-bubble ${item.role}`} key={`${item.role}-${index}`}>
              {item.text}
            </div>
          ))}
        </div>
        <form
          className="chat-input toolbox-chat-input"
          onSubmit={(event) => {
            event.preventDefault();
            onSend();
          }}
        >
          <input
            aria-label="生图描述"
            value={message}
            onChange={(event) => onMessageChange(event.target.value)}
            placeholder="描述你想要的画面…"
          />
          <button className="btn btn-primary" type="submit">发送</button>
        </form>
      </section>

      <aside className="glass-card tool-panel">
        <h3>🗂️ 素材库</h3>
        <div className="tool-list">
          {materials.length ? materials.map((material) => (
            <button
              key={material.id}
              type="button"
              onClick={() => app.addToast(`已关联素材：${material.name}`)}
            >
              {material.thumb} {material.name.slice(0, 12)}
            </button>
          )) : <p className="muted">暂无可关联素材</p>}
        </div>
      </aside>
    </section>
  );
}
