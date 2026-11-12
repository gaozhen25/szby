import { apiClient } from "./client.js";
import { accountReportApi } from "./accountReports.js";
import { DEFAULT_IMAGE_RATIO } from "../utils/imageAspectRatio.js";
import { uploadFileToOss, uploadFilesToOss } from "./uploads.js";

export function buildCreationPayload(topicId, targetPlatform) {
  return { topicId, targetPlatform };
}

export const starxApi = {
  ...accountReportApi,
  login: (payload) => apiClient.post("/auth/login", payload),
  me: () => apiClient.get("/auth/me"),
  getAccounts: (params = {}) => {
    const search = new URLSearchParams(
      Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== "")
    ).toString();
    return apiClient.get(`/accounts${search ? `?${search}` : ""}`);
  },
  createAccount: (payload) => apiClient.post("/accounts", payload),
  updateAccount: (accountId, payload) => apiClient.patch(`/accounts/${accountId}`, payload),
  deleteAccount: (accountId) => apiClient.delete(`/accounts/${accountId}`),
  getKnowledgeBases: (params = {}) => {
    const search = new URLSearchParams(
      Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== "")
    ).toString();
    return apiClient.get(`/knowledge-bases${search ? `?${search}` : ""}`);
  },
  getKnowledgeBase: (knowledgeBaseId) => apiClient.get(`/knowledge-bases/${knowledgeBaseId}`),
  createKnowledgeBase: (payload) => apiClient.post("/knowledge-bases", payload),
  updateKnowledgeBase: (knowledgeBaseId, payload) => apiClient.patch(`/knowledge-bases/${knowledgeBaseId}`, payload),
  deleteKnowledgeBase: (knowledgeBaseId) => apiClient.delete(`/knowledge-bases/${knowledgeBaseId}`),
  uploadKnowledgeBaseImages: (files) =>
    uploadFilesToOss(files, { purpose: "knowledge_base_image" }),
  getTopics: (accountId) => apiClient.get(`/accounts/${accountId}/topics`),
  getFavoriteTopics: (accountId) => apiClient.get(`/accounts/${accountId}/favorite-topics`),
  favoriteTopic: (accountId, topicId) => apiClient.post(`/accounts/${accountId}/favorite-topics/${topicId}`, {}),
  deleteFavoriteTopic: (accountId, favoriteId) =>
    apiClient.delete(`/accounts/${accountId}/favorite-topics/${favoriteId}`),
  refreshTopics: (accountId) => apiClient.post(`/accounts/${accountId}/topics/refresh-batch`, {}),
  getTopicRefreshWorkflow: (accountId, workflowId) =>
    apiClient.get(`/accounts/${accountId}/topics/refresh-workflows/${workflowId}`),
  generateCreation: (accountId, topicId, targetPlatform) =>
    apiClient.post(`/accounts/${accountId}/creations/generate`, buildCreationPayload(topicId, targetPlatform)),
  getCreation: (accountId, creationId) => apiClient.get(`/accounts/${accountId}/creations/${creationId}`),
  submitCreationTask: (accountId, creationId, payload) =>
    apiClient.post(`/accounts/${accountId}/creations/${creationId}/submit-task`, payload),
  publishCreation: (accountId, creationId, payload) =>
    apiClient.post(`/accounts/${accountId}/creations/${creationId}/publish`, payload),
  uploadPublishVideo: async (accountId, creationId, taskId, file) => ({
    ...(await uploadFileToOss(file, { accountId, purpose: "publish_video" })),
    creationId,
    taskId,
  }),
  uploadPublishImages: async (accountId, creationId, taskId, files) =>
    (await uploadFilesToOss(files, { accountId, purpose: "publish_image" }))
      .map((item) => ({ ...item, creationId, taskId })),
  getPublishStatus: (accountId, creationId) =>
    apiClient.get(`/accounts/${accountId}/creations/${creationId}/publish/status`),
  getTasks: (accountId) => apiClient.get(`/accounts/${accountId}/tasks`),
  createTask: (accountId, payload) => apiClient.post(`/accounts/${accountId}/tasks`, payload),
  duplicateTask: (accountId, taskId) =>
    apiClient.post(`/accounts/${accountId}/tasks/${taskId}/duplicate`, {}),
  updateTaskStatus: (accountId, taskId, status) =>
    apiClient.patch(`/accounts/${accountId}/tasks/${taskId}/status`, { status }),
  getMaterials: (accountId) => apiClient.get(`/accounts/${accountId}/materials`),
  createMaterial: (accountId, payload) => apiClient.post(`/accounts/${accountId}/materials`, payload),
  getDigitalHumanTrainingScript: () => apiClient.get("/digital-human/training-script"),
  getDigitalHumanProfiles: (accountId) =>
    apiClient.get(`/accounts/${accountId}/digital-human/profiles`),
  createDigitalHumanProfile: async (accountId, payload) => {
    const sourceVideo = await uploadFileToOss(payload.videoFile, {
      accountId,
      purpose: "digital_human_source",
    });
    return apiClient.post(`/accounts/${accountId}/digital-human/profiles`, {
      name: payload.name || "",
      trainingScriptVersion: payload.trainingScriptVersion || "zh_cn_v1",
      consentConfirmed: Boolean(payload.consentConfirmed),
      sourceVideo,
    });
  },
  disableDigitalHumanProfile: (accountId, profileId) =>
    apiClient.delete(`/accounts/${accountId}/digital-human/profiles/${profileId}`),
  uploadDigitalHumanEditingAsset: (
    accountId,
    file,
    purpose = "digital_human_editing_asset",
  ) =>
    uploadFileToOss(file, {
      accountId,
      purpose,
    }),
  createDigitalHumanVideo: (accountId, payload) =>
    apiClient.post(`/accounts/${accountId}/digital-human/videos`, payload),
  getDigitalHumanVideoJobs: (accountId, params = {}) => {
    const search = new URLSearchParams(
      Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== "")
    ).toString();
    return apiClient.get(`/accounts/${accountId}/digital-human/videos${search ? `?${search}` : ""}`);
  },
  getDashboard: (accountId, params = {}) => {
    const search = new URLSearchParams(
      Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== "")
    ).toString();
    return apiClient.get(`/accounts/${accountId}/dashboard${search ? `?${search}` : ""}`);
  },
  startDashboardRefresh: (accountId, platform) =>
    apiClient.post(
      `/accounts/${accountId}/dashboard/refresh?platform=${encodeURIComponent(platform)}`,
      {},
    ),
  getDashboardRefresh: (accountId, refreshId) =>
    apiClient.get(`/accounts/${accountId}/dashboard/refreshes/${refreshId}`),
  getDashboardContentTrend: (accountId, contentId, days = 7) =>
    apiClient.get(`/accounts/${accountId}/dashboard/contents/${contentId}/trend?days=${days}`),
  getSummary: () => apiClient.get("/dashboard/summary"),
  getCompetitorAccounts: (accountId) =>
    apiClient.get(`/accounts/${accountId}/competitors/accounts`),
  getCompetitorAccountContentTrends: (accountId, targetId, days = 7) =>
    apiClient.get(`/accounts/${accountId}/competitors/accounts/${targetId}/content-trends?days=${days}`),
  getCompetitorAccountMetricTrends: (accountId, targetId, days = 30) =>
    apiClient.get(`/accounts/${accountId}/competitors/accounts/${targetId}/metric-trends?days=${days}`),
  addCompetitorAccount: (accountId, reference) =>
    apiClient.post(
      `/accounts/${accountId}/competitors/accounts`,
      typeof reference === "string" ? { profileUrl: reference } : reference
    ),
  deleteCompetitorAccount: (accountId, targetId) =>
    apiClient.delete(`/accounts/${accountId}/competitors/accounts/${targetId}`),
  refreshCompetitorAccount: (accountId, targetId) =>
    apiClient.post(`/accounts/${accountId}/competitors/accounts/${targetId}/refresh`, {}),
  refreshCompetitorAccounts: (accountId) =>
    apiClient.post(`/accounts/${accountId}/competitors/accounts/refresh-batch`, {}),
  getCompetitorVideos: (accountId) =>
    apiClient.get(`/accounts/${accountId}/competitors/videos`),
  addCompetitorVideo: (accountId, contentUrl) =>
    apiClient.post(`/accounts/${accountId}/competitors/videos`, { contentUrl }),
  deleteCompetitorVideo: (accountId, targetId) =>
    apiClient.delete(`/accounts/${accountId}/competitors/videos/${targetId}`),
  refreshCompetitorVideo: (accountId, targetId) =>
    apiClient.post(`/accounts/${accountId}/competitors/videos/${targetId}/refresh`, {}),
  refreshCompetitorVideos: (accountId) =>
    apiClient.post(`/accounts/${accountId}/competitors/videos/refresh-batch`, {}),
  getCompetitorRefreshWorkflow: (accountId, workflowId) =>
    apiClient.get(`/accounts/${accountId}/competitors/refresh-workflows/${workflowId}`),
  ingestPlatformCookie: (payload) => apiClient.post("/platform-login/cookies", payload),
  ensurePlatformLoginAgent: () => apiClient.post("/platform-login/agent/ensure", {}),
  getHotBoard: (accountId, params = {}) => {
    const search = new URLSearchParams(
      Object.entries({
        platform: params.platform || "抖音",
        boardType: params.boardType || "topic_total",
        keyword: params.keyword || "",
        category: params.category || "",
        dateWindow: params.dateWindow ?? 24,
        limit: params.limit ?? 30,
        forceRefresh: params.forceRefresh ? "true" : undefined,
      }).filter(([, value]) => value !== undefined && value !== null && value !== "")
    ).toString();
    return apiClient.get(`/accounts/${accountId}/hot-boards${search ? `?${search}` : ""}`);
  },
  refreshHotBoard: (accountId, payload = {}) =>
    apiClient.post(`/accounts/${accountId}/hot-boards/refresh`, {
      platform: payload.platform || "抖音",
      boardType: payload.boardType || "topic_total",
      keyword: payload.keyword || "",
      category: payload.category || "",
      dateWindow: payload.dateWindow ?? 24,
      limit: payload.limit ?? 30,
    }),
  getHotTopicDetail: (accountId, challengeId, params = {}) => {
    const search = new URLSearchParams(
      Object.entries({
        sortType: params.sortType ?? 0,
        forceRefresh: params.forceRefresh ? "true" : undefined,
      }).filter(([, value]) => value !== undefined && value !== null && value !== "")
    ).toString();
    return apiClient.get(
      `/accounts/${accountId}/hot-boards/topics/${encodeURIComponent(challengeId)}${search ? `?${search}` : ""}`
    );
  },
  extractLinkReference: (text, context = {}) => apiClient.post("/extract/link-reference", { text, ...context }),
  getExtractLinkHistory: (params = {}) => {
    const search = new URLSearchParams(
      Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== "")
    ).toString();
    return apiClient.get(`/extract/link-reference/history${search ? `?${search}` : ""}`);
  },
  bindExtractHistories: (payload) => apiClient.patch("/extract/link-reference/history/bind", payload),
  createVideoAnalysisJob: (payload) => apiClient.post("/extract/video-analysis-jobs", payload),
  getVideoAnalysisJobs: (params = {}) => {
    const search = new URLSearchParams(
      Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== "")
    ).toString();
    return apiClient.get(`/extract/video-analysis-jobs${search ? `?${search}` : ""}`);
  },
  getVideoAnalysisJob: (jobId) => apiClient.get(`/extract/video-analysis-jobs/${jobId}`),
  getGenerationJobs: (accountId, params = {}) => {
    const search = new URLSearchParams(
      Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== "")
    ).toString();
    return apiClient.get(`/accounts/${accountId}/generation/jobs${search ? `?${search}` : ""}`);
  },
  getGenerationJob: (accountId, jobId) => apiClient.get(`/accounts/${accountId}/generation/jobs/${jobId}`),
  createPromptJob: async (accountId, payload) => {
    const uploaded = await uploadFilesToOss(payload.images || [], {
      accountId,
      purpose: "generation_reference",
    });
    return apiClient.post(`/accounts/${accountId}/generation/prompt-jobs`, {
      copyText: payload.copyText || "",
      targetPlatform: payload.targetPlatform || "",
      topicTitle: payload.topicTitle || null,
      referenceUrls: [
        ...uploaded.map((item) => item.url),
        ...(payload.referenceUrls || []),
      ],
    });
  },
  createTopicPromptJob: (accountId, payload) =>
    apiClient.post(`/accounts/${accountId}/generation/topic-prompt-jobs`, payload),
  createImageJob: async (accountId, payload) => {
    const [referenceUploads, materialUploads] = await Promise.all([
      uploadFilesToOss(payload.referenceImages || [], {
        accountId,
        purpose: "generation_reference",
      }),
      uploadFilesToOss(payload.materialImages || [], {
        accountId,
        purpose: "generation_material",
      }),
    ]);
    const { referenceImages, materialImages, ...requestPayload } = payload;
    return apiClient.post(`/accounts/${accountId}/generation/image-jobs`, {
      ...requestPayload,
      ratio: payload.ratio || DEFAULT_IMAGE_RATIO,
      referenceUrls: [
        ...referenceUploads.map((item) => item.url),
        ...(payload.referenceUrls || []),
      ],
      materialUrls: [
        ...materialUploads.map((item) => item.url),
        ...(payload.materialUrls || []),
      ],
    });
  },
  createPersonReplacementJob: async (accountId, payload) => {
    const [targetImage, personImage] = await Promise.all([
      uploadFileToOss(payload.targetImage, {
        accountId,
        purpose: "person_replacement_target",
      }),
      uploadFileToOss(payload.personImage, {
        accountId,
        purpose: "person_replacement_person",
      }),
    ]);
    return apiClient.post(`/accounts/${accountId}/generation/person-replacement-jobs`, {
      targetImage,
      personImage,
      consentConfirmed: Boolean(payload.consentConfirmed),
      ratio: payload.ratio || DEFAULT_IMAGE_RATIO,
      count: payload.count || 1,
    });
  },
  createPersonReplacementJobs: async (accountId, payload) => {
    const [targetImages, personImage] = await Promise.all([
      uploadFilesToOss(payload.targetImages || [], {
        accountId,
        purpose: "person_replacement_target",
      }, { concurrency: payload.concurrency || 3 }),
      uploadFileToOss(payload.personImage, {
        accountId,
        purpose: "person_replacement_person",
      }),
    ]);
    const results = new Array(targetImages.length);
    let nextIndex = 0;
    const worker = async () => {
      while (nextIndex < targetImages.length) {
        const index = nextIndex;
        nextIndex += 1;
        try {
          const job = await apiClient.post(`/accounts/${accountId}/generation/person-replacement-jobs`, {
            targetImage: targetImages[index],
            personImage,
            consentConfirmed: Boolean(payload.consentConfirmed),
            ratio: payload.ratios?.[index] || payload.ratio || DEFAULT_IMAGE_RATIO,
            count: payload.count || 1,
          });
          results[index] = { job, error: "" };
        } catch (error) {
          results[index] = { job: null, error: error.message || "任务提交失败" };
        }
      }
    };
    await Promise.all(Array.from(
      { length: Math.min(Math.max(payload.concurrency || 3, 1), targetImages.length) },
      worker,
    ));
    return results;
  },
  downloadPersonReplacementResult: (accountId, jobId, imageIndex = 0) =>
    apiClient.getBlob(
      `/accounts/${accountId}/generation/jobs/${jobId}/result-image${imageIndex ? `?imageIndex=${imageIndex}` : ""}`
    ),
  createScriptRewriteJob: (accountId, payload) =>
    apiClient.post(`/accounts/${accountId}/generation/script-rewrite-jobs`, payload),
  createVideoScriptJob: (accountId, payload) =>
    apiClient.post(`/accounts/${accountId}/generation/video-script-jobs`, payload),

  // Prompt tags
  getPromptTags: (accountId) => apiClient.get(`/accounts/${accountId}/generation/prompt-tags`),
  createPromptTagCategory: (accountId, payload) =>
    apiClient.post(`/accounts/${accountId}/generation/prompt-tag-categories`, payload),
  deletePromptTagCategory: (accountId, categoryId) =>
    apiClient.delete(`/accounts/${accountId}/generation/prompt-tag-categories/${categoryId}`),
  createPromptTag: (accountId, categoryId, payload) =>
    apiClient.post(`/accounts/${accountId}/generation/prompt-tag-categories/${categoryId}/tags`, payload),
  updatePromptTag: (accountId, tagId, payload) =>
    apiClient.patch(`/accounts/${accountId}/generation/prompt-tags/${tagId}`, payload),
  deletePromptTag: (accountId, tagId) =>
    apiClient.delete(`/accounts/${accountId}/generation/prompt-tags/${tagId}`),

  // Prompt templates
  getPromptTemplates: (accountId) => apiClient.get(`/accounts/${accountId}/generation/prompt-templates`),
  createPromptTemplate: (accountId, payload) =>
    apiClient.post(`/accounts/${accountId}/generation/prompt-templates`, payload),
  updatePromptTemplate: (accountId, templateId, payload) =>
    apiClient.patch(`/accounts/${accountId}/generation/prompt-templates/${templateId}`, payload),
  deletePromptTemplate: (accountId, templateId) =>
    apiClient.delete(`/accounts/${accountId}/generation/prompt-templates/${templateId}`),

  // Reverse prompt from image
  reversePrompt: async (accountId, source) => {
    if (typeof Blob !== "undefined" && source instanceof Blob) {
      const uploaded = await uploadFileToOss(source, {
        accountId,
        purpose: "generation_reference",
      });
      return apiClient.post(`/accounts/${accountId}/generation/reverse-prompt`, {
        imageUrl: uploaded.url,
        uploadId: uploaded.uploadId,
      });
    }
    const payload = typeof source === "string" ? { imageUrl: source } : source;
    return apiClient.post(`/accounts/${accountId}/generation/reverse-prompt`, payload);
  },

  // Compose prompt (preview final prompt from tags)
  composePrompt: (accountId, payload) =>
    apiClient.post(`/accounts/${accountId}/generation/prompts/compose`, payload),
};
