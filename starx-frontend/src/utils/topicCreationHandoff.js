export async function startImageTopicPromptPlan({
  api,
  accountId,
  topicId,
  preferences,
  referenceUrls = [],
}) {
  const payload = { topicId, ...preferences };
  if (referenceUrls.length) payload.referenceUrls = referenceUrls;
  const job = await api.createTopicPromptJob(accountId, payload);
  requireImagePromptJobId(job);
  return job;
}

export function requireImagePromptJobId(job) {
  const jobId = String(job?.id || "").trim();
  if (!jobId) throw new Error("图片 Prompt 计划任务创建失败：未返回任务 ID");
  return jobId;
}

export function resolveActiveImagePromptJobId(currentId, incomingId) {
  return String(currentId || "").trim() || String(incomingId || "").trim();
}

export async function submitTopicCreation({
  topic,
  preferences,
  generateCreation,
  onSuccess,
  onFailure,
}) {
  try {
    await generateCreation(topic.id, preferences.targetPlatform, preferences);
    onSuccess?.();
    return { ok: true };
  } catch (error) {
    onFailure?.(error, preferences);
    return { ok: false, error };
  }
}

export function applyImagePromptJobResult(
  creation,
  { creationId, jobId, preferences }
) {
  if (!creation || creation.creationId !== creationId) return creation;
  const currentJobId = String(
    creation.creationState?.imagePromptJobId
      || creation.creationState?.promptJobId
      || ""
  ).trim();
  const incomingJobId = String(jobId || "").trim();
  if (!incomingJobId || (currentJobId && currentJobId !== incomingJobId)) return creation;
  return {
    ...creation,
    creationState: {
      ...(creation.creationState || {}),
      imagePromptJobId: incomingJobId,
      promptJobId: incomingJobId,
      imageCreationPreferences: preferences,
      imagePromptPlan: null,
    },
  };
}

export function applyImagePromptStartFailure(
  creation,
  { creationId, error } = {}
) {
  if (!creation || creation.creationId !== creationId) return creation;
  return {
    ...creation,
    creationState: {
      ...(creation.creationState || {}),
      imagePromptPlanStartError: String(error?.message || error || "图片 Prompt 计划创建失败"),
    },
  };
}

export function canRetryImagePromptPlan({
  topicId,
  preferences,
  promptJobId = "",
  promptJob = null,
  startError = "",
  isRetrying = false,
} = {}) {
  if (isRetrying || !String(topicId || "").trim() || !preferences) return false;
  return Boolean(
    String(startError || "").trim()
    || (String(promptJobId || "").trim() && promptJob?.status === "failed")
  );
}
