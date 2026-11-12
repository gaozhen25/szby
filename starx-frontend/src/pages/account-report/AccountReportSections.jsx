import { useLayoutEffect, useRef, useState } from "react";
import { asArray, formatMetric, metricEntries, metricIcon, metricLabel, resolvePlatformDisplay } from "../../utils/accountReport";
import CreatorAvatar from "../../components/CreatorAvatar";

function EmptyBlock({ children = "暂无可展示的数据" }) {
  return <div className="report-empty-inline">{children}</div>;
}

/** Clamp long copy to N lines; toggle sits after the visible text. */
function ExpandableText({ label = "", text = "", lines = 2, className = "" }) {
  const bodyRef = useRef(null);
  const [expanded, setExpanded] = useState(false);
  const [overflows, setOverflows] = useState(false);
  const content = String(text || "");

  useLayoutEffect(() => {
    const node = bodyRef.current;
    if (!node) return undefined;

    const measure = () => {
      const wasExpanded = node.classList.contains("is-expanded");
      node.classList.add("is-clamped");
      node.classList.remove("is-expanded");
      const nextOverflows = node.scrollHeight > node.clientHeight + 1;
      if (wasExpanded) {
        node.classList.add("is-expanded");
        node.classList.remove("is-clamped");
      }
      setOverflows(nextOverflows);
    };

    measure();
    if (typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [content, label, lines, expanded]);

  if (!content) return null;

  return (
    <div
      className={`expandable-text ${expanded ? "is-expanded" : "is-clamped"} ${className}`.trim()}
      style={{ "--expandable-lines": String(lines) }}
    >
      <p ref={bodyRef} className={`expandable-text-body ${expanded ? "is-expanded" : "is-clamped"}`}>
        {label ? <b>{label}</b> : null}
        {content}
        {expanded && overflows ? (
          <>
            {" "}
            <button
              type="button"
              className="expandable-text-toggle"
              aria-expanded={true}
              onClick={() => setExpanded(false)}
            >
              收起
            </button>
          </>
        ) : null}
      </p>
      {!expanded && overflows ? (
        <button
          type="button"
          className="expandable-text-toggle expandable-text-toggle-trail"
          aria-expanded={false}
          onClick={() => setExpanded(true)}
        >
          展开
        </button>
      ) : null}
    </div>
  );
}

/** Clamp a whole content block; one expand/collapse for the region. */
function ExpandableBlock({ children, lines = 2, className = "" }) {
  const bodyRef = useRef(null);
  const [expanded, setExpanded] = useState(false);
  const [overflows, setOverflows] = useState(false);

  useLayoutEffect(() => {
    const node = bodyRef.current;
    if (!node) return undefined;

    const measure = () => {
      const wasExpanded = node.classList.contains("is-expanded");
      node.classList.add("is-clamped");
      node.classList.remove("is-expanded");
      const nextOverflows = node.scrollHeight > node.clientHeight + 1;
      if (wasExpanded) {
        node.classList.add("is-expanded");
        node.classList.remove("is-clamped");
      }
      setOverflows(nextOverflows);
    };

    measure();
    if (typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [children, lines, expanded]);

  return (
    <div
      className={`expandable-block ${expanded ? "is-expanded" : "is-clamped"} ${className}`.trim()}
      style={{ "--expandable-lines": String(lines) }}
    >
      <div ref={bodyRef} className={`expandable-block-body ${expanded ? "is-expanded" : "is-clamped"}`}>
        {children}
      </div>
      {overflows || expanded ? (
        <button
          type="button"
          className="expandable-block-toggle"
          aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded ? "收起" : "展开"}
        </button>
      ) : null}
    </div>
  );
}

function PlatformTag({ platform, className = "" }) {
  const { icon, label } = resolvePlatformDisplay(platform);
  return (
    <span className={`platform-readable-tag ${className}`.trim()} title={label}>
      <span aria-hidden="true">{icon}</span>
      {label}
    </span>
  );
}

function TagList({ items }) {
  const values = asArray(items).filter(Boolean);
  if (!values.length) return <EmptyBlock />;
  return (
    <div className="profile-tags">
      {values.map((item, index) => <span className="profile-tag" key={`${item}-${index}`}>{item}</span>)}
    </div>
  );
}

function Metrics({ metrics }) {
  const entries = metricEntries(metrics);
  if (!entries.length) return null;
  return (
    <div className="report-metrics">
      {entries.map(([key, value]) => {
        const label = metricLabel(key);
        const icon = metricIcon(key);
        return (
          <span key={key} title={label}>
            {icon ? <span className="report-metric-icon" aria-hidden="true">{icon}</span> : null}
            <b>{formatMetric(value)}</b>
            {icon ? <span className="sr-only">{label}</span> : label}
          </span>
        );
      })}
    </div>
  );
}

function CreatorProfileName({ creator, fallback, className = "" }) {
  const label = creator?.name || fallback;
  if (!creator?.safeProfileUrl) return <span className={className}>{label}</span>;
  return (
    <a
      className={`creator-profile-link ${className}`.trim()}
      href={creator.safeProfileUrl}
      target="_blank"
      rel="noopener noreferrer"
    >
      {label}
    </a>
  );
}

function competitorAccountKey(account) {
  return account?.safeProfileUrl || account?.creatorHash || account?.configurationKey || "";
}

function AddToCompetitorsButton({
  account,
  onAdd,
  addingKeys,
  addedKeys,
  disabled = false,
  compact = false,
}) {
  if (!onAdd) return null;
  const accountKey = competitorAccountKey(account);
  const adding = addingKeys?.has(accountKey);
  const added = addedKeys?.has(accountKey);
  const unavailable = !account?.safeProfileUrl;
  return (
    <button
      type="button"
      className={`btn btn-xs report-add-competitor ${compact ? "is-compact" : ""}`.trim()}
      disabled={disabled || unavailable || adding || added}
      title={unavailable ? "缺少公开主页链接，暂时无法添加" : "快捷添加到竞品监控"}
      onClick={() => onAdd(account)}
    >
      {adding ? "添加中…" : added ? "✓ 已添加" : compact ? "＋ 监控" : "＋ 添加到竞品监控"}
    </button>
  );
}

function SectionRegenerateButton({ onRegenerate, regenerating, disabled }) {
  if (!onRegenerate) return null;
  return (
    <button
      type="button"
      className="btn btn-sm report-section-regenerate"
      disabled={disabled || regenerating}
      onClick={onRegenerate}
    >
      {regenerating ? "生成中…" : "重新生成"}
    </button>
  );
}

export function ReportCard({ icon, title, subtitle, children, action, headerAction, className = "" }) {
  return (
    <section className={`report-card ${className}`.trim()}>
      <div className="report-card-header">
        <div className="report-card-icon" aria-hidden="true">{icon}</div>
        <div className="report-card-header-text">
          <h3>{title}</h3>
          <p>{subtitle}</p>
        </div>
        {headerAction}
      </div>
      <div className="report-card-body">{children}</div>
      {action}
    </section>
  );
}

export function ReportSectionLoading({ icon, title }) {
  return (
    <ReportCard icon={icon} title={title} subtitle="AI 正在独立生成此板块">
      <div className="report-section-loading" role="status" aria-live="polite">
        <span className="report-section-loading-spinner" aria-hidden="true">✦</span>
        <div>
          <strong>生成中…</strong>
          <small>完成后会自动展示，无需等待其他板块</small>
        </div>
      </div>
    </ReportCard>
  );
}

export function SimilarAccountsSummary({
  accounts,
  legacyText,
  onOpen,
  onAddToCompetitors,
  addingCompetitorKeys,
  addedCompetitorKeys,
  onRegenerate,
  regenerating,
  disabled,
}) {
  const topAccounts = accounts.slice(0, 3);
  return (
    <ReportCard
      icon="🔍"
      title="相似账号"
      subtitle={accounts.length ? `共 ${accounts.length} 个公开账号样本` : "等待公开账号证据"}
      headerAction={<SectionRegenerateButton onRegenerate={onRegenerate} regenerating={regenerating} disabled={disabled} />}
      action={<button type="button" className="btn btn-sm report-card-action" onClick={onOpen}>查看完整名单 ›</button>}
    >
      {topAccounts.length ? topAccounts.map((account, index) => (
        <div className="similar-account-mini" key={account.creatorHash || `${account.name}-${index}`}>
          <CreatorAvatar creator={account} className="mini-avatar" />
          <div className="mini-info">
            <CreatorProfileName creator={account} fallback="未命名账号" className="mini-name" />
            <PlatformTag platform={account.platform} className="mini-tag" />
            <small>{account.similarityReason || "暂无相似原因"}</small>
            {Array.isArray(account.representativeContents) && account.representativeContents.length ? (
              <div className="mini-rep-contents">
                {account.representativeContents.slice(0, 2).map((item) => (
                  <span key={`${account.creatorHash || account.name}-${item}`}>{item}</span>
                ))}
              </div>
            ) : null}
          </div>
          <AddToCompetitorsButton
            account={account}
            onAdd={onAddToCompetitors}
            addingKeys={addingCompetitorKeys}
            addedKeys={addedCompetitorKeys}
            disabled={disabled}
            compact
          />
        </div>
      )) : <EmptyBlock>{legacyText || "暂无足够的公开相似账号样本"}</EmptyBlock>}
    </ReportCard>
  );
}

export function ComplianceSummary({ rules, industry, legacyText, onOpen, onRegenerate, regenerating, disabled }) {
  return (
    <ReportCard
      icon="🛡"
      title="行业合规提醒"
      subtitle={industry ? `行业：${industry}` : "基于账号行业与目标平台"}
      headerAction={<SectionRegenerateButton onRegenerate={onRegenerate} regenerating={regenerating} disabled={disabled} />}
      action={rules.length > 0 ? <button type="button" className="btn btn-sm report-card-action" onClick={onOpen}>查看规则 ›</button> : null}
    >
      {rules.length ? (
        <div className="risk-pills">
          {rules.slice(0, 4).map((rule, index) => (
            <span className={`risk-pill risk-${rule.riskLevel || "medium"}`} key={`${rule.expression}-${index}`}>
              <span className="risk-icon">⚠</span>{rule.expression || "风险表达"}
            </span>
          ))}
        </div>
      ) : <EmptyBlock>{legacyText || "暂无行业合规规则"}</EmptyBlock>}
    </ReportCard>
  );
}

export function TargetProfileCard({ profile, legacyText, onRegenerate, regenerating, disabled }) {
  const categories = asArray(profile.categories);
  const ranking = profile.priorityRanking || {};
  const reminder = profile.positioningReminder || {};
  const priorityCategory = ranking.priorityCategory || "";
  const coreNeeds = asArray(profile.coreNeeds);
  const preferences = asArray(profile.contentPreferences);
  const concerns = asArray(profile.purchaseConcerns);
  const triggers = asArray(profile.conversionTriggers);
  const hasLegacyProfile = Boolean(profile.summary || coreNeeds.length || preferences.length || concerns.length || triggers.length);
  const needsProfileUpgrade = hasLegacyProfile || Boolean(String(legacyText || "").trim());
  const profileDescription = (genderProfile) => genderProfile?.description || "暂无画像";
  const levelLabel = { high: "高", medium: "中", low: "低", "高": "高", "较高": "较高", "中等": "中等", "较低": "较低", "低": "低" };
  return (
    <ReportCard
      icon="👤"
      title="目标用户画像"
      subtitle={categories.length ? `${categories.length} 类核心用户${priorityCategory ? ` · 优先：${priorityCategory}` : ""}` : (needsProfileUpgrade ? "旧版画像，需重新生成" : "从报告证据提炼用户特征")}
      headerAction={<SectionRegenerateButton onRegenerate={onRegenerate} regenerating={regenerating} disabled={disabled} />}
    >
      {categories.length ? (
        <div className="target-profile-categories">
          {profile.assumption ? (
            <ExpandableText
              className="target-profile-assumption"
              label="分析假设："
              text={profile.assumption}
              lines={2}
            />
          ) : null}
          {categories.map((category, index) => (
            <article className="target-profile-category" key={`${category.categoryName || "用户类别"}-${index}`}>
              <h4>{category.categoryName || `用户类别 ${index + 1}`}</h4>
              <ExpandableText
                className="target-profile-motivation"
                label="购买动机："
                text={category.purchaseMotivation || "暂无"}
                lines={2}
              />
              {category.specificProfile ? (
                <ExpandableText text={category.specificProfile} lines={3} />
              ) : (
                <div className="target-profile-genders">
                  <div>
                    <strong>男性画像{category.maleProfile?.applicable === false ? "（非有效用户）" : ""}</strong>
                    <ExpandableText text={profileDescription(category.maleProfile)} lines={2} />
                  </div>
                  <div>
                    <strong>女性画像{category.femaleProfile?.applicable === false ? "（非有效用户）" : ""}</strong>
                    <ExpandableText text={profileDescription(category.femaleProfile)} lines={2} />
                  </div>
                </div>
              )}
            </article>
          ))}
          {priorityCategory ? (
            <div className="target-profile-conclusion">
              <h4>优先用户排序</h4>
              <ExpandableBlock lines={2} className="target-profile-conclusion-body">
                <ol>{asArray(ranking.rankedCategories).map((item, index) => (
                  <li key={`${item.categoryName}-${index}`}>
                    <b>{item.categoryName}</b>{item.priority ? `（第 ${item.priority} 优先级）` : ""}：内容吸引力 {levelLabel[item.contentAttraction] || "待判断"}、
                    信任建立难度 {levelLabel[item.trustDifficulty] || "待判断"}、
                    付费可能性 {levelLabel[item.paymentLikelihood] || "待判断"}、
                    复购可能性 {levelLabel[item.repurchaseLikelihood] || "待判断"}。{item.reason}
                  </li>
                ))}</ol>
                <p><b>最值得优先服务：</b>{priorityCategory}。{ranking.priorityReason}</p>
              </ExpandableBlock>
            </div>
          ) : null}
          {(reminder.commonMisjudgment || reminder.hypothesisToValidate) ? (
            <div className="target-profile-conclusion">
              <h4>定位提醒</h4>
              <ExpandableBlock lines={2} className="target-profile-conclusion-body">
                {reminder.commonMisjudgment ? <p><b>判断误区：</b>{reminder.commonMisjudgment}</p> : null}
                {reminder.hypothesisToValidate ? <p><b>待验证假设：</b>{reminder.hypothesisToValidate}</p> : null}
              </ExpandableBlock>
            </div>
          ) : null}
        </div>
      ) : needsProfileUpgrade ? (
        <div className="target-profile-upgrade-notice">
          <strong>当前保存的是旧版目标用户画像</strong>
          <p>请点击页面右上角“重新生成”，升级为按购买场景、需求状态和决策逻辑划分的 3–5 类用户画像。</p>
        </div>
      ) : <EmptyBlock>暂无目标用户画像</EmptyBlock>}
    </ReportCard>
  );
}

export function HotContentsCard({ contents, legacyText, onRegenerate, regenerating, disabled }) {
  return (
    <ReportCard
      icon="🔥"
      title="爆款笔记参考"
      subtitle={contents.length ? `${contents.length} 个公开高互动样本` : "等待公开内容证据"}
      headerAction={<SectionRegenerateButton onRegenerate={onRegenerate} regenerating={regenerating} disabled={disabled} />}
    >
      {contents.length ? <div className="report-hot-content-list">{contents.slice(0, 8).map((content, index) => {
        const key = content.contentId || `${content.title}-${index}`;
        const title = content.title || "未命名内容";
        const typeIcon = content.contentType === "video" ? "🎬" : "📄";
        const reason = String(content.selectionReason || "").trim();
        const metrics = content.metrics && typeof content.metrics === "object" ? content.metrics : content;
        const body = (
          <div className="trending-note-content">
            <span className="note-title">{title}</span>
            <div className="note-meta">
              <PlatformTag platform={content.platform} />
            </div>
            {reason ? <p className="note-reason">{reason}</p> : null}
            <Metrics metrics={metrics} />
          </div>
        );
        return (
          <div className="trending-note" key={key}>
            <div className="note-thumb">
              <span aria-hidden="true">{typeIcon}</span>
              {content.safeCoverUrl ? (
                <img
                  src={content.safeCoverUrl}
                  alt={`${title}封面`}
                  loading="lazy"
                  referrerPolicy="no-referrer"
                  onError={(event) => { event.currentTarget.style.display = "none"; }}
                />
              ) : null}
            </div>
            {content.safeUrl ? (
              <a className="report-safe-link" href={content.safeUrl} target="_blank" rel="noopener noreferrer">{body}</a>
            ) : (
              <div className="note-body">{body}</div>
            )}
          </div>
        );
      })}</div> : <EmptyBlock>{legacyText || "暂无足够的公开爆款样本"}</EmptyBlock>}
    </ReportCard>
  );
}

export function SimilarAccountsView({
  accounts,
  accountName,
  industry,
  onBack,
  onAdd,
  onEdit,
  onDelete,
  onAddToCompetitors,
  addingCompetitorKeys,
  addedCompetitorKeys,
  deletingKey,
  disabled,
}) {
  return (
    <div>
      <button className="report-back-nav" onClick={onBack}>← 返回账号报告</button>
      <div className="report-hero report-masthead">
        <div className="report-masthead-copy">
          <span className="report-kicker">SIMILAR ACCOUNTS</span>
          <h2>相似账号名单</h2>
          <p className="report-hero-subtitle">{accountName} · {industry || "未设置行业"} · AI 推荐与人工配置</p>
        </div>
        <div className="report-hero-actions">
          <button type="button" className="btn btn-primary" disabled={disabled} onClick={onAdd}>＋ 添加相似账号</button>
        </div>
      </div>
      {accounts.length ? (
        <div className="report-detail-grid">
          {accounts.slice(0, 20).map((account, index) => {
            const configurationKey = account.configurationKey || account.creatorHash || "";
            return (
            <article className="report-detail-card" key={configurationKey || `${account.name}-${index}`}>
              <div className="report-detail-title">
                <CreatorAvatar creator={account} className="report-similar-list-avatar" />
                <div>
                  <h3><CreatorProfileName creator={account} fallback="未命名账号" /></h3>
                  <div className="report-similar-account-tags">
                    <PlatformTag platform={account.platform} />
                    {account.isBenchmark || account.configurationSource === "benchmark" ? (
                      <small className="report-manual-tag">对标账号</small>
                    ) : account.configurationSource === "manual" ? (
                      <small className="report-manual-tag">人工配置</small>
                    ) : null}
                  </div>
                </div>
                <div className="report-similar-actions">
                  <AddToCompetitorsButton
                    account={account}
                    onAdd={onAddToCompetitors}
                    addingKeys={addingCompetitorKeys}
                    addedKeys={addedCompetitorKeys}
                    disabled={disabled}
                  />
                  {onEdit && (account.configurationSource === "manual" || account.configurationSource === "benchmark" || account.isBenchmark) ? (
                    <button
                      type="button"
                      className="btn btn-xs report-similar-edit"
                      disabled={disabled}
                      onClick={() => onEdit(account)}
                      aria-label={`编辑相似账号${account.name || ""}`}
                    >
                      编辑
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className="btn btn-xs btn-danger report-similar-delete"
                    disabled={disabled || deletingKey === configurationKey}
                    onClick={() => onDelete(account)}
                    aria-label={`删除相似账号${account.name || ""}`}
                  >
                    {deletingKey === configurationKey ? "删除中…" : "删除"}
                  </button>
                </div>
              </div>
              <p>{account.similarityReason || "暂无相似原因"}</p>
              <div><h4>代表内容</h4><TagList items={account.representativeContents} /></div>
            </article>
            );
          })}
        </div>
      ) : <EmptyBlock>暂无可展示的相似账号</EmptyBlock>}
    </div>
  );
}

export function ComplianceRulesView({ rules, industry, onBack }) {
  const riskLabel = { high: "高风险", medium: "中风险", low: "低风险" };
  return (
    <div>
      <button className="report-back-nav" onClick={onBack}>← 返回账号报告</button>
      <div className="report-hero report-masthead">
        <div className="report-masthead-copy">
          <span className="report-kicker">COMPLIANCE</span>
          <h2>{industry || "当前行业"}合规规则</h2>
          <p className="report-hero-subtitle">以下提醒来自本次账号报告，请结合平台最新规范复核</p>
        </div>
      </div>
      {rules.length ? (
        <div className="report-table-wrap"><table className="compliance-table"><thead><tr><th>风险等级</th><th>风险表达</th><th>原因</th><th>建议替换</th><th>平台</th></tr></thead><tbody>
          {rules.map((rule, index) => <tr key={`${rule.expression}-${index}`}><td><span className={`risk-level risk-${rule.riskLevel || "medium"}`}>{riskLabel[rule.riskLevel] || "需注意"}</span></td><td>{rule.expression || "-"}</td><td>{rule.reason || "-"}</td><td>{rule.suggestion || "-"}</td><td>{asArray(rule.platforms).join("、") || "通用"}</td></tr>)}
        </tbody></table></div>
      ) : <EmptyBlock>暂无可展示的合规规则</EmptyBlock>}
    </div>
  );
}

export function SourceNotices({ sourceMeta, failedPlatforms, unsupportedPlatforms, keywords, generatedAt, formatDate }) {
  const platforms = asArray(sourceMeta.platforms);
  const sampleCount = Number.isFinite(Number(sourceMeta.sampleCount)) ? Math.max(0, Number(sourceMeta.sampleCount)) : 0;
  const hasExternalEvidence = sampleCount > 0;
  return (
    <section className="report-source-notices">
      <div className="report-source-header"><h3>报告来源说明</h3><span>生成于 {formatDate(generatedAt)}</span></div>
      <div className="report-source-meta">
        <span>平台：{platforms.join("、") || "未记录"}</span>
        <span>关键词：{keywords.join("、") || "未使用关键词"}</span>
        <span>公开样本：{formatMetric(sampleCount)}</span>
      </div>
      {!hasExternalEvidence ? <p className="report-notice info">本次报告未获得可用外部公开内容，结论主要基于账号档案。</p> : null}
      {unsupportedPlatforms.map((platform) => <p className="report-notice info" key={platform}>{platform} 暂不支持公开内容采集，已使用账号档案降级生成。</p>)}
      {failedPlatforms.map((failure, index) => <p className="report-notice warning" key={`${failure.platform || "平台"}-${index}`}>{failure.platform || "部分平台"}：{failure.reason || failure.message || "公开内容采集失败"}</p>)}
    </section>
  );
}
