import { TAG_CATEGORY_UI_CONFIG, getTagEmoji } from "../../config/tagCategoryUi";

export default function SelectedTagsPanel({ categories, selectedTagIds, onToggle, onClear }) {
  const selectedTags = categories.flatMap((category) => (category.tags || []).map((tag) => ({ ...tag, categoryId: category.id }))).filter((tag) => selectedTagIds.includes(tag.id));
  return <section className="creation-selected-tags" aria-label="已选标签">
    <div className="creation-selected-heading"><div><span className="creation-pin">📌</span><strong>已选标签</strong><span className="creation-selected-count">{selectedTags.length}</span></div>{selectedTags.length > 0 && <button className="creation-clear-tags" type="button" onClick={onClear}>清空全部</button>}</div>
    <div className="creation-selected-list">{selectedTags.length ? selectedTags.map((tag) => { const ui = TAG_CATEGORY_UI_CONFIG[tag.categoryId] || {}; return <button className="creation-selected-chip" style={{ "--tag-color": ui.color }} key={`${tag.categoryId}-${tag.id}`} type="button" onClick={() => onToggle(tag.id)} title={`取消选择 ${tag.name}`}><span>{getTagEmoji(tag)}</span>{tag.name}<b>×</b></button>; }) : <span className="creation-selected-empty">还没有选择标签，从下方分类中选择适合的标签</span>}</div>
  </section>;
}
