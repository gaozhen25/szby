export function formatVideoScriptLines(lines = []) {
  return (Array.isArray(lines) ? lines : [])
    .map((line) => {
      const timeRange = String(line?.timeRange || "").trim();
      const text = String(line?.text || "").trim();
      if (!timeRange && !text) return "";
      return timeRange ? `[${timeRange}] ${text}`.trim() : text;
    })
    .filter(Boolean)
    .join("\n");
}

export function formatShotBreakdownLines(items = []) {
  return (Array.isArray(items) ? items : [])
    .map((item, index) => {
      const shot = item?.shot || index + 1;
      const timeRange = String(item?.timeRange || "").trim();
      const script = String(item?.script || "").trim();
      const visual = String(item?.visualContent || "").trim();
      return [`镜头${shot}`, timeRange, script || visual].filter(Boolean).join(" ");
    })
    .filter(Boolean)
    .join("\n");
}

export function stripHashtagsFromTitle(value = "") {
  return String(value)
    .replace(/#[^#\s]+/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function buildVideoAnalysisDraftFields(result = {}) {
  const copyText = formatVideoScriptLines(result.videoScript || []);
  const scriptOriginalText = formatShotBreakdownLines(result.shotBreakdown || []);
  const firstRewrite = Array.isArray(result.rewriteReferences) ? result.rewriteReferences[0] : null;
  const rewriteLines = Array.isArray(firstRewrite?.script) ? firstRewrite.script.filter(Boolean) : [];
  const replicationPrompt = String(result.replicationPrompt || "").trim();
  const scriptRewrittenText = [...rewriteLines, replicationPrompt ? `\n${replicationPrompt}` : ""]
    .filter(Boolean)
    .join("\n");

  return {
    copyText,
    publishCopy: String(result.publishCopy || "").trim(),
    scriptOriginalText,
    scriptRewrittenText,
  };
}

const normalizeHashtag = (value) => {
  const text = String(value || "").trim();
  if (!text) return "";
  return text.startsWith("#") ? text : `#${text}`;
};

export function buildVideoScriptPackageFromAnalysis(result = {}, options = {}) {
  const videoScript = Array.isArray(result.videoScript) ? result.videoScript : [];
  const shotBreakdown = Array.isArray(result.shotBreakdown) ? result.shotBreakdown : [];
  const hashtags = (Array.isArray(options.hashtags) ? options.hashtags : [])
    .map(normalizeHashtag)
    .filter(Boolean);

  return {
    ...result,
    sourceType: "video_analysis",
    title: String(options.title || result.title || "").trim(),
    draftScript: videoScript
      .map((item) => {
        const timeRange = String(item?.timeRange || "").trim();
        const text = String(item?.text || "").trim();
        return [timeRange ? `[${timeRange}]` : "", text].filter(Boolean).join(" ");
      })
      .filter(Boolean),
    finalScript: shotBreakdown.map((item = {}, index) => ({
      shotNumber: Number(item.shot) || index + 1,
      timeRange: String(item.timeRange || "").trim(),
      narration: String(item.script || "").trim(),
      soundNarration: [item.script, item.bgmSound].map((value) => String(value || "").trim()).filter(Boolean).join("；"),
      purpose: String(item.scriptRole || item.visualRole || "").trim(),
      visual: String(item.visualContent || item.image || "").trim(),
      shotSizeCamera: String(item.shotSizeCamera || "").trim(),
      shootingTechnique: String(item.shootingTechnique || "").trim(),
      subtitle: String(item.subtitle || "").trim(),
      bgmSound: String(item.bgmSound || "").trim(),
    })),
    hashtags,
  };
}
