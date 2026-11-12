import {
  asArray,
  formatMetric,
  formatReportDate,
  metricEntries,
  metricLabel,
  resolvePlatformDisplay,
} from "./accountReport";

const SECTION_TITLES = {
  similarAccounts: "01 相似账号洞察",
  complianceRules: "02 行业合规提醒",
  targetUserProfile: "03 目标用户画像",
  hotContents: "04 爆款内容参考",
};

function cleanText(value, fallback = "") {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  return text || fallback;
}

function safeFilePart(value) {
  return cleanText(value, "账号报告")
    .replace(/[\\/:*?"<>|#%&{}$!'@+=`~\s]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 64) || "账号报告";
}

function escapeMarkdown(value) {
  return cleanText(value).replace(/\|/g, "\\|");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function formatPlatforms(platforms) {
  return asArray(platforms)
    .map((platform) => resolvePlatformDisplay(platform).label)
    .filter(Boolean)
    .join("、");
}

function formatMetrics(metrics) {
  return metricEntries(metrics)
    .map(([key, value]) => `${metricLabel(key)} ${formatMetric(value)}`)
    .join(" · ");
}

function formatReportDateForFile(value) {
  const date = value ? new Date(value) : new Date();
  if (Number.isNaN(date.getTime())) return "unknown-date";
  const pad = (number) => String(number).padStart(2, "0");
  return [
    date.getFullYear(),
    pad(date.getMonth() + 1),
    pad(date.getDate()),
  ].join("-");
}

function riskLabel(value) {
  return {
    high: "高风险",
    medium: "中风险",
    low: "低风险",
    "高": "高风险",
    "中": "中风险",
    "低": "低风险",
  }[String(value || "")] || "需关注";
}

function compactSourceSummary(sourceMeta) {
  const platformText = formatPlatforms(sourceMeta.platforms) || "未记录";
  const keywordText = asArray(sourceMeta.keywords).join("、") || "未记录";
  const sampleText = formatMetric(sourceMeta.sampleCount || 0);
  return `${platformText} · ${keywordText} · ${sampleText} 个公开样本`;
}

function createReportHighlights({ report, reportView, sourceMeta }) {
  const similarCount = reportView.similarAccounts.length;
  const complianceCount = asArray(report.complianceRules).length;
  const profileCount = asArray(report.targetUserProfile?.categories).length;
  const hotCount = reportView.hotContents.length;
  const failedCount = asArray(sourceMeta.failedPlatforms).length;
  return [
    {
      label: "相似账号",
      value: similarCount ? `${similarCount} 个` : "待补充",
      note: similarCount ? "可用于竞品监控与内容定位参考" : "暂无足够公开账号样本",
    },
    {
      label: "合规提醒",
      value: complianceCount ? `${complianceCount} 条` : "待补充",
      note: complianceCount ? "优先复核高风险表达与替代表述" : "暂无行业合规规则",
    },
    {
      label: "用户画像",
      value: profileCount ? `${profileCount} 类` : "待补充",
      note: profileCount ? "按购买动机、场景与性别差异拆分" : "暂无结构化用户画像",
    },
    {
      label: "爆款样本",
      value: hotCount ? `${hotCount} 条` : "待补充",
      note: hotCount ? "用于选题、标题和内容结构参考" : "暂无高互动公开内容样本",
    },
    {
      label: "数据状态",
      value: failedCount ? "部分采集受限" : "采集完成",
      note: compactSourceSummary(sourceMeta),
    },
  ];
}

function createExportMeta({ account, reportView }) {
  const report = reportView.report || {};
  const sourceMeta = reportView.sourceMeta || {};
  const accountName = cleanText(account?.name, "未知账号");
  const industry = cleanText(account?.industry, "未设置行业");
  const platformText = formatPlatforms(account?.platforms) || resolvePlatformDisplay(account?.platform).label;
  const generatedAt = report.generatedAt;
  return {
    title: `${accountName} 账号专业报告`,
    accountName,
    industry,
    platformText,
    description: cleanText(account?.description),
    purpose: cleanText(account?.purpose),
    generatedAt,
    generatedAtText: formatReportDate(generatedAt),
    exportedAtText: formatReportDate(new Date().toISOString()),
    reportVersion: Number(report.reportVersion || 0),
    fileNameBase: `${safeFilePart(accountName)}-账号报告-${formatReportDateForFile(generatedAt)}`,
    sourceMeta,
  };
}

function buildMarkdown({ account, reportView }) {
  const report = reportView.report || {};
  const meta = createExportMeta({ account, reportView });
  const sourceMeta = meta.sourceMeta;
  const highlights = createReportHighlights({ report, reportView, sourceMeta });
  const similarAccounts = reportView.similarAccounts;
  const complianceRules = asArray(report.complianceRules);
  const profile = report.targetUserProfile || {};
  const hotContents = reportView.hotContents;
  const keywords = asArray(sourceMeta.keywords).join("、") || "未记录";
  const sourcePlatforms = formatPlatforms(sourceMeta.platforms) || "未记录";
  const failedPlatforms = asArray(sourceMeta.failedPlatforms);
  const unsupportedPlatforms = asArray(sourceMeta.unsupportedPlatforms);
  const lines = [
    `# ${meta.title}`,
    "",
    `> 一份面向内容定位、竞品参考、合规复核和选题决策的账号分析报告。生成时间：${meta.generatedAtText} · 导出时间：${meta.exportedAtText}`,
    "",
    "## 核心概览",
    "",
    "| 项目 | 内容 |",
    "| --- | --- |",
    `| 账号 | ${escapeMarkdown(meta.accountName)} |`,
    `| 行业 | ${escapeMarkdown(meta.industry)} |`,
    `| 平台 | ${escapeMarkdown(meta.platformText || "未设置平台")} |`,
    `| 报告版本 | v${meta.reportVersion} |`,
    meta.description ? `| 账号描述 | ${escapeMarkdown(meta.description)} |` : "",
    meta.purpose ? `| 经营目标 | ${escapeMarkdown(meta.purpose)} |` : "",
    "",
    "## 关键发现",
    "",
    "| 维度 | 状态 | 解读 |",
    "| --- | --- | --- |",
    ...highlights.map((item) => `| ${escapeMarkdown(item.label)} | ${escapeMarkdown(item.value)} | ${escapeMarkdown(item.note)} |`),
    "",
    "## 目录",
    "",
    `- [${SECTION_TITLES.similarAccounts}](#${SECTION_TITLES.similarAccounts.replace(/\s+/g, "-").toLowerCase()})`,
    `- [${SECTION_TITLES.complianceRules}](#${SECTION_TITLES.complianceRules.replace(/\s+/g, "-").toLowerCase()})`,
    `- [${SECTION_TITLES.targetUserProfile}](#${SECTION_TITLES.targetUserProfile.replace(/\s+/g, "-").toLowerCase()})`,
    `- [${SECTION_TITLES.hotContents}](#${SECTION_TITLES.hotContents.replace(/\s+/g, "-").toLowerCase()})`,
    "- [报告来源说明](#报告来源说明)",
    "",
    `## ${SECTION_TITLES.similarAccounts}`,
    "",
    similarAccounts.length
      ? `本节展示与当前账号定位、内容形态或受众特征接近的公开账号样本，共 ${similarAccounts.length} 个。`
      : "本节暂无足够公开相似账号样本，建议完善账号主页链接或重新生成报告。",
    "",
  ].filter((line) => line !== "");

  if (similarAccounts.length) {
    lines.push("| 账号 | 平台 | 相似原因 | 代表指标 | 代表内容 |");
    lines.push("| --- | --- | --- | --- | --- |");
    similarAccounts.slice(0, 20).forEach((accountItem) => {
      const name = accountItem.safeProfileUrl
        ? `[${escapeMarkdown(accountItem.name || "未命名账号")}](${accountItem.safeProfileUrl})`
        : escapeMarkdown(accountItem.name || "未命名账号");
      lines.push([
        name,
        escapeMarkdown(resolvePlatformDisplay(accountItem.platform).label),
        escapeMarkdown(accountItem.similarityReason || "暂无"),
        escapeMarkdown(formatMetrics(accountItem.metrics) || "-"),
        escapeMarkdown(asArray(accountItem.representativeContents).join("；") || "-"),
      ].join(" | ").replace(/^/, "| ").replace(/$/, " |"));
    });
  } else {
    lines.push(cleanText(report.competitors, "暂无相似账号样本"));
  }

  lines.push("", `## ${SECTION_TITLES.complianceRules}`, "");
  lines.push(complianceRules.length
    ? "以下表达适合在脚本、标题、封面文案和评论区回复中优先避让。"
    : "暂无结构化合规规则，建议结合行业和平台官方规则人工复核。");
  lines.push("");
  if (complianceRules.length) {
    lines.push("| 风险等级 | 风险表达 | 原因 | 建议替换 | 平台 |");
    lines.push("| --- | --- | --- | --- | --- |");
    complianceRules.forEach((rule) => {
      lines.push(`| ${escapeMarkdown(riskLabel(rule.riskLevel))} | ${escapeMarkdown(rule.expression || "-")} | ${escapeMarkdown(rule.reason || "-")} | ${escapeMarkdown(rule.suggestion || "-")} | ${escapeMarkdown(formatPlatforms(rule.platforms) || "通用")} |`);
    });
  } else {
    lines.push(cleanText(report.prohibitedWords, "暂无合规规则"));
  }

  lines.push("", `## ${SECTION_TITLES.targetUserProfile}`, "");
  lines.push("用户画像用于判断内容应优先服务谁、解决什么问题，以及哪些人群暂时不应作为主攻方向。");
  lines.push("");
  if (profile.assumption) lines.push(`**分析假设：** ${cleanText(profile.assumption)}`, "");
  const categories = asArray(profile.categories);
  if (categories.length) {
    categories.forEach((category, index) => {
      lines.push(`### ${index + 1}. ${cleanText(category.categoryName, "用户类别")}`);
      lines.push("");
      lines.push(`- 购买动机：${cleanText(category.purchaseMotivation, "暂无")}`);
      if (category.specificProfile) lines.push(`- 具体画像：${cleanText(category.specificProfile)}`);
      if (category.maleProfile?.description) lines.push(`- 男性画像：${cleanText(category.maleProfile.description)}`);
      if (category.femaleProfile?.description) lines.push(`- 女性画像：${cleanText(category.femaleProfile.description)}`);
      lines.push("");
    });
  } else {
    lines.push(cleanText(profile.summary || report.targetUsers, "暂无目标用户画像"));
  }
  if (profile.priorityRanking?.priorityCategory) {
    lines.push(`**优先服务用户：** ${cleanText(profile.priorityRanking.priorityCategory)}。${cleanText(profile.priorityRanking.priorityReason)}`, "");
  }
  if (profile.positioningReminder?.commonMisjudgment || profile.positioningReminder?.hypothesisToValidate) {
    lines.push("**定位提醒**");
    if (profile.positioningReminder.commonMisjudgment) {
      lines.push(`- 判断误区：${cleanText(profile.positioningReminder.commonMisjudgment)}`);
    }
    if (profile.positioningReminder.hypothesisToValidate) {
      lines.push(`- 待验证假设：${cleanText(profile.positioningReminder.hypothesisToValidate)}`);
    }
    lines.push("");
  }

  lines.push(`## ${SECTION_TITLES.hotContents}`, "");
  lines.push(hotContents.length
    ? "以下公开高互动内容可作为选题方向、标题结构、封面表达和内容节奏的参考。"
    : "暂无足够公开爆款内容样本，建议补充平台主页或扩大关键词范围后重新生成。");
  lines.push("");
  if (hotContents.length) {
    hotContents.slice(0, 20).forEach((content, index) => {
      const title = cleanText(content.title, "未命名内容");
      const titleWithLink = content.safeUrl ? `[${escapeMarkdown(title)}](${content.safeUrl})` : escapeMarkdown(title);
      lines.push(`### ${index + 1}. ${titleWithLink}`);
      lines.push("");
      lines.push(`- 平台：${resolvePlatformDisplay(content.platform).label}`);
      lines.push(`- 入选原因：${cleanText(content.selectionReason, "高互动公开内容")}`);
      const metrics = formatMetrics(content.metrics && typeof content.metrics === "object" ? content.metrics : content);
      if (metrics) lines.push(`- 公开指标：${metrics}`);
      lines.push("");
    });
  } else {
    lines.push(cleanText(report.hotContent, "暂无爆款内容样本"));
  }

  lines.push("## 报告来源说明", "");
  lines.push(`- 数据平台：${sourcePlatforms}`);
  lines.push(`- 关键词：${keywords}`);
  lines.push(`- 公开样本：${formatMetric(sourceMeta.sampleCount || 0)}`);
  if (unsupportedPlatforms.length) lines.push(`- 暂不支持采集平台：${unsupportedPlatforms.join("、")}`);
  failedPlatforms.forEach((failure) => {
    lines.push(`- 采集提示：${cleanText(failure.platform, "部分平台")} - ${cleanText(failure.reason || failure.message, "公开内容采集失败")}`);
  });
  lines.push("", "> 使用提示：本报告基于账号档案与可采集公开内容生成。涉及平台规则、投放承诺、医疗/金融/教育等敏感行业表达时，请以平台最新官方规范和专业合规意见为准。");

  return `${lines.join("\n").replace(/\n{3,}/g, "\n\n")}\n`;
}

function splitMarkdownCover(markdown) {
  const lines = markdown.split("\n");
  let start = 0;
  if (lines[start]?.startsWith("# ")) start += 1;
  while (!lines[start]?.trim() && start < lines.length) start += 1;
  if (lines[start]?.startsWith("> ")) start += 1;
  while (!lines[start]?.trim() && start < lines.length) start += 1;
  return lines.slice(start).join("\n");
}

function renderParagraphs(markdown) {
  const lines = markdown.split("\n");
  const html = [];
  let index = 0;

  const inline = (value) => escapeHtml(value)
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g, '<a href="$2">$1</a>');

  const readTable = () => {
    const tableLines = [];
    while (index < lines.length && lines[index].startsWith("| ")) {
      tableLines.push(lines[index]);
      index += 1;
    }
    const rows = tableLines
      .filter((line) => !/^\|\s*-+/.test(line))
      .map((line) => line.slice(1, -1).split("|").map((cell) => cell.trim()));
    if (!rows.length) return "";
    const [head, ...body] = rows;
    return `<table><thead><tr>${head.map((cell) => `<th>${inline(cell)}</th>`).join("")}</tr></thead><tbody>${body.map((row) => `<tr>${row.map((cell) => `<td>${inline(cell)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  };

  const readList = () => {
    const items = [];
    while (index < lines.length && lines[index].startsWith("- ")) {
      items.push(`<li>${inline(lines[index].slice(2))}</li>`);
      index += 1;
    }
    return `<ul>${items.join("")}</ul>`;
  };

  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
    } else if (line.startsWith("# ")) {
      html.push(`<h1>${inline(line.slice(2))}</h1>`);
      index += 1;
    } else if (line.startsWith("## ")) {
      html.push(`<h2>${inline(line.slice(3))}</h2>`);
      index += 1;
    } else if (line.startsWith("### ")) {
      html.push(`<h3>${inline(line.slice(4))}</h3>`);
      index += 1;
    } else if (line.startsWith("> ")) {
      html.push(`<blockquote>${inline(line.slice(2))}</blockquote>`);
      index += 1;
    } else if (line.startsWith("- ")) {
      html.push(readList());
    } else if (line.startsWith("| ")) {
      html.push(readTable());
    } else {
      html.push(`<p>${inline(line)}</p>`);
      index += 1;
    }
  }

  return html.join("\n");
}

function createPrintHtml(markdown, meta) {
  const report = { sourceMeta: meta.sourceMeta };
  const sourceSummary = compactSourceSummary(meta.sourceMeta);
  const coverItems = [
    ["账号", meta.accountName],
    ["行业", meta.industry],
    ["平台", meta.platformText || "未设置平台"],
    ["报告版本", `v${meta.reportVersion}`],
    ["生成时间", meta.generatedAtText],
    ["导出时间", meta.exportedAtText],
  ];
  const highlights = createReportHighlights({ report, reportView: { similarAccounts: [], hotContents: [] }, sourceMeta: meta.sourceMeta });
  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>${escapeHtml(meta.title)}</title>
  <style>
    @page { size: A4; margin: 16mm 15mm; }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: #142033;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      line-height: 1.65;
      background: #eef2f7;
    }
    main { max-width: 920px; margin: 0 auto; background: #fff; box-shadow: 0 24px 70px rgba(15, 23, 42, 0.12); }
    .cover {
      min-height: 245px;
      padding: 34px 34px 28px;
      color: #fff;
      background:
        linear-gradient(135deg, rgba(12, 45, 86, 0.96), rgba(28, 82, 132, 0.92)),
        linear-gradient(45deg, #0f2f57, #2563eb);
    }
    .eyebrow { margin: 0 0 22px; font-size: 11px; font-weight: 800; letter-spacing: 0.24em; text-transform: uppercase; opacity: 0.78; }
    h1 { max-width: 760px; margin: 0; font-size: 34px; line-height: 1.18; letter-spacing: 0; }
    .cover-subtitle { max-width: 680px; margin: 14px 0 0; color: rgba(255, 255, 255, 0.78); font-size: 14px; }
    .cover-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-top: 28px; }
    .cover-card { min-height: 64px; padding: 11px 12px; border: 1px solid rgba(255, 255, 255, 0.2); border-radius: 12px; background: rgba(255, 255, 255, 0.1); }
    .cover-card span { display: block; color: rgba(255, 255, 255, 0.66); font-size: 11px; }
    .cover-card strong { display: block; margin-top: 4px; color: #fff; font-size: 13px; font-weight: 700; }
    .content { padding: 28px 34px 36px; }
    h2 { margin: 30px 0 12px; padding-top: 18px; border-top: 1px solid #dbe3ef; color: #0f2f57; font-size: 20px; line-height: 1.35; letter-spacing: 0; }
    h2:first-child { margin-top: 0; padding-top: 0; border-top: 0; }
    h3 { margin: 20px 0 8px; color: #223047; font-size: 15px; }
    p, li { color: #334155; font-size: 13px; }
    blockquote { margin: 0 0 22px; padding: 10px 14px; color: #526070; background: #f1f5f9; border-left: 4px solid #2563eb; }
    ul { margin: 8px 0 12px; padding-left: 20px; }
    table { width: 100%; margin: 12px 0 20px; border-collapse: separate; border-spacing: 0; table-layout: fixed; border: 1px solid #dbe3ef; border-radius: 12px; overflow: hidden; }
    th { color: #475569; font-weight: 700; background: #f6f8fb; }
    th, td { padding: 9px 10px; border-right: 1px solid #dbe3ef; border-bottom: 1px solid #dbe3ef; font-size: 12px; line-height: 1.55; vertical-align: top; overflow-wrap: anywhere; }
    tr:last-child td { border-bottom: 0; }
    th:last-child, td:last-child { border-right: 0; }
    tbody tr:nth-child(even) td { background: #fbfcfe; }
    a { color: #1d4ed8; text-decoration: none; }
    strong { color: #111827; }
    .footer-note { margin-top: 30px; padding-top: 12px; border-top: 1px solid #dbe3ef; color: #64748b; font-size: 11px; }
    @media print {
      body { background: #fff; }
      main { box-shadow: none; }
      .cover { min-height: 220px; print-color-adjust: exact; -webkit-print-color-adjust: exact; }
      .content { padding: 24px 0 0; }
      h2 { break-after: avoid; }
      h3 { break-after: avoid; }
      table { break-inside: avoid; }
    }
  </style>
</head>
<body>
  <main>
    <section class="cover">
      <p class="eyebrow">ACCOUNT INTELLIGENCE REPORT</p>
      <h1>${escapeHtml(meta.title)}</h1>
      <p class="cover-subtitle">面向内容定位、竞品参考、合规复核和选题决策的专业账号分析报告。</p>
      <div class="cover-grid">
        ${coverItems.map(([label, value]) => `<div class="cover-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("")}
      </div>
    </section>
    <section class="content">
      ${renderParagraphs(splitMarkdownCover(markdown))}
      <p class="footer-note">数据摘要：${escapeHtml(sourceSummary)}。报告由 StarX 根据账号档案与可采集公开内容生成。</p>
    </section>
  </main>
  <script>
    window.addEventListener("load", () => {
      window.focus();
      window.print();
    });
  </script>
</body>
</html>`;
}

export function createAccountReportExport({ account, reportView }) {
  const markdown = buildMarkdown({ account, reportView });
  const meta = createExportMeta({ account, reportView });
  return {
    fileNameBase: meta.fileNameBase,
    markdown,
    html: createPrintHtml(markdown, meta),
  };
}

export function downloadAccountReportMarkdown(exportPayload) {
  const blob = new Blob([exportPayload.markdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${exportPayload.fileNameBase}.md`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function printAccountReportPdf(exportPayload) {
  const printWindow = window.open("", "_blank", "width=960,height=720");
  if (!printWindow) return false;
  printWindow.opener = null;
  printWindow.document.open();
  printWindow.document.write(exportPayload.html);
  printWindow.document.close();
  return true;
}
