import { apiClient } from "./client.js";

function uploadError(response) {
  const error = new Error(`OSS 上传失败：${response.status || "网络错误"}`);
  error.status = response.status;
  return error;
}

const CONTENT_TYPE_BY_EXTENSION = {
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".png": "image/png",
  ".webp": "image/webp",
  ".mp4": "video/mp4",
  ".mov": "video/quicktime",
  ".mp3": "audio/mpeg",
  ".m4a": "audio/mp4",
  ".aac": "audio/aac",
  ".wav": "audio/wav",
  ".ogg": "audio/ogg",
};

function resolveContentType(file) {
  const filename = String(file.name || "");
  const extension = filename.includes(".")
    ? `.${filename.split(".").pop().toLowerCase()}`
    : "";
  if (file.type === "image/jpg") return "image/jpeg";
  return file.type || CONTENT_TYPE_BY_EXTENSION[extension] || "application/octet-stream";
}

export async function uploadFileToOss(file, { accountId = null, purpose, signal } = {}) {
  if (!(file instanceof Blob)) {
    throw new TypeError("待上传内容必须是文件");
  }
  const contentType = resolveContentType(file);
  const fallbackExtension = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/aac": ".aac",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/ogg": ".ogg",
  }[contentType] || ".bin";
  const filename = file.name || `upload${fallbackExtension}`;
  const signed = await apiClient.post("/uploads/presign", {
    accountId,
    purpose,
    filename,
    contentType,
    sizeBytes: file.size,
  });
  const response = await fetch(signed.uploadUrl, {
    method: signed.method || "PUT",
    headers: signed.headers || { "Content-Type": contentType },
    body: file,
    signal,
  });
  if (!response.ok) throw uploadError(response);
  return {
    uploadId: signed.uploadId,
    url: signed.objectUrl,
    filename,
    contentType,
    sizeBytes: file.size,
    etag: response.headers?.get?.("ETag")?.replaceAll('"', "") || "",
  };
}

export async function uploadFilesToOss(
  files,
  options = {},
  { concurrency = 3 } = {},
) {
  const queue = Array.from(files || []);
  const results = new Array(queue.length);
  let nextIndex = 0;
  const worker = async () => {
    while (nextIndex < queue.length) {
      const index = nextIndex;
      nextIndex += 1;
      results[index] = await uploadFileToOss(queue[index], options);
    }
  };
  await Promise.all(
    Array.from({ length: Math.min(Math.max(concurrency, 1), queue.length) }, worker),
  );
  return results;
}
