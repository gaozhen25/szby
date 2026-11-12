export const DEFAULT_IMAGE_RATIO = "9:16";

export const SUPPORTED_IMAGE_RATIOS = Object.freeze([
  { value: "1:1", decimal: 1 },
  { value: "3:4", decimal: 3 / 4 },
  { value: "9:16", decimal: 9 / 16 },
  { value: "4:3", decimal: 4 / 3 },
  { value: "16:9", decimal: 16 / 9 },
]);

export function closestSupportedImageRatio(width, height) {
  const safeWidth = Number(width);
  const safeHeight = Number(height);
  if (!(safeWidth > 0) || !(safeHeight > 0)) return DEFAULT_IMAGE_RATIO;

  const actual = safeWidth / safeHeight;
  return SUPPORTED_IMAGE_RATIOS.reduce((closest, candidate) => {
    const distance = Math.abs(Math.log(actual / candidate.decimal));
    const closestDistance = Math.abs(Math.log(actual / closest.decimal));
    return distance < closestDistance ? candidate : closest;
  }).value;
}

function explicitDimensions(source) {
  if (!source || typeof source !== "object") return null;
  const width = source.width ?? source.naturalWidth ?? source.imageWidth;
  const height = source.height ?? source.naturalHeight ?? source.imageHeight;
  return Number(width) > 0 && Number(height) > 0 ? { width, height } : null;
}

function sourceUrl(source) {
  if (typeof source === "string") return source;
  if (!source || typeof source !== "object") return "";
  return source.previewUrl || source.url || source.src || source.originalUrl || "";
}

function loadImageDimensions(source, timeoutMs = 5000) {
  const dimensions = explicitDimensions(source);
  if (dimensions) return Promise.resolve(dimensions);
  if (typeof Image === "undefined") return Promise.reject(new Error("当前环境无法读取图片尺寸"));

  const isBlob = typeof Blob !== "undefined" && source instanceof Blob;
  const url = isBlob ? URL.createObjectURL(source) : sourceUrl(source);
  if (!url) return Promise.reject(new Error("参考图地址为空"));

  return new Promise((resolve, reject) => {
    const image = new Image();
    let settled = false;
    const cleanup = () => {
      window.clearTimeout(timeout);
      image.onload = null;
      image.onerror = null;
      if (isBlob) URL.revokeObjectURL(url);
    };
    const finish = (callback, value) => {
      if (settled) return;
      settled = true;
      cleanup();
      callback(value);
    };
    const timeout = window.setTimeout(
      () => finish(reject, new Error("读取参考图尺寸超时")),
      timeoutMs,
    );
    image.onload = () => finish(resolve, {
      width: image.naturalWidth,
      height: image.naturalHeight,
    });
    image.onerror = () => finish(reject, new Error("无法读取参考图尺寸"));
    image.referrerPolicy = "no-referrer";
    image.src = url;
  });
}

export async function inferImageRatioFromReferences(references = []) {
  const firstReference = (Array.isArray(references) ? references : [references]).find(Boolean);
  if (!firstReference) return DEFAULT_IMAGE_RATIO;

  try {
    const { width, height } = await loadImageDimensions(firstReference);
    return closestSupportedImageRatio(width, height);
  } catch {
    return DEFAULT_IMAGE_RATIO;
  }
}
