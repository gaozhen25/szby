export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}

export function platformName(value) {
  if (value === "xhs") return "小红书";
  if (value === "douyin") return "抖音";
  return "未知";
}

export function kindName(value) {
  return { image: "图文", video: "视频", mixed: "混合" }[value] || "其他";
}

export function shortStoreError(error) {
  const text = String(error || "");
  if (!text) return "未写入 OSS";
  if (text.includes("does not belong") || text.includes("bucket acl") || text.includes("AccessDenied")) {
    return "OSS 拒绝写入：AccessKey 不是这个桶的主人";
  }
  return text.length > 96 ? text.slice(0, 96) + "…" : text;
}
