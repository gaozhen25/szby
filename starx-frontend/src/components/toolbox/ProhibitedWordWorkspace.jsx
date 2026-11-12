export default function ProhibitedWordWorkspace({
  text,
  found,
  onTextChange,
  onDetect,
  onClear,
  onReplaceAll,
}) {
  return (
    <article className="glass-card toolbox-tool-card toolbox-workspace toolbox-workspace-check">
      <h2>🚫 违禁词批量检测</h2>
      <p className="muted">自动识别广告法违禁词、平台敏感词，一键替换合规表述</p>
      <textarea
        aria-label="待检测文案"
        rows="7"
        value={text}
        onChange={(event) => onTextChange(event.target.value)}
      />
      <div className="button-row">
        <button className="btn btn-primary" type="button" onClick={onDetect}>🔍 开始检测</button>
        <button className="btn" type="button" onClick={onClear}>清空</button>
      </div>
      <div className="toolbox-check-results" aria-live="polite">
        {found.map(([word, replacement]) => (
          <div className="kanban-card" key={word}>❌ <del>{word}</del> → ✅ {replacement}</div>
        ))}
      </div>
      {found.length ? (
        <button className="btn btn-primary" type="button" onClick={onReplaceAll}>
          🪄 一键自动替换
        </button>
      ) : null}
    </article>
  );
}
