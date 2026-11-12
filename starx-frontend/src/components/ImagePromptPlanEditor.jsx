const ROLE_LABELS = {
  cover: "封面",
  content: "内容页",
  ending: "收尾页",
  standalone: "独立图",
};

export default function ImagePromptPlanEditor({
  plan,
  disabled = false,
  onPlanFieldChange,
  onCardChange,
  onMoveCard,
  onRemoveCard,
  onAddCard,
}) {
  if (!plan?.cards?.length) return null;
  const isSeries = plan.collectionMode === "series";

  return (
    <section className="image-prompt-plan-editor">
      <div className="image-prompt-plan-heading">
        <div>
          <h3>图片 Prompt 计划</h3>
          <p>逐张检查并修改，确认后再生成图片。</p>
        </div>
        <span className="badge">{isSeries ? "系列图" : "独立图"} · {plan.cards.length} 张</span>
      </div>

      {isSeries && (
        <label className="image-plan-shared-style">
          <span className="field-label">系列共享视觉约束</span>
          <textarea
            rows={3}
            value={plan.sharedStyle}
            disabled={disabled}
            onChange={(event) => onPlanFieldChange("sharedStyle", event.target.value)}
            placeholder="统一人物、色彩、光线、构图和文字安全区"
          />
        </label>
      )}

      <div className="image-prompt-card-list">
        {plan.cards.map((card, index) => (
          <article className="image-prompt-card" key={card.slotId}>
            <div className="image-prompt-card-header">
              <strong>{ROLE_LABELS[card.role] || "图片"} {index + 1}</strong>
              <div className="image-prompt-card-actions">
                <button type="button" className="btn btn-xs" disabled={disabled || index === 0} onClick={() => onMoveCard(index, index - 1)}>上移</button>
                <button type="button" className="btn btn-xs" disabled={disabled || index === plan.cards.length - 1} onClick={() => onMoveCard(index, index + 1)}>下移</button>
                <button type="button" className="btn btn-xs btn-danger" disabled={disabled || plan.cards.length === 1} onClick={() => onRemoveCard(index)}>移除</button>
              </div>
            </div>
            <label>
              <span className="field-label">卡片标题</span>
              <input value={card.title} disabled={disabled} onChange={(event) => onCardChange(index, "title", event.target.value)} />
            </label>
            <label>
              <span className="field-label">生图 Prompt</span>
              <textarea rows={5} value={card.prompt} disabled={disabled} onChange={(event) => onCardChange(index, "prompt", event.target.value)} />
            </label>
          </article>
        ))}
      </div>

      {plan.cards.length < 4 && (
        <button type="button" className="btn btn-sm image-prompt-add-card" disabled={disabled} onClick={onAddCard}>＋ 添加一张</button>
      )}

      <div className="image-plan-metadata-grid">
        <label>
          <span className="field-label">负向提示词</span>
          <textarea rows={2} value={plan.negativePrompt} disabled={disabled} onChange={(event) => onPlanFieldChange("negativePrompt", event.target.value)} />
        </label>
        <label>
          <span className="field-label">发布文案</span>
          <textarea rows={2} value={plan.publishCopy} disabled={disabled} onChange={(event) => onPlanFieldChange("publishCopy", event.target.value)} />
        </label>
        <label>
          <span className="field-label">话题标签</span>
          <input value={(plan.hashtags || []).join(" ")} disabled={disabled} onChange={(event) => onPlanFieldChange("hashtags", event.target.value.split(/\s+/u).filter(Boolean))} />
        </label>
      </div>
    </section>
  );
}
