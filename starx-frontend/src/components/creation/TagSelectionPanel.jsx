import { useMemo, useState } from "react";
import SelectedTagsPanel from "./SelectedTagsPanel";
import { TAG_CATEGORY_UI_CONFIG, getTagEmoji } from "../../config/tagCategoryUi";

const COLLAPSED_COUNT = 7;

function TagCategoryCard({ category, selectedTagIds, search, onToggle, onCreateTag }) {
  const [expanded, setExpanded] = useState(false);
  const ui = TAG_CATEGORY_UI_CONFIG[category.id] || { label: category.name, emoji: "🏷️", color: "#22D3EE", description: category.description };
  const matchingTags = useMemo(() => (category.tags || []).filter((tag) => !search || String(tag.name || "").toLowerCase().includes(search.toLowerCase())), [category.tags, search]);
  const selected = matchingTags.filter((tag) => selectedTagIds.includes(tag.id));
  const base = matchingTags.filter((tag) => !selectedTagIds.includes(tag.id));
  const visibleTags = expanded ? [...selected, ...base] : [...selected, ...base.slice(0, Math.max(0, COLLAPSED_COUNT - selected.length))];
  if (!matchingTags.length) return null;
  const hiddenCount = Math.max(0, matchingTags.length - visibleTags.length);
  return <article className={`creation-tag-category creation-tag-category-${category.id}`} style={{ "--category-color": ui.color }}>
    <div className="creation-category-info"><div className="creation-category-title"><span className="creation-category-emoji">{ui.emoji}</span><h4>{ui.label}</h4><button className="creation-add-tag" type="button" style={{ "--category-color": ui.color }} onClick={() => onCreateTag(category.id)} aria-label={`在${ui.label}下新增标签`}>＋ 新增</button></div><p>{ui.description || category.description}</p><span className="creation-category-count">{matchingTags.length} 个标签</span></div>
    <div className="creation-category-tags">{visibleTags.map((tag) => { const isSelected = selectedTagIds.includes(tag.id); return <button type="button" key={tag.id} className={`creation-tag-chip ${isSelected ? "selected" : ""}`} style={{ "--category-color": ui.color }} onClick={() => onToggle(tag.id)} title={tag.prompt?.slice(0, 100)} aria-pressed={isSelected}><span>{getTagEmoji(tag)}</span>{tag.name}{isSelected && <b aria-hidden="true">✓</b>}</button>; })}</div>
    {(hiddenCount > 0 || expanded) && <button className="creation-expand-tags" style={{ "--category-color": ui.color }} type="button" onClick={() => setExpanded((value) => !value)}>{expanded ? "收起" : `更多 ${hiddenCount}+`} <span className={expanded ? "up" : ""}>⌄</span></button>}
  </article>;
}

export default function TagSelectionPanel({ categories, selectedTagIds, onToggle, onCreateTag, onClear, onSkip, onNext, afterCategories = null }) {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const fixedCategories = (categories || []).filter((category) => ["purpose", "style", "scene", "quality"].includes(category.id));
  const visibleCategories = fixedCategories.filter((category) => filter === "all" || category.id === filter);
  const normalizedSearch = search.trim().toLowerCase();
  return <div className="creation-tag-selection">
    <SelectedTagsPanel categories={fixedCategories} selectedTagIds={selectedTagIds} onToggle={onToggle} onClear={onClear} />
    <div className="creation-tag-toolbar"><div className="creation-tag-search"><span>⌕</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索标签名称" aria-label="搜索标签名称" />{search && <button type="button" onClick={() => setSearch("")} aria-label="清空搜索">×</button>}</div><div className="creation-tag-filter" role="tablist" aria-label="标签分类筛选"><button type="button" className={filter === "all" ? "active" : ""} onClick={() => setFilter("all")}>全部</button>{fixedCategories.map((category) => { const ui = TAG_CATEGORY_UI_CONFIG[category.id]; return <button type="button" key={category.id} className={filter === category.id ? "active" : ""} style={{ "--category-color": ui?.color }} onClick={() => setFilter(category.id)}>{ui?.emoji} {ui?.label || category.name}</button>; })}</div></div>
    <div className="creation-category-list">{visibleCategories.map((category) => <TagCategoryCard category={category} selectedTagIds={selectedTagIds} search={normalizedSearch} onToggle={onToggle} onCreateTag={onCreateTag} key={category.id} />)}{!visibleCategories.some((category) => (category.tags || []).some((tag) => !normalizedSearch || String(tag.name || "").toLowerCase().includes(normalizedSearch))) && <div className="creation-tag-no-results">没有匹配的标签</div>}</div>
    {afterCategories}
    <div className="creation-tag-next"><button className="btn" type="button" onClick={onSkip}>跳过标签</button><button className="btn btn-primary" type="button" onClick={onNext}>下一步 →</button></div>
  </div>;
}
