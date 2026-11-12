import { useEffect, useRef, useState } from "react";

function formatUpdatedAt(value) {
  if (!value) return "暂无更新时间";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "更新时间未知";
  return `更新于 ${date.toLocaleDateString("zh-CN")}`;
}

export default function KnowledgeBaseManager({ app, onCreate, onBusyChange }) {
  const knowledgeBaseList = app.knowledgeBaseList || [];
  const knowledgeBasePage = app.knowledgeBasePage || {
    page: 1,
    pageSize: 12,
    total: knowledgeBaseList.length,
    keyword: "",
  };
  const [keyword, setKeyword] = useState(knowledgeBasePage.keyword || "");
  const [deletingId, setDeletingId] = useState("");
  const deletingRef = useRef("");
  const totalPages = Math.max(
    1,
    Math.ceil((knowledgeBasePage.total || 0) / (knowledgeBasePage.pageSize || 12))
  );

  useEffect(() => {
    setKeyword(knowledgeBasePage.keyword || "");
  }, [knowledgeBasePage.keyword]);

  const loadPage = (page, nextKeyword = knowledgeBasePage.keyword || "") => {
    app.loadKnowledgeBasesPage?.({
      page,
      pageSize: knowledgeBasePage.pageSize || 12,
      keyword: nextKeyword,
    });
  };

  const search = (event) => {
    event.preventDefault();
    if (deletingRef.current) return;
    loadPage(1, keyword.trim());
  };

  const confirmDelete = async (knowledgeBase) => {
    if (deletingRef.current) return;
    if (!window.confirm(`确认删除知识库「${knowledgeBase.name || "未命名知识库"}」？已关联账号的知识库需要先解绑。`)) return;

    deletingRef.current = knowledgeBase.id;
    setDeletingId(knowledgeBase.id);
    onBusyChange(true);
    try {
      await app.deleteKnowledgeBase(knowledgeBase);
    } finally {
      deletingRef.current = "";
      setDeletingId("");
      onBusyChange(false);
    }
  };

  return (
    <section className="knowledge-library-shell" aria-labelledby="knowledge-library-heading">
      <header className="knowledge-library-header">
        <div>
          <span className="knowledge-library-kicker">KNOWLEDGE LIBRARY</span>
          <h3 id="knowledge-library-heading">品牌知识库</h3>
          <p>集中维护品牌资料，账号绑定后会在真实内容链路中使用。</p>
        </div>
        <button
          className="btn btn-primary"
          type="button"
          disabled={Boolean(deletingId)}
          onClick={onCreate}
        >
          + 新建知识库
        </button>
      </header>

      <form className="knowledge-library-search" onSubmit={search}>
        <label className="sr-only" htmlFor="knowledge-library-search">搜索知识库或产品名称</label>
        <input
          id="knowledge-library-search"
          data-autofocus
          value={keyword}
          disabled={Boolean(deletingId)}
          onChange={(event) => setKeyword(event.target.value)}
          placeholder="搜索知识库或产品名称"
        />
        <button className="btn btn-sm" type="submit" disabled={Boolean(deletingId) || app.knowledgeBaseLoading}>
          搜索
        </button>
      </form>

      <div className="knowledge-library-list" aria-live="polite">
        {app.knowledgeBaseLoading ? (
          <div className="knowledge-library-state">
            <span className="knowledge-library-spinner" aria-hidden="true" />
            <p>正在加载知识库…</p>
          </div>
        ) : null}

        {!app.knowledgeBaseLoading && knowledgeBaseList.length === 0 ? (
          <div className="knowledge-library-state">
            <span className="knowledge-library-empty-icon" aria-hidden="true">▣</span>
            <strong>{knowledgeBasePage.keyword ? "没有匹配的知识库" : "暂未创建知识库"}</strong>
            <p>{knowledgeBasePage.keyword ? "换一个关键词后重新搜索。" : "点击右上角新建你的第一份品牌资料。"}</p>
          </div>
        ) : null}

        {!app.knowledgeBaseLoading && knowledgeBaseList.map((knowledgeBase) => {
          const imageCount = (knowledgeBase.imageMaterials || []).filter((item) => item?.trim()).length;
          const isDeleting = deletingId === knowledgeBase.id;

          return (
            <article className="knowledge-library-item" key={knowledgeBase.id}>
              <div className="knowledge-library-mark" aria-hidden="true">▣</div>
              <div className="knowledge-library-info">
                <strong>{knowledgeBase.name || "未命名知识库"}</strong>
                <span>
                  {knowledgeBase.productName || "未设置产品名称"} · {knowledgeBase.industry || "品牌资料"}
                </span>
                <small>{imageCount} 条图片素材 · {formatUpdatedAt(knowledgeBase.updatedAt)}</small>
              </div>
              <div className="knowledge-library-actions">
                <button
                  className="btn btn-sm"
                  type="button"
                  disabled={Boolean(deletingId)}
                  onClick={() => app.openKnowledgeBaseModal(knowledgeBase)}
                >
                  编辑
                </button>
                <button
                  className="btn btn-sm btn-danger"
                  type="button"
                  disabled={Boolean(deletingId)}
                  onClick={() => confirmDelete(knowledgeBase)}
                >
                  {isDeleting ? "删除中…" : "删除"}
                </button>
              </div>
            </article>
          );
        })}
      </div>

      <footer className="pagination-row knowledge-library-pagination">
        <span className="muted">
          共 {knowledgeBasePage.total || 0} 个 · 第 {knowledgeBasePage.page} / {totalPages} 页
        </span>
        <div className="button-row">
          <button
            className="btn btn-sm"
            type="button"
            disabled={knowledgeBasePage.page <= 1 || app.knowledgeBaseLoading || Boolean(deletingId)}
            onClick={() => loadPage(knowledgeBasePage.page - 1)}
          >
            上一页
          </button>
          <button
            className="btn btn-sm"
            type="button"
            disabled={knowledgeBasePage.page >= totalPages || app.knowledgeBaseLoading || Boolean(deletingId)}
            onClick={() => loadPage(knowledgeBasePage.page + 1)}
          >
            下一页
          </button>
        </div>
      </footer>
    </section>
  );
}
