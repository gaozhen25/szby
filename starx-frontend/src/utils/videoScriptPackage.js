const hasOwn = (value, key) => Boolean(value) && Object.prototype.hasOwnProperty.call(value, key);

function readFinalScriptLine(item) {
  const narration = String(item?.narration || "").trim();
  if (narration) return narration;
  return String(item?.text || "").trim();
}

const shootingText = (value) => String(value || "").trim();

export function normalizeVideoShootingSegments(result = {}) {
  const finalScript = Array.isArray(result?.finalScript) ? result.finalScript : [];
  const shotBreakdown = Array.isArray(result?.shotBreakdown) ? result.shotBreakdown : [];
  const source = finalScript.length ? finalScript : shotBreakdown;
  return source.map((item = {}, index) => ({
    shotNumber: Number(item.shotNumber || item.shot_number || item.shot) || index + 1,
    timeRange: shootingText(item.timeRange),
    narration: shootingText(readFinalScriptLine(item) || item.script),
    soundNarration: shootingText(
      item.soundNarration
      || item.sound_narration
      || [readFinalScriptLine(item) || item.script, item.bgmSound || item.bgm_sound].filter(Boolean).join("；")
    ),
    purpose: shootingText(item.purpose || item.scriptRole || item.visualRole),
    visual: shootingText(item.visual || item.visualContent || item.image),
    shotSizeCamera: shootingText(item.shotSizeCamera || item.shot_size_camera),
    shootingTechnique: shootingText(item.shootingTechnique || item.shooting_technique),
    subtitle: shootingText(item.subtitle),
    bgmSound: shootingText(item.bgmSound || item.bgm_sound),
  }));
}

export function buildVideoScriptDraftFields(result = {}) {
  const finalScript = Array.isArray(result.finalScript) ? result.finalScript : [];
  const finalText = finalScript
    .map(readFinalScriptLine)
    .filter(Boolean)
    .join("\n");

  return {
    title: String(result.title || "").trim(),
    draftText: (Array.isArray(result.draftScript) ? result.draftScript : []).map(String).join("\n"),
    finalText,
    body: finalText,
    publishCopy: String(result.publishCopy || "").trim(),
    hashtagsText: (Array.isArray(result.hashtags) ? result.hashtags : []).join(" "),
    bgmSuggestion: String(result.bgmSuggestion || "").trim(),
  };
}

export function resolveActiveVideoScriptJobId(currentId, incomingId) {
  return String(currentId || "").trim() || String(incomingId || "").trim();
}

export function applyAutostartVideoScriptJobResult(
  currentCreation,
  { creationId, jobId, preferences = {} } = {}
) {
  if (!currentCreation || currentCreation.creationId !== creationId) return currentCreation;
  const currentJobId = String(currentCreation.creationState?.activeVideoScriptJobId || "").trim();
  const autostartJobId = String(jobId || "").trim();
  if (!autostartJobId || (currentJobId && currentJobId !== autostartJobId)) return currentCreation;

  return {
    ...currentCreation,
    creationState: {
      ...(currentCreation.creationState || {}),
      activeVideoScriptJobId: autostartJobId,
      videoScriptTargetPlatform: preferences.targetPlatform,
      videoScriptDurationSeconds: preferences.durationSeconds,
      videoScriptContentGoal: preferences.contentGoal,
      videoScriptFormat: preferences.videoFormat,
      videoScriptToneStyle: preferences.toneStyle,
      videoScriptCustomRequirements: preferences.customRequirements,
    },
  };
}

export function advanceVideoScriptRefreshFailure(currentCount, error, limit = 3) {
  const count = Math.max(0, Number(currentCount) || 0) + 1;
  return {
    count,
    blocked: count >= limit,
    message: String(error?.message || error || "视频脚本任务加载失败"),
  };
}

export function shouldApplyLegacyScriptRewrite({
  creationType,
  activeVideoScriptJobId,
  trackedScriptRewriteJobId,
  completedJobId,
  legacyVideoFlowActive,
} = {}) {
  if (!trackedScriptRewriteJobId || completedJobId !== trackedScriptRewriteJobId) return false;
  return creationType !== "video" || (Boolean(legacyVideoFlowActive) && !activeVideoScriptJobId);
}

export function resolveCreationTargetPlatform(creationType, currentTargetPlatform, videoTargetPlatform) {
  if (creationType === "video" && String(videoTargetPlatform || "").trim()) {
    return String(videoTargetPlatform).trim();
  }
  return String(currentTargetPlatform || "").trim();
}

export function buildPersistedVideoScriptPackage(result, editable = {}) {
  const packageResult = result && typeof result === "object" && !Array.isArray(result) ? result : {};
  return {
    ...packageResult,
    editableTitle: String(editable.title ?? ""),
    editableDraftText: String(editable.draftText ?? ""),
    editableFinalText: String(editable.finalText ?? ""),
    editableBody: String(editable.body ?? ""),
    editablePublishCopy: String(editable.publishCopy ?? ""),
    editableHashtagsText: String(editable.hashtagsText ?? ""),
    editableBgmSuggestion: String(editable.bgmSuggestion ?? ""),
  };
}

export function restoreVideoScriptDraft({ packageResult, content = {}, videoPublishText, topicTitle = "" } = {}) {
  const fields = buildVideoScriptDraftFields(packageResult || {});
  const contentDraftText = Array.isArray(content.scriptOriginal) ? content.scriptOriginal.map(String).join("\n") : "";
  const contentFinalText = Array.isArray(content.scriptRewritten) ? content.scriptRewritten.map(String).join("\n") : "";
  const contentHashtagsText = Array.isArray(content.hashtags) ? content.hashtags.map(String).join(" ") : "";

  return {
    title: hasOwn(packageResult, "editableTitle")
      ? String(packageResult.editableTitle ?? "")
      : String(content.title || fields.title || topicTitle || ""),
    draftText: hasOwn(packageResult, "editableDraftText")
      ? String(packageResult.editableDraftText ?? "")
      : contentDraftText || fields.draftText,
    finalText: hasOwn(packageResult, "editableFinalText")
      ? String(packageResult.editableFinalText ?? "")
      : contentFinalText || fields.finalText,
    body: hasOwn(packageResult, "editableBody")
      ? String(packageResult.editableBody ?? "")
      : String(content.body || fields.body || ""),
    publishCopy: hasOwn(packageResult, "editablePublishCopy")
      ? String(packageResult.editablePublishCopy ?? "")
      : videoPublishText !== undefined && videoPublishText !== null
        ? String(videoPublishText)
        : String(fields.publishCopy || content.body || ""),
    hashtagsText: hasOwn(packageResult, "editableHashtagsText")
      ? String(packageResult.editableHashtagsText ?? "")
      : contentHashtagsText || fields.hashtagsText,
    bgmSuggestion: hasOwn(packageResult, "editableBgmSuggestion")
      ? String(packageResult.editableBgmSuggestion ?? "")
      : String(content.bgmSuggestion || fields.bgmSuggestion || ""),
  };
}
