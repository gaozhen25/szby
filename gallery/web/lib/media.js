export function proxy(url, name) {
  if (!url) return "";
  let href = "/api/media?url=" + encodeURIComponent(url);
  if (name) href += "&name=" + encodeURIComponent(name);
  return href;
}

export function fileName(item, media, index) {
  const id = String(item.content_id || "file").replace(/[^\w.-]/g, "") || "file";
  const ext = media.ext || (media.type === "video" ? "mp4" : "jpg");
  return media.type === "video" ? id + "." + ext : id + "-" + (index + 1) + "." + ext;
}

export function fileSrc(file) {
  if (!file) return "";
  if (file.href) return file.href;
  return proxy(file.source_url);
}
