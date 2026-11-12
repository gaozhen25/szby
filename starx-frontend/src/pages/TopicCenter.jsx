import { useEffect, useMemo, useState } from "react";

import CreationPreferenceModal from "../components/CreationPreferenceModal";
import LoadingOverlay from "../components/creation/LoadingOverlay";
import { submitTopicCreation } from "../utils/topicCreationHandoff";
import "../styles/topic-center.css";

const normalizeTopicMetaText = (value) => {
  if (!(typeof value === "string" || typeof value === "number")) return "";
  return String(value).trim();
};

const formatTopicReason = (topic) => {
  const reason = normalizeTopicMetaText(topic?.reason);
  const contentId = normalizeTopicMetaText(topic?.referenceNote?.contentId);
  if (!reason || !contentId || !reason.includes(contentId)) return reason;

  const referenceTitle = normalizeTopicMetaText(topic?.referenceNote?.title);
  const readableReference = referenceTitle ? `爆款笔记《${referenceTitle}》` : "参考爆款笔记";
  const escapedId = contentId.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const labeledReference = new RegExp(`(?:爆款|参考)?笔记\\s*(?:id|编号)?\\s*[:：#]?\\s*${escapedId}`, "gi");
  const sanitized = reason.replace(labeledReference, readableReference);
  return sanitized.split(contentId).join(referenceTitle ? `《${referenceTitle}》` : "该参考笔记");
};

const PLATFORM_EMOJI = {
  抖音: "🎵",
  小红书: "📕",
  快手: "⚡",
  视频号: "💬",
  B站: "📺",
  bilibili: "📺",
  微博: "📢",
};

const FILTER_OPTIONS = [
  { id: "全部", label: "✨ 全部" },
  { id: "抄爆", label: "🔥 抄爆" },
  { id: "原创", label: "💡 原创" },
  { id: "视频", label: "🎬 视频" },
  { id: "图文", label: "🖼️ 图文" },
  { id: "抖音", label: "🎵 抖音" },
  { id: "小红书", label: "📕 小红书" },
];

const META_EMOJI = {
  抄爆: "🔥",
  原创: "💡",
  热点: "📈",
  种草: "🛒",
  干货: "📚",
  日常: "☕",
};

const PAGE_SIZE = 6;

const platformLabelWithEmoji = (platform) => {
  const name = normalizeTopicMetaText(platform);
  if (!name) return "";
  const emoji = PLATFORM_EMOJI[name] || "📱";
  return name.includes(emoji) ? name : `${emoji} ${name}`;
};

const metaLabelWithEmoji = (value) => {
  const text = normalizeTopicMetaText(value);
  if (!text) return "";
  const emoji = META_EMOJI[text];
  return emoji && !text.includes(emoji) ? `${emoji} ${text}` : text;
};

const recommendStars = (topic) => {
  const raw = Number(topic?.score ?? topic?.heat ?? topic?.recommendScore ?? topic?.recommend_score);
  if (Number.isFinite(raw) && raw > 0) {
    const stars = Math.max(1, Math.min(5, Math.round(raw <= 5 ? raw : raw / 20)));
    return "⭐".repeat(stars);
  }
  const seed = String(topic?.id || topic?.title || "topic");
  let hash = 0;
  for (let i = 0; i < seed.length; i += 1) hash = (hash * 31 + seed.charCodeAt(i)) >>> 0;
  return "⭐".repeat(3 + (hash % 3));
};

const resolveImageReferenceNote = (topic) => {
  const referenceNote = topic?.referenceNote;
  if (topic?.type !== "image" || !referenceNote || typeof referenceNote !== "object") return null;
  if (referenceNote.contentType !== "image" || !normalizeTopicMetaText(referenceNote.publicUrl)) return null;
  return referenceNote;
};

function TopicReferenceNote({ note, expanded, onToggle }) {
  const reason = normalizeTopicMetaText(note?.selectionReason);
  const title = normalizeTopicMetaText(note?.title);
  if (!title) return null;

  return (
    <div className={`topic-reference-note ${expanded ? "is-expanded" : "is-collapsed"}`}>
      <div className="topic-reference-head">
        <span className="topic-reference-label">🔥 参考爆款</span>
        <button
          type="button"
          className="topic-reference-toggle"
          aria-expanded={expanded}
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            onToggle();
          }}
        >
          {expanded ? "收起" : "展开"}
        </button>
      </div>
      {expanded ? (
        <>
          {note.publicUrl ? (
            <a
              className="topic-reference-title"
              href={note.publicUrl}
              target="_blank"
              rel="noreferrer"
              title={title}
            >
              {title}
            </a>
          ) : (
            <strong className="topic-reference-title" title={title}>{title}</strong>
          )}
          {reason ? <small className="topic-reference-reason">{reason}</small> : null}
        </>
      ) : null}
    </div>
  );
}

export default function TopicCenter({ app }) {
  const [activeView, setActiveView] = useState("recommended");
  const [activeFilter, setActiveFilter] = useState("全部");
  const [currentPage, setCurrentPage] = useState(1);
  const [selectedTopic, setSelectedTopic] = useState(null);
  const [retryPreferences, setRetryPreferences] = useState(null);
  const [isCreating, setIsCreating] = useState(false);
  const [pendingFavoriteIds, setPendingFavoriteIds] = useState(() => new Set());
  const [expandedReferenceIds, setExpandedReferenceIds] = useState(() => new Set());
  const favoriteTopics = app.favoriteTopics || [];
  const favoriteSourceKeys = useMemo(
    () => new Set(favoriteTopics.map((topic) => `${topic.sourceTopicId}::${topic.sourceBatchId || ""}`)),
    [favoriteTopics],
  );

  const toggleReferenceExpanded = (topicId) => {
    setExpandedReferenceIds((prev) => {
      const next = new Set(prev);
      if (next.has(topicId)) next.delete(topicId);
      else next.add(topicId);
      return next;
    });
  };

  const resolveImageTargetPlatform = (topic) => {
    const configured = app.currentAccount?.platforms?.length
      ? app.currentAccount.platforms
      : [app.currentAccount?.platform].filter(Boolean);
    return (topic.platforms || []).find((platform) => configured.includes(platform))
      || configured[0]
      || topic.platforms?.[0]
      || "小红书";
  };

  const createFromTopic = async (topic, preferences) => {
    if (!topic || isCreating) return;
    setIsCreating(true);
    try {
      await submitTopicCreation({
        topic,
        preferences,
        generateCreation: app.generateCreation,
        onSuccess: () => {
          setRetryPreferences(null);
          setSelectedTopic(null);
        },
        onFailure: (error) => {
          setRetryPreferences(preferences);
          app.addToast(`${error?.message || "创建创作内容失败"}，请重试`, "warning");
        },
      });
    } finally {
      setIsCreating(false);
    }
  };

  const openCreationPreferences = (topic) => {
    setRetryPreferences(null);
    setSelectedTopic(topic);
    if (topic.type !== "video") {
      void createFromTopic(topic, { targetPlatform: resolveImageTargetPlatform(topic) });
    }
  };

  const closeCreationPreferences = () => {
    if (isCreating) return;
    setRetryPreferences(null);
    setSelectedTopic(null);
  };

  const confirmCreation = async (preferences) => {
    await createFromTopic(selectedTopic, preferences);
  };

  const matchesFilter = (topic) => {
    if (activeFilter === "全部") return true;
    if (activeFilter === "视频") return topic.type === "video";
    if (activeFilter === "图文") return topic.type !== "video";
    if (activeFilter === "抖音" || activeFilter === "小红书") {
      return Array.isArray(topic.platforms) && topic.platforms.includes(activeFilter);
    }
    if (activeFilter === "抄爆" || activeFilter === "原创") {
      if (activeFilter === "抄爆") return Boolean(resolveImageReferenceNote(topic));
      return topic.source === activeFilter || topic.category === activeFilter;
    }
    return true;
  };

  const visibleTopics = activeView === "favorites" ? favoriteTopics : app.topics;
  const filteredTopics = visibleTopics.filter(matchesFilter);
  const totalPages = Math.max(1, Math.ceil(filteredTopics.length / PAGE_SIZE));
  const pagedTopics = filteredTopics.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  useEffect(() => {
    if (currentPage > totalPages) setCurrentPage(totalPages);
  }, [currentPage, totalPages]);

  const handleFilterChange = (f) => {
    setActiveFilter(f);
    setCurrentPage(1);
  };

  const handleViewChange = (view) => {
    setActiveView(view);
    setActiveFilter("全部");
    setCurrentPage(1);
  };

  const withPendingFavorite = async (id, action) => {
    setPendingFavoriteIds((prev) => new Set(prev).add(id));
    try {
      await action();
    } catch (error) {
      app.addToast(error?.message || "收藏操作失败，请重试", "warning");
    } finally {
      setPendingFavoriteIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  };

  const card = (topic, favorite = false) => {
    const platforms = Array.isArray(topic.platforms) ? topic.platforms.map(normalizeTopicMetaText).filter(Boolean) : [];
    const reason = formatTopicReason(topic);
    const stars = recommendStars(topic);
    const referenceNote = resolveImageReferenceNote(topic);
    const sourceKey = `${topic.id}::${topic.batchId || ""}`;
    const isFavorited = !favorite && favoriteSourceKeys.has(sourceKey);
    const favoritePending = pendingFavoriteIds.has(topic.id);
    return (
      <article className={`glass-card topic-card ${favorite ? "topic-card-favorite" : ""}`} key={topic.id}>
        <span className="type badge">{topic.type === "video" ? "🎬 视频" : "🖼️ 图文"}</span>
        <div className="topic-score" title="推荐指数">{stars}</div>
        <h3>{topic.title}</h3>
        {favorite && topic.collectedAt ? (
          <div className="topic-collected-at">♡ 收藏于 {new Date(topic.collectedAt).toLocaleDateString("zh-CN")}</div>
        ) : null}
        <div className="topic-meta">
          {referenceNote ? <span className="tmt topic-copy-hit-tag">🔥 抄爆</span> : null}
          {metaLabelWithEmoji(topic.source) ? <span className="tmt">{metaLabelWithEmoji(topic.source)}</span> : null}
          {metaLabelWithEmoji(topic.category) ? <span className="tmt">{metaLabelWithEmoji(topic.category)}</span> : null}
        </div>
        {platforms.length ? (
          <div className="topic-platforms">
            {platforms.map((platform, index) => (
              <span className="tmt platform-chip" key={`${platform}-${index}`}>{platformLabelWithEmoji(platform)}</span>
            ))}
          </div>
        ) : null}
        {reason ? <p className="topic-reason">{reason}</p> : null}
        {referenceNote?.title ? (
          <TopicReferenceNote
            note={referenceNote}
            expanded={expandedReferenceIds.has(topic.id)}
            onToggle={() => toggleReferenceExpanded(topic.id)}
          />
        ) : null}
        <div className="topic-actions">
          {favorite ? (
            <button
              className="btn btn-sm btn-ghost topic-delete-favorite"
              disabled={favoritePending}
              onClick={() => void withPendingFavorite(topic.id, () => app.deleteFavoriteTopic(topic.id))}
            >
              {favoritePending ? "删除中..." : "删除收藏"}
            </button>
          ) : (
            <button
              className={`btn btn-sm btn-ghost topic-favorite-button ${isFavorited ? "is-favorited" : ""}`}
              disabled={favoritePending}
              aria-pressed={isFavorited}
              onClick={() => {
                if (isFavorited) handleViewChange("favorites");
                else void withPendingFavorite(topic.id, () => app.favoriteTopic(topic.id));
              }}
            >
              {favoritePending ? "收藏中..." : isFavorited ? "♥ 已收藏" : "♡ 收藏"}
            </button>
          )}
          <button className="btn btn-create" onClick={() => openCreationPreferences(topic)}>✨ 去创作</button>
        </div>
      </article>
    );
  };

  return (
    <div className="topic-page topic-ux-shell">
      {isCreating || app.isRefreshingTopics ? (
        <LoadingOverlay
          contained
          message={app.isRefreshingTopics && !isCreating
            ? "正在生成新一批选题..."
            : selectedTopic?.type === "video"
              ? "正在生成视频脚本..."
              : resolveImageReferenceNote(selectedTopic)
                ? "正在解析参考爆款..."
                : "正在进入 AI 图文创作..."}
          subMessage={app.isRefreshingTopics && !isCreating
            ? "AI 正在结合账号报告、用户画像和参考笔记分析，请稍候"
            : selectedTopic?.type === "video"
              ? "脚本生成完成后将自动进入创作页面"
              : resolveImageReferenceNote(selectedTopic)
                ? "正在提取爆款原图，完成后将进入解析结果页面"
                : "无需参考笔记，AI 将根据选题和账号信息生成生图提示词"}
        />
      ) : null}

      <div className="section-header topic-ux-header">
        <div>
          <h2>选题中心 · <span className="hl">{app.currentAccount?.name}</span></h2>
          <p className="topic-page-subtitle">把值得继续打磨的灵感留下来，换一批也不会丢失</p>
        </div>
        <div className="button-row topic-ux-actions">
          {activeView === "recommended" ? (
            <button className="btn btn-primary" onClick={app.refreshTopics} disabled={app.isRefreshingTopics}>
              {app.isRefreshingTopics ? "AI 分析中" : "🔄 换一批选题"}
            </button>
          ) : null}
        </div>
      </div>

      <div className="topic-view-tabs" role="tablist" aria-label="选题视图">
        <button
          type="button"
          role="tab"
          aria-selected={activeView === "recommended"}
          className={activeView === "recommended" ? "active" : ""}
          onClick={() => handleViewChange("recommended")}
        >
          推荐选题 <span>{app.topics.length}</span>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeView === "favorites"}
          className={activeView === "favorites" ? "active" : ""}
          onClick={() => handleViewChange("favorites")}
        >
          ♥ 我的收藏 <span>{favoriteTopics.length}</span>
        </button>
      </div>

      <div className="view-toggle-group topic-ux-filters topic-filter-row">
        {FILTER_OPTIONS.map((f) => (
          <button
            key={f.id}
            className={`pill ${activeFilter === f.id ? "active" : ""}`}
            onClick={() => handleFilterChange(f.id)}
          >
            {f.label}
          </button>
        ))}
      </div>

      <div className="topic-stats" aria-label="选题统计">
        <div className="topic-stat">
          ⭐ 今日推荐 <strong className="topic-stat-value">{app.topics.length}</strong>
        </div>
        <div className="topic-stat">
          ♥ 已收藏 <strong className="topic-stat-value">{favoriteTopics.length}</strong>
        </div>
        <div className="topic-stat">
          ✏ 已创作 <strong className="topic-stat-value">{app.dashboard?.creation ?? 0}</strong>
        </div>
      </div>

      <div className="topic-grid topic-ux-grid">
        {pagedTopics.map((topic) => card(topic, activeView === "favorites"))}
      </div>

      {!filteredTopics.length ? (
        <div className="topic-empty-state">
          <div className="topic-empty-icon">{activeView === "favorites" ? "♡" : "✦"}</div>
          <h3>{activeView === "favorites" ? "还没有收藏选题" : "没有符合筛选条件的选题"}</h3>
          <p>{activeView === "favorites" ? "看到喜欢的选题就点一下收藏，之后换批次也能在这里找到。" : "试试切换筛选条件，或让 AI 生成一批新选题。"}</p>
          {activeView === "favorites" ? (
            <button className="btn btn-primary" onClick={() => handleViewChange("recommended")}>去发现选题</button>
          ) : null}
        </div>
      ) : null}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="pagination-row" style={{ marginTop: "var(--space-2xl)" }}>
          <span className="muted">
            共 {filteredTopics.length} 条 · 第 {currentPage} / {totalPages} 页
          </span>
          <div className="button-row">
            <button className="btn btn-sm" disabled={currentPage <= 1} onClick={() => setCurrentPage(currentPage - 1)}>上一页</button>
            <button className="btn btn-sm" disabled={currentPage >= totalPages} onClick={() => setCurrentPage(currentPage + 1)}>下一页</button>
          </div>
        </div>
      )}

      {selectedTopic?.type === "video" && !isCreating ? (
        <CreationPreferenceModal
          variant="video"
          topic={selectedTopic}
          account={app.currentAccount}
          initialPreferences={retryPreferences}
          isSubmitting={isCreating}
          onCancel={closeCreationPreferences}
          onConfirm={confirmCreation}
        />
      ) : null}
    </div>
  );
}
