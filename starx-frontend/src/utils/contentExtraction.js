export function extractHashTags(text = "") {
  const matches = String(text).match(/#[\p{L}\p{N}_-]+/gu) || [];
  return [...new Set(matches)];
}

export function stripHashTagsFromDescription(text = "") {
  return String(text)
    .replace(/#[\p{L}\p{N}_-]+(?:\s*\[话题\]\s*#?)?/gu, "")
    .replace(/[ \t]{2,}/g, " ")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n[ \t]+/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export function buildFieldsFromExtract(result = {}) {
  const title = result.title?.trim() || "";
  const description = result.description?.trim() || "";
  const hashtags = Array.isArray(result.hashtags) && result.hashtags.length
    ? result.hashtags
    : extractHashTags(`${title} ${description}`);

  return {
    title,
    body: stripHashTagsFromDescription(description),
    hashtags,
  };
}
