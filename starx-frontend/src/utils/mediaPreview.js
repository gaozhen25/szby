const AWEME_PLAYBACK_PATH = /^\/aweme\/v1\/play(?:wm)?\//;

export function buildVideoPreviewUrl(sourceUrl, cacheKey = Date.now()) {
  const cleanUrl = String(sourceUrl || "").trim();
  if (!cleanUrl) return "";

  try {
    const parsed = new URL(cleanUrl);
    if (!AWEME_PLAYBACK_PATH.test(parsed.pathname)) return cleanUrl;
    parsed.searchParams.set("starx_preview", String(cacheKey));
    return parsed.toString();
  } catch {
    return cleanUrl;
  }
}
