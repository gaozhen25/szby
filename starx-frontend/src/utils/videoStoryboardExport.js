import { normalizeVideoShootingSegments } from "./videoScriptPackage.js";

const CSV_COLUMNS = [
  ["镜号", "shotNumber"],
  ["时间", "timeRange"],
  ["景别 / 机位", "shotSizeCamera"],
  ["画面内容", "visual"],
  ["声音 / 旁白", "soundNarration"],
  ["拍摄 / 运镜", "shootingTechnique"],
  ["字幕", "subtitle"],
];

function csvCell(value) {
  return `"${String(value ?? "").replaceAll('"', '""')}"`;
}

export function buildVideoStoryboardCsv(packageResult = {}) {
  const segments = normalizeVideoShootingSegments(packageResult);
  const rows = [
    ["视频标题", packageResult.title || ""],
    ["开场钩子", packageResult.hookSuggestion || ""],
    [],
    CSV_COLUMNS.map(([label]) => label),
    ...segments.map((segment) => CSV_COLUMNS.map(([, key]) => segment[key] || "")),
  ];
  return `\uFEFF${rows.map((row) => row.map(csvCell).join(",")).join("\r\n")}`;
}

function safeFilename(value) {
  return String(value || "视频分镜脚本")
    .replace(/[\\/:*?"<>|]/g, "-")
    .trim()
    .slice(0, 60) || "视频分镜脚本";
}

export function downloadVideoStoryboardCsv(packageResult = {}) {
  const blob = new Blob([buildVideoStoryboardCsv(packageResult)], {
    type: "text/csv;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${safeFilename(packageResult.title)}-分镜脚本.csv`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
