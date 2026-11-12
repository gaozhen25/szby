import { DEFAULT_IMAGE_RATIO } from "./imageAspectRatio.js";

export function addUniqueJobId(jobIds, jobId) {
  if (!jobId || jobIds.includes(jobId)) return jobIds;
  return [...jobIds, jobId];
}

export function extractJobImages(job) {
  const rawImages = Array.isArray(job?.resultPayload?.images) ? job.resultPayload.images : [];
  return rawImages
    .map((image) => {
      if (typeof image === "string") return { url: image, meta: {} };
      if (image && typeof image.url === "string") return { url: image.url, meta: image };
      return null;
    })
    .filter(Boolean);
}

export function buildCanvasNodes(generationJobs, canvasJobIds) {
  const jobsById = new Map(generationJobs.map((job) => [job.id, job]));
  return canvasJobIds
    .map((jobId, index) => {
      const job = jobsById.get(jobId);
      if (!job || job.jobType !== "image") return null;
      return {
        id: job.id,
        batchIndex: index,
        title: job.topicTitle || `图片任务 ${index + 1}`,
        status: job.status,
        prompt: job.prompt || "",
        ratio: job.ratio || DEFAULT_IMAGE_RATIO,
        requestedCount: job.requestedCount || 1,
        error: job.error || "",
        createdAt: job.createdAt || "",
        images: extractJobImages(job),
      };
    })
    .filter(Boolean)
    .map((node, index) => ({
      ...node,
      x: (index % 3) * 400 + 60,
      y: Math.floor(index / 3) * 340 + 44,
    }));
}

export function getSelectedFavoriteImages(favorites, selectedKeys) {
  return favorites.filter((favorite) => selectedKeys.has(favorite.key));
}
