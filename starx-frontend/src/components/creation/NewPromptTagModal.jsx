import { useEffect, useState } from "react";
import ModalOverlay from "../ModalOverlay";

export default function NewPromptTagModal({ open, category, onClose, onSubmit }) {
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    setName("");
    setPrompt("");
    setSubmitting(false);
  }, [open, category?.id]);

  if (!open || !category) return null;

  const close = () => {
    if (!submitting) onClose();
  };

  const submit = async (event) => {
    event.preventDefault();
    if (!name.trim() || !prompt.trim() || submitting) return;
    setSubmitting(true);
    try {
      const created = await onSubmit({
        id: `custom_${Date.now()}`,
        name: name.trim(),
        prompt: prompt.trim(),
        category: category.id,
        isCustom: true,
      });
      if (created !== false) onClose();
    } finally {
      setSubmitting(false);
    }
  };

  return <ModalOverlay>
    <form className="modal new-prompt-tag-modal" role="dialog" aria-modal="true" aria-labelledby="new-prompt-tag-title" onSubmit={submit}>
      <div className="new-prompt-tag-heading">
        <div>
          <span className="new-prompt-tag-kicker">新增标签</span>
          <h3 id="new-prompt-tag-title">添加到{category.label}</h3>
        </div>
        <button className="new-prompt-tag-close" type="button" aria-label="关闭新增标签弹窗" onClick={close} disabled={submitting}>×</button>
      </div>
      <div className="new-prompt-tag-category" style={{ "--category-color": category.color }}>
        <span>{category.emoji || "🏷️"}</span>
        <div><small>所属分类</small><strong>{category.label}</strong></div>
      </div>
      <label>
        <span className="field-label">标签名称 *</span>
        <input value={name} onChange={(event) => setName(event.target.value)} placeholder="如：赛博朋克" autoFocus disabled={submitting} />
      </label>
      <label>
        <span className="field-label">标签提示词 *</span>
        <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} rows={4} placeholder="输入该标签对应的 Prompt 内容…" disabled={submitting} />
      </label>
      <p className="new-prompt-tag-help">选中该标签后，这段提示词会自动加入图片生成描述。</p>
      <div className="modal-actions">
        <button className="btn" type="button" onClick={close} disabled={submitting}>取消</button>
        <button className="btn btn-primary" type="submit" disabled={!name.trim() || !prompt.trim() || submitting}>{submitting ? "创建中…" : "确认创建"}</button>
      </div>
    </form>
  </ModalOverlay>;
}
