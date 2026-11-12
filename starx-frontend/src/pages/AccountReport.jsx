import { useCallback, useEffect, useState } from "react";

import {
  ComplianceRulesView,
  ComplianceSummary,
  HotContentsCard,
  ReportSectionLoading,
  SimilarAccountsSummary,
  SimilarAccountsView,
  SourceNotices,
  TargetProfileCard,
} from "./account-report/AccountReportSections";
import AccountReportLoadingOverlay from "./account-report/AccountReportLoadingOverlay";
import SimilarAccountDeleteModal from "./account-report/SimilarAccountDeleteModal";
import SimilarAccountModal from "./account-report/SimilarAccountModal";
import {
  asArray,
  createAccountReportViewModel,
  formatReportDate,
  logHotContentsBackendData,
} from "../utils/accountReport";
import {
  createAccountReportExport,
  downloadAccountReportMarkdown,
  printAccountReportPdf,
} from "../utils/accountReportExport";
import "../styles/account-report.css";

function EmptyReport({ failed, onRefresh, disabled }) {
  return (
    <div className="report-empty-state">
      <span>{failed ? "⚠" : "📊"}</span>
      <h3>{failed ? "账号报告暂未生成" : "尚无账号报告"}</h3>
      <p>{failed ? "本次生成失败，没有覆盖已有数据。你可以稍后重新生成。" : "点击生成后，系统会结合账号档案与支持平台的公开内容生成报告。"}</p>
      <button className="btn btn-primary" disabled={disabled} onClick={onRefresh}>生成账号报告</button>
    </div>
  );
}

export default function AccountReport({ app }) {
  const [view, setView] = useState("main");
  const [referenceComments, setReferenceComments] = useState(false);
  const [showSimilarAccountModal, setShowSimilarAccountModal] = useState(false);
  const [deletingSimilarAccountKey, setDeletingSimilarAccountKey] = useState("");
  const [pendingDeleteSimilarAccount, setPendingDeleteSimilarAccount] = useState(null);
  const [addingCompetitorKeys, setAddingCompetitorKeys] = useState(() => new Set());
  const [addedCompetitorKeys, setAddedCompetitorKeys] = useState(() => new Set());
  const workflow = app.reportWorkflow;
  const sectionWorkflows = app.reportSectionWorkflows || {};
  const reportView = createAccountReportViewModel(app.report, workflow);
  const report = reportView.report;
  const similarAccounts = reportView.similarAccounts;
  const reportComplianceRules = asArray(report?.complianceRules);
  const targetUserProfile = report?.targetUserProfile || {};
  const hotContents = reportView.hotContents;
  const sourceMeta = reportView.sourceMeta;
  const legacyCompetitors = report?.competitors || "";
  const legacyProhibitedWords = report?.prohibitedWords || "";
  const legacyTargetUsers = report?.targetUsers || "";
  const legacyHotContent = report?.hotContent || "";
  const generatedAt = report?.generatedAt;

  const failedPlatforms = asArray(sourceMeta.failedPlatforms);
  const unsupportedPlatforms = asArray(sourceMeta.unsupportedPlatforms);
  const keywords = asArray(sourceMeta.keywords);
  const accountName = app.currentAccount?.name || "未知账号";
  const industry = app.currentAccount?.industry || "未设置行业";
  const platforms = asArray(app.currentAccount?.platforms);
  const platformText = platforms.join("、") || app.currentAccount?.platform || "未设置平台";
  const hasReport = reportView.hasReport;
  const skeleton = reportView.state === "skeleton";
  const isFailed = reportView.isFailed;
  const showLoading = Boolean(app.isGeneratingReport || reportView.isActive);
  const isSectionGenerating = (sectionKey) => Boolean(sectionWorkflows[sectionKey]);
  const hasGeneratingSection = Object.keys(sectionWorkflows).length > 0;
  const activeSectionKey = String(
    workflow?.inputPayload?.sectionKey || workflow?.resultPayload?.reportSectionKey || ""
  );
  const showFullLoading = showLoading && !activeSectionKey;
  const completedSections = new Set(reportView.completedSections);
  const hasVisibleCompletedSection = reportView.visibleCompletedSections.length > 0;
  const showReportContent = hasReport && (
    !showLoading || reportView.hasPublishedReport || hasVisibleCompletedSection
  );
  const isSectionReady = (sectionKey) => (
    !showLoading || reportView.hasPublishedReport || completedSections.has(sectionKey)
  );

  useEffect(() => {
    setReferenceComments(false);
    setShowSimilarAccountModal(false);
    setDeletingSimilarAccountKey("");
    setPendingDeleteSimilarAccount(null);
    setAddingCompetitorKeys(new Set());
    setAddedCompetitorKeys(new Set());
  }, [app.currentAccount?.id]);

  const closeSimilarAccountModal = useCallback(() => {
    setShowSimilarAccountModal(false);
  }, []);

  const requestDeleteSimilarAccount = (account) => {
    const configurationKey = account.configurationKey || account.creatorHash;
    if (!configurationKey) {
      app.addToast("该相似账号缺少删除标识，请刷新报告后重试", "warning");
      return;
    }
    setPendingDeleteSimilarAccount({ ...account, configurationKey });
  };

  const confirmDeleteSimilarAccount = async () => {
    const configurationKey = pendingDeleteSimilarAccount?.configurationKey;
    if (!configurationKey) return;
    setDeletingSimilarAccountKey(configurationKey);
    try {
      await app.deleteReportSimilarAccount(configurationKey);
      setPendingDeleteSimilarAccount(null);
    } finally {
      setDeletingSimilarAccountKey("");
    }
  };

  const addSimilarAccountToCompetitors = async (account) => {
    const accountId = app.currentAccount?.id;
    const profileUrl = account?.safeProfileUrl;
    const accountKey = profileUrl || account?.creatorHash || account?.configurationKey || "";
    if (!accountId || !profileUrl || !accountKey || addingCompetitorKeys.has(accountKey)) {
      if (!profileUrl) app.addToast("该相似账号缺少公开主页链接，暂时无法添加到竞品监控", "warning");
      return;
    }

    setAddingCompetitorKeys((current) => new Set(current).add(accountKey));
    try {
      await app.addCompetitorAccount(profileUrl);
      setAddedCompetitorKeys((current) => new Set(current).add(accountKey));
      app.addToast("已添加到竞品监控，正在抓取账号数据", "success");
    } catch (error) {
      if (error?.status === 409) {
        setAddedCompetitorKeys((current) => new Set(current).add(accountKey));
        app.addToast("该账号已在竞品监控中", "success");
      } else {
        app.addToast(error?.message || "添加竞品监控失败，请稍后重试", "warning");
      }
    } finally {
      setAddingCompetitorKeys((current) => {
        const next = new Set(current);
        next.delete(accountKey);
        return next;
      });
    }
  };

  useEffect(() => {
    if (!isSectionReady("hotContents")) return;
    logHotContentsBackendData("AccountReport/view", report, {
      accountId: app.currentAccount?.id,
      viewHotContents: hotContents,
      workflowPreview: workflow?.resultPayload?.reportPreview ?? null,
      completedSections: [...completedSections],
    });
  }, [app.currentAccount?.id, report, hotContents, workflow, showLoading, reportView.hasPublishedReport]);

  if (hasReport && view === "similar") {
    return (
      <div className="account-report-page account-report-ux-shell">
        <SimilarAccountsView
          accounts={similarAccounts}
          accountName={accountName}
          industry={industry}
          onBack={() => setView("main")}
          onAdd={() => setShowSimilarAccountModal(true)}
          onDelete={requestDeleteSimilarAccount}
          onAddToCompetitors={addSimilarAccountToCompetitors}
          addingCompetitorKeys={addingCompetitorKeys}
          addedCompetitorKeys={addedCompetitorKeys}
          deletingKey={deletingSimilarAccountKey}
          disabled={showLoading || isSectionGenerating("similarAccounts")}
        />
        <SimilarAccountModal
          open={showSimilarAccountModal}
          onClose={closeSimilarAccountModal}
          onResolve={app.resolveReportSimilarAccount}
          onSubmit={app.addReportSimilarAccount}
        />
        <SimilarAccountDeleteModal
          account={pendingDeleteSimilarAccount}
          deleting={Boolean(deletingSimilarAccountKey)}
          onCancel={() => setPendingDeleteSimilarAccount(null)}
          onConfirm={confirmDeleteSimilarAccount}
        />
      </div>
    );
  }
  if (hasReport && view === "rules") {
    return (
      <div className="account-report-page account-report-ux-shell">
        <ComplianceRulesView rules={reportComplianceRules} industry={industry} onBack={() => setView("main")} />
      </div>
    );
  }

  const refresh = () => app.refreshAccountReport(referenceComments, null);
  const refreshSection = (sectionKey) => () => (
    app.refreshAccountReport(referenceComments, sectionKey)
  );
  const createExportPayload = () => createAccountReportExport({
    account: app.currentAccount,
    reportView,
  });
  const exportMarkdown = () => {
    if (!hasReport) {
      app.addToast("请先生成账号报告，再导出 Markdown", "warning");
      return;
    }
    downloadAccountReportMarkdown(createExportPayload());
    app.addToast("Markdown 账号报告已导出", "success");
  };
  const exportPdf = () => {
    if (!hasReport) {
      app.addToast("请先生成账号报告，再导出 PDF", "warning");
      return;
    }
    const opened = printAccountReportPdf(createExportPayload());
    if (opened) {
      app.addToast("已打开专业报告打印页，可选择保存为 PDF", "success");
    } else {
      app.addToast("浏览器阻止了打印窗口，请允许弹窗后重试", "warning");
    }
  };

  return (
    <div className="account-report-page account-report-ux-shell">
      <header className="report-hero report-masthead">
        <div className="report-masthead-copy">
          <span className="report-kicker">ACCOUNT INTEL</span>
          <h2>账号报告 · <span className="hl">{accountName}</span></h2>
          <p className="report-hero-subtitle">
            基于账号档案与公开内容自动生成 · {platformText}
            {app.currentAccount?.description ? ` · ${app.currentAccount.description}` : ""}
          </p>
        </div>
        <div className="report-hero-actions">
          <span className="report-updated-at">更新于 {formatReportDate(generatedAt)}</span>
          <div className="report-export-actions" aria-label="导出账号报告">
            <button
              type="button"
              className="btn btn-sm report-export-button"
              disabled={!hasReport}
              onClick={exportPdf}
            >
              导出 PDF
            </button>
            <button
              type="button"
              className="btn btn-sm report-export-button"
              disabled={!hasReport}
              onClick={exportMarkdown}
            >
              导出 MD
            </button>
          </div>
          <div className="report-comment-toggle">
            <span className="report-comment-toggle-copy">
              <strong>参考内容评论</strong>
              <small>开启后采集公开评论用于聚合分析，耗时可能增加</small>
            </span>
            <button
              type="button"
              className="report-comment-switch"
              role="switch"
              aria-checked={referenceComments}
              aria-label="参考内容评论"
              disabled={showLoading || hasGeneratingSection}
              onClick={() => setReferenceComments((enabled) => !enabled)}
            >
              <span aria-hidden="true" />
            </button>
          </div>
          <button className="btn" onClick={refresh} disabled={showLoading || hasGeneratingSection}>
            {showLoading || hasGeneratingSection ? "生成中…" : "重新生成全部"}
          </button>
        </div>
      </header>

      {showFullLoading ? (
        <div className="report-loading-slot">
          <AccountReportLoadingOverlay workflow={workflow} reportView={reportView} />
        </div>
      ) : null}

      {!showLoading && !skeleton && !hasReport ? (
        <EmptyReport failed={isFailed} onRefresh={refresh} disabled={showLoading} />
      ) : null}

      {showReportContent ? (
        <>
          <div className="report-grid report-grid-editorial">
            <div className="report-grid-top">
              {isSectionReady("similarAccounts") ? (
                <SimilarAccountsSummary
                  accounts={similarAccounts}
                  legacyText={legacyCompetitors}
                  onOpen={() => setView("similar")}
                  onAddToCompetitors={addSimilarAccountToCompetitors}
                  addingCompetitorKeys={addingCompetitorKeys}
                  addedCompetitorKeys={addedCompetitorKeys}
                  onRegenerate={refreshSection("similarAccounts")}
                  regenerating={isSectionGenerating("similarAccounts")}
                  disabled={showLoading || isSectionGenerating("similarAccounts")}
                />
              ) : <ReportSectionLoading icon="🔍" title="相似账号" />}
              {isSectionReady("complianceRules") ? (
                <ComplianceSummary
                  rules={reportComplianceRules}
                  industry={industry}
                  legacyText={legacyProhibitedWords}
                  onOpen={() => setView("rules")}
                  onRegenerate={refreshSection("complianceRules")}
                  regenerating={isSectionGenerating("complianceRules")}
                  disabled={showLoading || isSectionGenerating("complianceRules")}
                />
              ) : <ReportSectionLoading icon="🛡" title="行业合规提醒" />}
            </div>
            <div className="report-grid-wide">
              {isSectionReady("targetUserProfile") ? (
                <TargetProfileCard
                  profile={targetUserProfile}
                  legacyText={legacyTargetUsers}
                  onRegenerate={refreshSection("targetUserProfile")}
                  regenerating={isSectionGenerating("targetUserProfile")}
                  disabled={showLoading || isSectionGenerating("targetUserProfile")}
                />
              ) : <ReportSectionLoading icon="👤" title="目标用户画像" />}
            </div>
            <div className="report-grid-wide">
              {isSectionReady("hotContents") ? (
                <HotContentsCard
                  contents={hotContents}
                  legacyText={legacyHotContent}
                  onRegenerate={refreshSection("hotContents")}
                  regenerating={isSectionGenerating("hotContents")}
                  disabled={showLoading || isSectionGenerating("hotContents")}
                />
              ) : <ReportSectionLoading icon="🔥" title="爆款笔记参考" />}
            </div>
          </div>

          <SourceNotices
            sourceMeta={sourceMeta}
            failedPlatforms={failedPlatforms}
            unsupportedPlatforms={unsupportedPlatforms}
            keywords={keywords}
            generatedAt={generatedAt}
            formatDate={formatReportDate}
          />

          {!showLoading ? (
            <div className="report-cta">
              <div className="report-cta-left">
                <span className="report-cta-icon" aria-hidden="true">🎯</span>
                <span>下一步：参考账号报告，在选题中心生成更贴合定位的内容方向</span>
              </div>
              <button className="btn btn-primary" onClick={() => app.setActivePage("topic")}>去选题中心 ›</button>
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
