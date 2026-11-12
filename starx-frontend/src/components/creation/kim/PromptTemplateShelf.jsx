import { useMemo, useState } from "react";
import { DEFAULT_IMAGE_RATIO } from "../../../utils/imageAspectRatio";

const templateSummary = (template) => {
  const prompt = String(template.previewPrompt || template.prompt || "").trim();
  return prompt || (template.selectedTagIds?.length ? `包含 ${template.selectedTagIds.length} 个提示词标签` : "空白提示词模板");
};

export default function PromptTemplateShelf({ templates = [], activeTemplateId = "", onApply }) {
  const [search, setSearch] = useState("");
  const filteredTemplates = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    if (!keyword) return templates;
    return templates.filter((template) => [template.name, template.description, template.previewPrompt, template.prompt]
      .some((value) => String(value || "").toLowerCase().includes(keyword)));
  }, [search, templates]);

  return <section className="prompt-template-shelf" aria-labelledby="prompt-template-shelf-title">
    <div className="prompt-template-shelf-heading">
      <div>
        <span className="prompt-template-kicker">PROMPT TEMPLATES</span>
        <h3 id="prompt-template-shelf-title">从提示词模板开始</h3>
        <p>一键恢复提示词、标签和生成参数，也可以继续微调。</p>
      </div>
      {templates.length > 3 ? <label className="prompt-template-search">
        <span aria-hidden="true">⌕</span>
        <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索模板" aria-label="搜索提示词模板" />
      </label> : null}
    </div>

    {templates.length === 0 ? <div className="prompt-template-empty">
      <span aria-hidden="true">✦</span>
      <div><strong>还没有提示词模板</strong><p>完成提示词编辑后，可在下一步保存常用组合。</p></div>
    </div> : filteredTemplates.length === 0 ? <div className="prompt-template-empty"><div><strong>没有匹配的模板</strong><p>换个关键词试试。</p></div></div> : <div className="prompt-template-grid">
      {filteredTemplates.map((template) => {
        const active = activeTemplateId === template.id;
        return <button
          className={`prompt-template-option ${active ? "active" : ""}`}
          type="button"
          key={template.id}
          onClick={() => onApply(template)}
          aria-pressed={active}
        >
          <span className="prompt-template-option-icon" aria-hidden="true">✦</span>
          <span className="prompt-template-option-content">
            <strong>{template.name}</strong>
            <small>{template.description || templateSummary(template)}</small>
            <span>{template.selectedTagIds?.length || 0} 个标签 · {template.params?.ratio || DEFAULT_IMAGE_RATIO}</span>
          </span>
          <span className="prompt-template-apply">{active ? "已应用 ✓" : "应用"}</span>
        </button>;
      })}
    </div>}
  </section>;
}
