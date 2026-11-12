function safeFilename(filename, fallback = "starx-media") {
  return String(filename || fallback).replace(/[\\/:*?"<>|]+/g, "_");
}

function triggerBlobDownload(blob, filename) {
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = safeFilename(filename);
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}

export async function downloadMedia(url, filename = "starx-media") {
  const cleanUrl = String(url || "").trim();
  if (!cleanUrl) return false;

  const safeName = safeFilename(filename);

  try {
    const response = await fetch(cleanUrl, { mode: "cors" });
    if (!response.ok) throw new Error(`download failed: ${response.status}`);
    const blob = await response.blob();
    triggerBlobDownload(blob, safeName);
    return true;
  } catch {
    const anchor = document.createElement("a");
    anchor.href = cleanUrl;
    anchor.download = safeName;
    anchor.target = "_blank";
    anchor.rel = "noopener noreferrer";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    return false;
  }
}

/** Pack media URLs into a single zip and download. Returns { successCount, total }. */
export async function downloadMediaZip(items = [], zipFilename = "starx-materials.zip") {
  const list = (Array.isArray(items) ? items : [])
    .map((item, index) => {
      if (typeof item === "string") {
        return { url: item, filename: `starx-parse-${index + 1}.png` };
      }
      return {
        url: String(item?.url || "").trim(),
        filename: safeFilename(item?.filename || `starx-parse-${index + 1}.png`),
      };
    })
    .filter((item) => item.url);

  if (!list.length) return { successCount: 0, total: 0 };

  const { default: JSZip } = await import("jszip");
  const zip = new JSZip();
  const usedNames = new Set();
  let successCount = 0;

  for (const item of list) {
    try {
      const response = await fetch(item.url, { mode: "cors" });
      if (!response.ok) throw new Error(`download failed: ${response.status}`);
      const blob = await response.blob();
      let name = item.filename;
      if (usedNames.has(name)) {
        const dot = name.lastIndexOf(".");
        const base = dot > 0 ? name.slice(0, dot) : name;
        const ext = dot > 0 ? name.slice(dot) : "";
        let n = 2;
        while (usedNames.has(`${base}-${n}${ext}`)) n += 1;
        name = `${base}-${n}${ext}`;
      }
      usedNames.add(name);
      zip.file(name, blob);
      successCount += 1;
    } catch {
      // skip CORS / network failures; report via counts
    }
  }

  if (successCount === 0) return { successCount: 0, total: list.length };

  const zipBlob = await zip.generateAsync({ type: "blob" });
  triggerBlobDownload(zipBlob, safeFilename(zipFilename, "starx-materials.zip"));
  return { successCount, total: list.length };
}

export function guessMediaFilename(url, fallback = "starx-media") {
  try {
    const pathname = new URL(String(url || ""), "https://example.invalid").pathname;
    const leaf = pathname.split("/").filter(Boolean).pop() || "";
    if (leaf && /\.[a-z0-9]{2,5}$/i.test(leaf)) return leaf.split("?")[0];
  } catch {
    // keep fallback
  }
  return fallback;
}

function guessVideoMime(url) {
  const lower = String(url || "").toLowerCase();
  if (lower.includes(".webm")) return "video/webm";
  if (lower.includes(".mov")) return "video/quicktime";
  return "video/mp4";
}

export function createImageSlide(url, { title = "", downloadFilename } = {}) {
  const src = String(url || "").trim();
  if (!src) return null;
  return {
    type: "image",
    src,
    title,
    downloadFilename: downloadFilename || guessMediaFilename(src, "starx-image.png"),
  };
}

export function createVideoSlide(url, { title = "", poster = "", downloadFilename } = {}) {
  const src = String(url || "").trim();
  if (!src) return null;
  return {
    type: "video",
    title,
    poster: poster || undefined,
    sources: [{ src, type: guessVideoMime(src) }],
    downloadFilename: downloadFilename || guessMediaFilename(src, "starx-video.mp4"),
  };
}

export function createMediaSlides(items = []) {
  return (Array.isArray(items) ? items : [])
    .map((item) => {
      if (!item) return null;
      if (item.type === "video") {
        return createVideoSlide(item.url || item.src, {
          title: item.title || item.label || "",
          poster: item.poster || item.cover || "",
          downloadFilename: item.downloadFilename,
        });
      }
      return createImageSlide(item.url || item.src, {
        title: item.title || item.label || "",
        downloadFilename: item.downloadFilename,
      });
    })
    .filter(Boolean);
}
