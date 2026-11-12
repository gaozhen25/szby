import { useState } from "react";

import DigitalHumanEnrollmentPanel from "../components/digital-human/DigitalHumanEnrollmentPanel";
import DigitalHumanProfileGrid from "../components/digital-human/DigitalHumanProfileGrid";
import "../styles/account-profile.css";

const platformIcons = {
  全部: "✦",
  小红书: "📕",
  抖音: "♪",
  视频号: "▶",
  快手: "⚡",
};

const accountPlatforms = [
  { id: "全部", label: "全部平台", icon: platformIcons.全部 },
  { id: "小红书", label: "小红书", icon: platformIcons.小红书 },
  { id: "抖音", label: "抖音", icon: platformIcons.抖音 },
  { id: "视频号", label: "视频号", icon: platformIcons.视频号 },
  { id: "快手", label: "快手", icon: platformIcons.快手 },
];

function getAvatarChar(name) {
  return name?.trim()?.charAt(0) || "?";
}

function getProfileCompletion(account) {
  const fields = [
    account?.name,
    account?.description,
    account?.purpose,
    account?.industry,
    account?.productService,
    account?.knowledgeBaseSummary?.name,
  ];
  return `${Math.round((fields.filter(Boolean).length / fields.length) * 100)}%`;
}

export default function AccountProfile({ app }) {
  const [platformFilter, setPlatformFilter] = useState(app.accountPage?.platform || "全部");
  const [accountKeyword, setAccountKeyword] = useState(app.accountPage?.keyword || "");
  const [deletingAccountId, setDeletingAccountId] = useState("");
  const [showDigitalHumanCreate, setShowDigitalHumanCreate] = useState(false);

  const accounts = app.accounts || [];
  const accountPage = app.accountPage || {
    page: 1,
    pageSize: 4,
    total: accounts.length,
    keyword: "",
    platform: "",
  };
  const accountTotalPages = Math.max(1, Math.ceil((accountPage.total || 0) / accountPage.pageSize));

  const loadAccountPage = (page, overrides = {}) => {
    const nextPlatform = overrides.platform ?? platformFilter;
    app.loadAccountsPage?.({
      page,
      pageSize: accountPage.pageSize,
      keyword: overrides.keyword ?? accountKeyword.trim(),
      platform: nextPlatform === "全部" ? "" : nextPlatform,
    });
  };

  const searchAccounts = (event) => {
    event.preventDefault();
    loadAccountPage(1);
  };

  const confirmDelete = async (account) => {
    if (deletingAccountId) return;
    if (!window.confirm(`确认删除账号「${account.name}」？相关选题、任务、素材和报告会一并移除。`)) return;

    setDeletingAccountId(account.id);
    try {
      await app.deleteAccount(account.id);
    } finally {
      setDeletingAccountId("");
    }
  };

  const currentAccount = app.currentAccount;
  const knowledgeBases = app.knowledgeBases || [];
  const knowledgeBaseTotal = app.knowledgeBasePage?.total ?? knowledgeBases.length;
  const totalKnowledgeImages = knowledgeBases.reduce(
    (total, knowledgeBase) => total + (knowledgeBase.imageMaterials || []).filter((item) => item?.trim()).length,
    0
  );
  const completion = getProfileCompletion(currentAccount);

  return (
    <div className="account-profile-ux-shell">
      <header className="account-toolbar account-profile-ux-header">
        <div className="account-profile-heading">
          <span className="account-profile-kicker">ACCOUNT PROFILES</span>
          <h2>账号档案</h2>
          <p>管理多平台账号身份，并为内容工作台切换当前运营账号。</p>
        </div>

        <div className="account-toolbar-right">
          <form className="inline-search account-profile-search" onSubmit={searchAccounts}>
            <label className="sr-only" htmlFor="account-profile-search">搜索账号名称</label>
            <input
              id="account-profile-search"
              value={accountKeyword}
              onChange={(event) => setAccountKeyword(event.target.value)}
              placeholder="搜索账号名称"
            />
            <button className="btn btn-sm" type="submit" disabled={app.accountLoading}>搜索</button>
          </form>
          <button className="btn btn-primary" type="button" onClick={() => app.openAccountModal?.()}>
            + 新建账号
          </button>
        </div>
      </header>

      <nav className="account-platform-nav" aria-label="按平台筛选账号">
        {accountPlatforms.map((platform) => (
          <button
            key={platform.id}
            className={`pill account-platform-filter ${platformFilter === platform.id ? "active" : ""}`}
            type="button"
            aria-pressed={platformFilter === platform.id}
            onClick={() => {
              setPlatformFilter(platform.id);
              loadAccountPage(1, { platform: platform.id });
            }}
          >
            <span className="platform-filter-icon" aria-hidden="true">{platform.icon}</span>
            {platform.label}
          </button>
        ))}
      </nav>

      {currentAccount ? (
        <section className="account-hero-card" aria-labelledby="current-account-title">
          <div className="account-hero-identity">
            <div className="account-hero-avatar" aria-hidden="true">{getAvatarChar(currentAccount.name)}</div>
            <div className="account-hero-info">
              <span className="account-hero-eyebrow">当前运营账号</span>
              <h3 id="current-account-title">
                {currentAccount.name}
                <span className="hero-badge-active">使用中</span>
              </h3>
              <span className="hero-subtitle">{currentAccount.description || "未设置定位"}</span>
              <div className="hero-platform-tags">
                {(currentAccount.platforms || []).map((platform) => (
                  <span className="platform-tag-outline" key={platform}>
                    <span aria-hidden="true">{platformIcons[platform] || "●"}</span>
                    {platform}
                  </span>
                ))}
                {currentAccount.type ? <span className="platform-tag-outline">{currentAccount.type}</span> : null}
              </div>
            </div>
          </div>

          <div className="account-hero-stat">
            <span className="stat-label">运营目标</span>
            <span className="stat-value">{currentAccount.purpose || "未设置"}</span>
          </div>

          <div className="account-hero-stat">
            <span className="stat-label">关联知识库</span>
            <span className="stat-value">{currentAccount.knowledgeBaseSummary?.name || "未关联"}</span>
          </div>

          <div className="account-hero-stat">
            <span className="stat-label">档案完整度</span>
            <span className="stat-value account-completion-value">{completion}</span>
            <div className="archive-progress" aria-label={`档案完整度 ${completion}`}>
              <div className="archive-progress-bar" style={{ width: completion }} />
            </div>
          </div>

          <div className="account-hero-actions account-hero-actions-right">
            <button className="btn-enter-workspace" type="button" onClick={() => app.setActivePage("topic")}>
              进入工作台
            </button>
            <button className="link-edit-archive" type="button" onClick={() => app.openAccountModal?.(currentAccount)}>
              编辑当前档案
            </button>
          </div>
        </section>
      ) : null}

      {currentAccount ? <section className="account-list-section" aria-labelledby="account-digital-human-title">
        <div className="account-grid-heading">
          <div>
            <span className="account-grid-kicker">DIGITAL HUMAN</span>
            <h3 className="account-grid-title" id="account-digital-human-title">数字人配置</h3>
            <p className="muted">上传固定文案口播视频，为当前账号创建可复用的形象和克隆声音。</p>
          </div>
          <button className="btn btn-primary" type="button" onClick={() => setShowDigitalHumanCreate((value) => !value)}>
            {showDigitalHumanCreate ? "收起创建" : "+ 创建数字人"}
          </button>
        </div>
        {showDigitalHumanCreate ? (
          <DigitalHumanEnrollmentPanel
            app={app}
            onCreated={() => setShowDigitalHumanCreate(false)}
          />
        ) : null}
        <DigitalHumanProfileGrid app={app} profiles={app.digitalHumanProfiles || []} />
      </section> : null}

      <section className="account-list-section" aria-labelledby="all-accounts-title">
        <div className="account-grid-heading">
          <div>
            <span className="account-grid-kicker">ALL ACCOUNTS</span>
            <h3 className="account-grid-title" id="all-accounts-title">全部账号</h3>
          </div>
          <span className="muted">共 {accountPage.total} 个账号</span>
        </div>

        {app.accountLoading ? (
          <article className="glass-card card account-state-card">
            <h3>正在加载账号</h3>
            <p>稍等片刻，系统正在获取当前页数据。</p>
          </article>
        ) : accountPage.total === 0 ? (
          <article className="glass-card card account-state-card">
            <h3>暂无账号档案</h3>
            <p>新建账号后，系统会生成对应的选题、任务、素材库与报告空间。</p>
          </article>
        ) : (
          <>
            <div className="account-grid">
              {accounts.map((account) => {
                const isCurrent = account.id === app.currentAccountId;
                const isDeleting = account.id === deletingAccountId;

                return (
                  <article className={`account-card ${isCurrent ? "is-current" : ""}`} key={account.id}>
                    <div className="account-card-header">
                      <div className="account-card-avatar" aria-hidden="true">{getAvatarChar(account.name)}</div>
                      <div className="account-card-title">
                        <h4>{account.name}</h4>
                        <span>{account.type || "普通号"}</span>
                      </div>
                      {isCurrent ? <span className="hero-badge-active">当前</span> : null}
                    </div>

                    <span className="account-card-desc">{account.description || "未设置定位"}</span>
                    <div className="account-card-tags">
                      {(account.platforms || []).map((platform) => (
                        <span className="platform-tag-outline" key={platform}>
                          <span aria-hidden="true">{platformIcons[platform] || "●"}</span>
                          {platform}
                        </span>
                      ))}
                    </div>

                    <div className="account-card-meta">
                      <div className="account-card-meta-row">
                        <span>运营目标</span>
                        <span>{account.purpose || "未设置"}</span>
                      </div>
                      <div className="account-card-meta-row">
                        <span>关联知识库</span>
                        <span>{account.knowledgeBaseSummary?.name || "未关联"}</span>
                      </div>
                    </div>

                    <div className="account-card-actions">
                      <button
                        className="btn-switch-account"
                        type="button"
                        disabled={isCurrent || Boolean(deletingAccountId)}
                        onClick={() => app.switchAccount(account.id)}
                      >
                        {isCurrent ? "当前账号" : "切换账号"}
                      </button>
                      <button
                        className="account-card-action"
                        type="button"
                        disabled={Boolean(deletingAccountId)}
                        onClick={() => app.openAccountModal?.(account)}
                      >
                        编辑
                      </button>
                      <button
                        className="account-card-action account-card-delete"
                        type="button"
                        disabled={Boolean(deletingAccountId)}
                        onClick={() => confirmDelete(account)}
                      >
                        {isDeleting ? "删除中…" : "删除"}
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>

            <div className="pagination-row account-pagination">
              <span className="muted">第 {accountPage.page} / {accountTotalPages} 页</span>
              <div className="button-row">
                <button
                  className="btn btn-sm"
                  type="button"
                  disabled={accountPage.page <= 1 || app.accountLoading}
                  onClick={() => loadAccountPage(accountPage.page - 1)}
                >
                  上一页
                </button>
                <button
                  className="btn btn-sm"
                  type="button"
                  disabled={accountPage.page >= accountTotalPages || app.accountLoading}
                  onClick={() => loadAccountPage(accountPage.page + 1)}
                >
                  下一页
                </button>
              </div>
            </div>
          </>
        )}
      </section>

      <aside className="knowledge-bar">
        <span className="knowledge-bar-icon" aria-hidden="true">▣</span>
        <div className="knowledge-bar-copy">
          <span className="knowledge-bar-title">品牌知识库</span>
          <span className="knowledge-bar-stats">
            可用知识库 {knowledgeBaseTotal} 个 · 已载入图片素材 {totalKnowledgeImages} 条
          </span>
        </div>
        <button className="knowledge-bar-link" type="button" onClick={() => app.openKnowledgeBaseModal()}>
          管理知识库 →
        </button>
      </aside>
    </div>
  );
}
