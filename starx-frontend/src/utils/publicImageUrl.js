export function browserCompatibleImageUrl(value) {
  try {
    const url = new URL(value);
    const hostname = url.hostname.toLowerCase();
    const isXiaohongshuCdn = hostname === "xhscdn.com" || hostname.endsWith(".xhscdn.com");
    if (url.protocol === "http:" && isXiaohongshuCdn) {
      url.protocol = "https:";
    }
    if (url.protocol !== "https:") return "";
    if (hostname.endsWith(".douyinpic.com") && /\.heic$/i.test(url.pathname)) {
      url.pathname = url.pathname.replace(/\.heic$/i, ".jpeg");
    }
    return url.toString();
  } catch {
    return "";
  }
}
