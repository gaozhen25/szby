const ACTIVE_PUBLISH_STATUSES = new Set(["pending", "queued", "running"]);
const SUPPORTED_VISIBILITIES = new Set(["0", "1", "2"]);
const DEVICE_CONFIGURATION_ERROR_PATTERN = /device|android|publishSettings|设备|发布(?:设置|配置)/i;

export function isPublishDeviceConfigurationError(...messages) {
  return messages.some((message) => (
    DEVICE_CONFIGURATION_ERROR_PATTERN.test(String(message || ""))
  ));
}

export function createWorkflowPublishRequestGate() {
  let epoch = 0;
  const sequences = new Map();

  return {
    begin(channel, accountId) {
      const key = String(channel || "workflow");
      const sequence = (sequences.get(key) || 0) + 1;
      sequences.set(key, sequence);
      return { epoch, key, accountId: String(accountId || ""), sequence };
    },
    isCurrent(token, currentAccountId) {
      return Boolean(
        token
        && token.epoch === epoch
        && token.accountId === String(currentAccountId || "")
        && sequences.get(token.key) === token.sequence
      );
    },
    reset() {
      epoch += 1;
      sequences.clear();
    },
  };
}

function normalizeMediaCandidate(candidate, index, creationType) {
  const fallbackKind = creationType === "video" ? "video" : "image";
  const url = typeof candidate === "string" ? candidate.trim() : String(candidate?.url || "").trim();
  if (!url) return null;

  const kind = candidate?.kind === "video" || candidate?.kind === "image"
    ? candidate.kind
    : fallbackKind;
  const fallbackLabel = kind === "video" ? `视频 ${index + 1}` : `图片 ${index + 1}`;

  const normalized = {
    url,
    kind,
    label: typeof candidate === "object" && candidate?.label
      ? String(candidate.label)
      : fallbackLabel,
  };
  if (typeof candidate === "object" && candidate?.workflowTaskId) {
    normalized.workflowTaskId = String(candidate.workflowTaskId);
  }
  return normalized;
}

function normalizeMediaCandidates(candidates, creationType) {
  if (!Array.isArray(candidates)) return [];
  return candidates
    .map((candidate, index) => normalizeMediaCandidate(candidate, index, creationType))
    .filter(Boolean);
}

function firstNonEmptyText(...values) {
  for (const value of values) {
    const text = String(value || "").trim();
    if (text) return text;
  }
  return "";
}

function appendHashtags(description, hashtags) {
  const copy = String(description || "").trim();
  if (!Array.isArray(hashtags)) return copy;

  const existingHashtags = new Set(copy.match(/#[^\s#，,。！？!?；;]+/gu) || []);
  const normalizedHashtags = [];
  const seenHashtags = new Set();

  for (const value of hashtags) {
    const name = String(value || "").trim().replace(/^#+/u, "");
    if (!name) continue;
    const hashtag = `#${name}`;
    if (existingHashtags.has(hashtag) || seenHashtags.has(hashtag)) continue;
    seenHashtags.add(hashtag);
    normalizedHashtags.push(hashtag);
  }

  if (normalizedHashtags.length === 0) return copy;
  return [copy, normalizedHashtags.join(" ")].filter(Boolean).join("\n\n");
}

function filenameFromUrl(url) {
  const pathname = new URL(url).pathname;
  const encodedName = pathname.split("/").filter(Boolean).at(-1) || "media";
  try {
    return decodeURIComponent(encodedName);
  } catch {
    return encodedName;
  }
}

export function buildWorkflowPublishDraft(creation = {}, task = {}) {
  const creationType = creation.type === "video" ? "video" : "image";
  const persistedCandidates = normalizeMediaCandidates(
    creation.creationState?.publishMediaCandidates,
    creationType,
  );
  const availableCandidates = persistedCandidates.length > 0
    ? persistedCandidates
    : normalizeMediaCandidates(creation.content?.assets, creationType);
  const taskId = String(task.id || "");
  const mediaCandidates = availableCandidates.filter((candidate) => (
    candidate.kind === creationType
    && (!candidate.workflowTaskId || candidate.workflowTaskId === taskId)
  ));
  const httpsMediaUrls = mediaCandidates
    .map((candidate) => candidate.url)
    .filter((url) => /^https:\/\//i.test(url));

  return {
    creationId: String(creation.creationId || task.creationId || ""),
    taskId,
    type: creationType,
    targetPlatform: String(creation.targetPlatform || task.targetPlatform || ""),
    title: firstNonEmptyText(
      creation.content?.title,
      creation.topicTitle,
      task.title,
    ),
    description: appendHashtags(
      firstNonEmptyText(
        creation.creationState?.publishCopy,
        creation.content?.body,
        task.body,
      ),
      creation.content?.hashtags,
    ),
    mediaCandidates,
    selectedMediaUrls: creationType === "image" ? httpsMediaUrls : httpsMediaUrls.slice(0, 1),
    visibility: "0",
    copyToAlbum: true,
    retry: false,
  };
}

export function buildWorkflowPublishPayload(draft = {}) {
  const selectedMediaUrls = (Array.isArray(draft.selectedMediaUrls)
    ? draft.selectedMediaUrls
    : [draft.selectedMediaUrl]
  ).map((url) => String(url || "").trim()).filter(Boolean);
  if (selectedMediaUrls.length === 0) {
    throw new Error("请选择可发布的 HTTPS 素材");
  }
  for (const selectedMediaUrl of selectedMediaUrls) {
    try {
      if (new URL(selectedMediaUrl).protocol !== "https:") {
        throw new Error("invalid protocol");
      }
    } catch {
      throw new Error("请选择可发布的 HTTPS 素材");
    }
  }
  if (draft.type === "video" && selectedMediaUrls.length !== 1) {
    throw new Error("视频发布只能选择一个素材");
  }

  const visibility = String(draft.visibility ?? "0").trim();
  if (!SUPPORTED_VISIBILITIES.has(visibility)) {
    throw new Error("发布可见性仅支持 0（默认公开）、1（好友可见）或 2（仅自己可见）");
  }

  const description = String(draft.description || "").trim();
  if (!description) {
    throw new Error("请填写发布文案后再发布");
  }

  const uploadedAssets = (draft.mediaCandidates || [])
    .filter((candidate) => (
      selectedMediaUrls.includes(candidate.url)
      && candidate.uploadRef?.uploadId
    ))
    .map((candidate) => candidate.uploadRef);

  return {
    targetPlatform: String(draft.targetPlatform || "").trim(),
    assetList: selectedMediaUrls,
    ...(uploadedAssets.length ? { uploadedAssets } : {}),
    filename: filenameFromUrl(selectedMediaUrls[0]),
    title: String(draft.title || "").trim(),
    description,
    visibility,
    copyToAlbum: draft.copyToAlbum !== false,
    retry: draft.retry === true,
  };
}

export function isWorkflowPublishActive(status) {
  return ACTIVE_PUBLISH_STATUSES.has(status);
}
