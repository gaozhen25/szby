import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import CreationPreferenceModal from "../components/CreationPreferenceModal";
import CreationTypePicker from "../components/creation/CreationTypePicker";
import ImagePromptPlanEditor from "../components/ImagePromptPlanEditor";
import VideoShootingCardList from "../components/VideoShootingCardList";
import LoadingOverlay from "../components/creation/LoadingOverlay";
import NewPromptTagModal from "../components/creation/NewPromptTagModal";
import KimCreationHeader from "../components/creation/kim/KimCreationHeader";
import KimCreationExtrasDrawer from "../components/creation/kim/KimCreationExtrasDrawer";
import ModalOverlay from "../components/ModalOverlay";
import KimImageReferenceStep from "../components/creation/kim/KimImageReferenceStep";
import KimImagePromptStep from "../components/creation/kim/KimImagePromptStep";
import KimLinkParseResult from "../components/creation/kim/KimLinkParseResult";
import KimLinkPromptStep from "../components/creation/kim/KimLinkPromptStep";
import KimLinkResultStep from "../components/creation/kim/KimLinkResultStep";
import KimStepWizard from "../components/creation/kim/KimStepWizard";
import KimTagSelectionStep from "../components/creation/kim/KimTagSelectionStep";
import KimVideoReferenceStep from "../components/creation/kim/KimVideoReferenceStep";
import KimVideoScriptStep from "../components/creation/kim/KimVideoScriptStep";
import KimWorkflowSaveModal from "../components/creation/kim/KimWorkflowSaveModal";
import DigitalHumanGenerator from "../components/digital-human/DigitalHumanGenerator";
import MediaLightbox, { useMediaLightbox } from "../components/MediaLightbox";
import { getKimCreationSteps } from "../components/creation/kim/kimCreationContract";
import { ACCOUNT_PLATFORM_OPTIONS } from "../utils/accountProfileForm";
import { buildFieldsFromExtract } from "../utils/contentExtraction";
import { pickInitialLinkReference } from "../utils/extractHistory";
import { DEFAULT_IMAGE_RATIO, inferImageRatioFromReferences } from "../utils/imageAspectRatio";
import { canRetryImagePromptPlan, requireImagePromptJobId, resolveActiveImagePromptJobId } from "../utils/topicCreationHandoff";
import {
  buildImagePublishMediaCandidates,
  buildGenerationSlots,
  getSelectedVariantAssets,
  mergeImageGroups,
  normalizeImageGroups,
  selectFirstVariants,
} from "../utils/imageVariants";
import {
  buildEditableImagePromptPlan,
  buildPromptPlanGenerationPayload,
  restorePersistedImagePromptPlan,
  shouldApplyImagePromptPlanJob,
} from "../utils/imagePromptPlan";
import {
  buildVideoAnalysisDraftFields,
  buildVideoScriptPackageFromAnalysis,
  stripHashtagsFromTitle,
} from "../utils/videoAnalysis";
import { buildVideoPreviewUrl } from "../utils/mediaPreview";
import {
  createImageSlide,
  createMediaSlides,
  createVideoSlide,
  downloadMedia,
} from "../utils/mediaLightbox";
import {
  advanceVideoScriptRefreshFailure,
  buildPersistedVideoScriptPackage,
  buildVideoScriptDraftFields,
  resolveActiveVideoScriptJobId,
  resolveCreationTargetPlatform,
  restoreVideoScriptDraft,
  shouldApplyLegacyScriptRewrite,
} from "../utils/videoScriptPackage";
import { TAG_CATEGORIES } from "../data/tagLibrary";
import { TAG_CATEGORY_UI_CONFIG } from "../config/tagCategoryUi";
import useImagePromptPlanEditor from "../hooks/useImagePromptPlanEditor";
import "../styles/content-creation-kim-exact.css";
import "../styles/content-creation-kim-extras.css";
import "../styles/content-creation-reference.css";
import "../styles/content-creation-tags.css";
import "../styles/content-creation-link-flow.css";
import "../styles/content-creation-type-picker.css";

/* ── helpers ── */
const statusText = { pending: "排队中", running: "生成中", completed: "已完成", failed: "失败" };
const VIDEO_SCRIPT_REFRESH_FAILURE_LIMIT = 3;
const assetPersistenceText = { pending: "资源转存中", completed: "资源已转存", fallback: "转存失败，当前使用源链接", failed: "后台任务异常，当前使用源链接" };
const readableError = (e) => (!e ? "" : e === "AI service token is not configured" ? "AI 服务 Token 未配置" : e);
const priorityLabels = { low: "低", normal: "普通", high: "高" };
const IMAGE_STEPS = getKimCreationSteps("image");
const VIDEO_STEPS = getKimCreationSteps("video");
const linesFromText = (t) => t.split("\n").map((l) => l.trim()).filter(Boolean);
const referenceTextFromExtract = (r) => [r?.title&&`标题：${r.title}`, r?.description&&`正文：${r.description}`, r?.url&&`来源链接：${r.url}`].filter(Boolean).join("\n");
const addUniqueId = (items, id) => (id && !items.includes(id) ? [...items, id] : items);
const getJobInputPayload = (job) => job?.inputPayload || job?.input_payload || {};
const getJobAssets = (job) => Array.isArray(job?.assets) ? job.assets : [];
const PLATFORM_EMOJI = { 抖音: "🎵", 小红书: "📕", 快手: "⚡", 视频号: "💬", B站: "📺", bilibili: "📺", 微博: "📢" };
const TAG_EMOJI = {
  cover: "🖼️", detail: "📋", product: "🛍️", poster: "📰", price: "💰", mirror_selfie: "🪞", food: "🍜", daily_report: "📸",
  ui_screenshot: "💻", social_screenshot: "📱", livestream: "📡", character_poster: "🎭", character_daily: "👤",
  chinese_classical: "🏯", four_panel_comic: "🗯️", child_drawing: "🖍️", hand_drawn_infographic: "✏️", photography: "📷",
  handwritten_annotation: "✍️", doodle: "🎨", ugly_cute: "🤪", beauty_photo: "💄", product_white_bg: "⬜", photo_restore: "🪄",
  embroidery: "🧵", beauty_retouch: "✨", film_portrait: "🎞️", blurry_snap: "🌫️", back_view: "🧍", bedroom: "🛏️",
  rental_room: "🏠", elevator: "🛗", convenience_store: "🏪", cafe: "☕", gym: "🏋️", office_desk: "🖥️", night_market: "🌃",
  park_bench: "🌳", subway: "🚇", workout_checkin: "💪", takeout: "🥡", snack_binge: "🍿", dog_walk: "🐕", reading_slack: "📖",
  gaming: "🎮", cooking_fail: "🍳", fitting_room: "👗", dawn_light: "🌅", afternoon_sun: "🌤️", sunset: "🌇", desk_lamp: "💡",
  rainy_day: "🌧️", no_person: "🚫", "8k": "💎", "4k_photo": "🔭", hd_render: "🖥️", cinema: "🎬",
};
const platformLabel = (name) => {
  const text = String(name || "").trim();
  if (!text) return "";
  const emoji = PLATFORM_EMOJI[text] || "📱";
  return text.includes(emoji) ? text : `${emoji} ${text}`;
};
const tagLabel = (tag) => {
  if (!tag?.name) return "";
  const emoji = tag.emoji || TAG_EMOJI[tag.id] || "🏷️";
  return String(tag.name).includes(emoji) ? tag.name : `${emoji} ${tag.name}`;
};
const truncateJobText = (text, maxLength = 30) => {
  const value = String(text || "").trim();
  const chars = Array.from(value);
  return chars.length > maxLength ? `${chars.slice(0, maxLength).join("")}...` : value;
};

function buildReferenceFromImageJob(job) {
  const input = getJobInputPayload(job);
  const slots = Array.isArray(input.slots) ? input.slots : [];
  const slotImages = slots
    .filter((slot) => slot?.sourceUrl && slot.sourceType !== "manual")
    .map((slot, index) => ({
      url: slot.sourceUrl,
      prompt: slot.sourcePrompt || "",
      analysis: slot.sourcePrompt || "",
      title: slot.fileName || `参考图 ${index + 1}`,
    }));
  const assetImages = getJobAssets(job)
    .filter((asset) => asset.assetType === "reference")
    .map((asset) => ({
      url: asset.url || "",
      title: asset.fileName || "任务参考图",
      analysis: asset.analysis || "",
      prompt: asset.analysis || "",
    }))
    .filter((image) => image.url);
  const seen = new Set();
  const images = [...slotImages, ...assetImages].filter((image) => {
    if (!image.url || seen.has(image.url)) return false;
    seen.add(image.url);
    return true;
  });
  if (!images.length && !input.referenceImageCount && !input.referenceUrlCount) return null;
  return {
    url: images[0]?.url || "",
    platform: job?.targetPlatform || "",
    type: "image_job_reference",
    title: "生图任务参考输入",
    description: job?.prompt ? `提示词：${job.prompt}` : "",
    images,
    videos: [],
  };
}

/* ── merge backend tag categories with local fallback ── */
function mergeCategories(backendCategories, customTags) {
  if (!backendCategories?.length) return TAG_CATEGORIES;
  const result = backendCategories.map((cat) => {
    const localCat = TAG_CATEGORIES.find((c) => c.id === cat.id);
    return {
      id: cat.id,
      name: cat.label || localCat?.name || cat.id,
      description: localCat?.description || "",
      tags: (cat.tags || []).map((t) => ({
        id: t.id,
        name: t.label || t.name,
        prompt: t.prompt || "",
        category: cat.id,
        categoryName: cat.label,
        isCustom: t.source === "custom",
      })),
    };
  });
  // append custom tags to matching categories
  for (const tag of customTags) {
    const cat = result.find((c) => c.id === tag.category);
    if (cat) cat.tags.push(tag);
  }
  return result;
}

function mapBackendTemplate(tpl) {
  return {
    id: tpl.id,
    name: tpl.name,
    description: tpl.description || "",
    prompt: tpl.prompt || "",
    selectedTagIds: tpl.selectedTagIds || [],
    negativePrompt: tpl.negativePrompt || "",
    params: { ratio: tpl.params?.ratio || DEFAULT_IMAGE_RATIO, count: tpl.params?.count || "same" },
    previewPrompt: tpl.previewPrompt || "",
    createdAt: tpl.createdAt?.slice(0, 10) || "",
    useCount: 0,
  };
}

const MOCK_MATERIAL_CATEGORIES = [
  { id: "all", name: "全部", icon: "📁" },
  { id: "uncategorized", name: "未分类", icon: "📂" },
  { id: "portrait", name: "人物", icon: "👤" },
  { id: "landscape", name: "风景", icon: "🏔️" },
  { id: "design", name: "设计素材", icon: "🎨" },
];

export default function ContentCreation({ app }) {
  const initialImagePromptPlan = restorePersistedImagePromptPlan(app.creation.creationState?.imagePromptPlan);
  const initialImageCreationPreferences = app.creation.creationState?.imageCreationPreferences || null;
  const initialVideoScriptPackage = app.creation.creationState?.videoScriptPackage || null;
  const initialVideoDraft = restoreVideoScriptDraft({
    packageResult: initialVideoScriptPackage,
    content: app.creation.content,
    videoPublishText: app.creation.creationState?.videoPublishText,
    topicTitle: app.creation.topicTitle,
  });

  /* ═══════ existing state ═══════ */
  const [type, setType] = useState(app.creation.type || "image");
  const [showCreationTypePicker, setShowCreationTypePicker] = useState(
    app.creation.creationState?.entryModeSelectionRequired === true,
  );
  useEffect(() => {
    if (app.creation.creationState?.entryModeSelectionRequired === true) {
      setShowCreationTypePicker(true);
    }
  }, [app.creation.creationId, app.creation.creationState?.entryModeSelectionRequired]);
  const initialWizardProgress = app.creation.creationState?.creationWizardProgressByType?.[app.creation.type || "image"] || {
    currentStep: app.creation.creationState?.creationWizardStep || 0,
    completedSteps: app.creation.creationState?.completedCreationWizardSteps || [],
  };
  const [currentStep, setCurrentStep] = useState(initialWizardProgress.currentStep);
  const [completedSteps, setCompletedSteps] = useState(initialWizardProgress.completedSteps);
  const wizardProgressByTypeRef = useRef({
    ...(app.creation.creationState?.creationWizardProgressByType || {}),
    [app.creation.type || "image"]: initialWizardProgress,
  });
  const activeCreationTypeRef = useRef(app.creation.type || "image");
  const [files, setFiles] = useState([]);
  const [linkText, setLinkText] = useState("");
  const [imageLinkPlatform, setImageLinkPlatform] = useState("小红书");
  const [imageReferenceDragging, setImageReferenceDragging] = useState(false);
  const [linkReference, setLinkReference] = useState(null);
  const [copyText, setCopyText] = useState(app.creation.content.body || "");
  const [title, setTitle] = useState(app.creation.content.title || app.creation.topicTitle || "");
  const [hashtags, setHashtags] = useState((app.creation.content.hashtags || []).join(" "));
  const [scriptOriginalText, setScriptOriginalText] = useState((app.creation.content.scriptOriginal || []).join("\n"));
  const [scriptRewrittenText, setScriptRewrittenText] = useState((app.creation.content.scriptRewritten || []).join("\n"));
  
  /* ═══════ video-specific state (independent from image mode) ═══════ */
  const [videoLinkText, setVideoLinkText] = useState("");
  const [videoLinkReference, setVideoLinkReference] = useState(null);
  const [videoTitle, setVideoTitle] = useState(initialVideoDraft.title);
  const [videoCopyText, setVideoCopyText] = useState(initialVideoDraft.body);
  const [videoPublishText, setVideoPublishText] = useState(initialVideoDraft.publishCopy);
  const [videoHashtags, setVideoHashtags] = useState(initialVideoDraft.hashtagsText);
  const [videoScriptOriginal, setVideoScriptOriginal] = useState(initialVideoDraft.draftText);
  const [videoScriptRewritten, setVideoScriptRewritten] = useState(initialVideoDraft.finalText);
  const [videoBgmSuggestion, setVideoBgmSuggestion] = useState(initialVideoDraft.bgmSuggestion);
  const [videoScriptPackage, setVideoScriptPackage] = useState(initialVideoScriptPackage);
  const [videoRewritePrompt, setVideoRewritePrompt] = useState("");
  const [showVideoRewritePrompt, setShowVideoRewritePrompt] = useState(false);
  const [activeKimVideoScriptRewriteJobId, setActiveKimVideoScriptRewriteJobId] = useState(
    app.creation.creationState?.activeKimVideoScriptRewriteJobId || ""
  );
  const [activeVideoScriptJobId, setActiveVideoScriptJobId] = useState(app.creation.creationState?.activeVideoScriptJobId || "");
  const [activeDigitalHumanWorkflowId, setActiveDigitalHumanWorkflowId] = useState(
    app.creation.creationState?.activeDigitalHumanWorkflowId || ""
  );
  const [digitalHumanWorkflowIds, setDigitalHumanWorkflowIds] = useState(
    app.creation.creationState?.digitalHumanWorkflowIds || []
  );
  const [videoScriptTargetPlatform, setVideoScriptTargetPlatform] = useState(app.creation.creationState?.videoScriptTargetPlatform || app.creation.targetPlatform || "");
  const [videoScriptDurationSeconds, setVideoScriptDurationSeconds] = useState(app.creation.creationState?.videoScriptDurationSeconds || 60);
  const [videoScriptContentGoal, setVideoScriptContentGoal] = useState(app.creation.creationState?.videoScriptContentGoal || "auto");
  const [videoScriptFormat, setVideoScriptFormat] = useState(app.creation.creationState?.videoScriptFormat || "auto");
  const [videoScriptToneStyle, setVideoScriptToneStyle] = useState(app.creation.creationState?.videoScriptToneStyle || "auto");
  const [videoScriptCustomRequirements, setVideoScriptCustomRequirements] = useState(app.creation.creationState?.videoScriptCustomRequirements || "");
  const [showVideoPreferences, setShowVideoPreferences] = useState(false);
  const [pendingVideoPreferences, setPendingVideoPreferences] = useState(null);
  const [showVideoRegenerateConfirm, setShowVideoRegenerateConfirm] = useState(false);
  const [showDigitalHumanGenerator, setShowDigitalHumanGenerator] = useState(false);
  const [showCreationExtras, setShowCreationExtras] = useState(false);
  const [showWorkflowModal, setShowWorkflowModal] = useState(false);
  const [savingWorkflow, setSavingWorkflow] = useState(false);
  const [videoScriptTrackingError, setVideoScriptTrackingError] = useState(null);
  const [handoff, setHandoff] = useState({ assignee:"", dueDate:"", priority:"normal", status:"draft", handoffNote:"" });
  const [imagePreviews, setImagePreviews] = useState([]);
  const [imageGroups, setImageGroups] = useState(app.creation.creationState?.imageGroups || []);
  const [selectedVariants, setSelectedVariants] = useState(app.creation.creationState?.selectedVariants || {});
  const [imageJobIds, setImageJobIds] = useState(app.creation.creationState?.imageJobIds || []);
  const [activeImageJobId, setActiveImageJobId] = useState(app.creation.creationState?.activeImageJobId || "");
  const [videoAnalysisJobId, setVideoAnalysisJobId] = useState(app.creation.creationState?.videoAnalysisJobId || "");
  const [promptJobId, setPromptJobId] = useState(app.creation.creationState?.promptJobId || "");
  const [imagePromptPlanStartError, setImagePromptPlanStartError] = useState(
    app.creation.creationState?.imagePromptPlanStartError || ""
  );
  const [promptPlanRetrying, setPromptPlanRetrying] = useState(false);
  const [scriptRewriteJobId, setScriptRewriteJobId] = useState(app.creation.creationState?.scriptRewriteJobId || "");
  const fileInputRef = useRef(null);
  const materialInputRef = useRef(null);
  const previewUrlsRef = useRef([]);
  const saveDebounceRef = useRef(null);
  const promptJobIdRef = useRef(promptJobId);
  const appliedImagePromptJobIdsRef = useRef(new Set(
    initialImagePromptPlan?.sourceJobId === promptJobId ? [promptJobId] : []
  ));
  const activeVideoScriptJobIdRef = useRef(activeVideoScriptJobId);
  const appliedVideoAnalysisJobIdsRef = useRef(new Set());
  const videoScriptRefreshFailureCountsRef = useRef(new Map());
  const appliedVideoScriptJobIdsRef = useRef(new Set(
    initialVideoScriptPackage?.sourceJobId === activeVideoScriptJobId ? [activeVideoScriptJobId] : []
  ));
  // Image cache: in-memory Map backed by localStorage for cross-refresh persistence
  function cacheJob(jobId, data) {
    imageCacheRef.current.set(jobId, data);
    try { localStorage.setItem(`starx_img_${jobId}`, JSON.stringify(data)); } catch {}
  }
  function getCachedJob(jobId) {
    if (imageCacheRef.current.has(jobId)) return imageCacheRef.current.get(jobId);
    try {
      const raw = localStorage.getItem(`starx_img_${jobId}`);
      if (raw) { const d = JSON.parse(raw); imageCacheRef.current.set(jobId, d); return d; }
    } catch {}
    return null;
  }
  const imageCacheRef = useRef(new Map());

  /* ═══════ new image-module state ═══════ */
  const [prompt, setPrompt] = useState(app.creation.content.imagePrompt || "");
  const [negativePrompt, setNegativePrompt] = useState(initialImagePromptPlan?.negativePrompt || "");
  const [selectedTagIds, setSelectedTagIds] = useState([]);
  const [ratio, setRatio] = useState(initialImagePromptPlan?.ratio || initialImageCreationPreferences?.ratio || DEFAULT_IMAGE_RATIO);
  const [useOriginalAsReference, setUseOriginalAsReference] = useState(app.creation.creationState?.useOriginalAsReference ?? true);
  const latestSaveStateRef = useRef({
    imageGroups,
    selectedVariants,
    imageJobIds,
    activeImageJobId,
    promptJobId,
    imagePromptPlanStartError,
    scriptRewriteJobId,
    activeKimVideoScriptRewriteJobId,
    videoPublishText,
    activeVideoScriptJobId,
    activeDigitalHumanWorkflowId,
    digitalHumanWorkflowIds,
    videoScriptPackage,
    videoScriptTargetPlatform,
    videoScriptDurationSeconds,
    videoScriptContentGoal,
    videoScriptFormat,
    videoScriptToneStyle,
    videoScriptCustomRequirements,
    ratio,
    imagePrompt: prompt,
    linkReference,
    linkText,
    useOriginalAsReference,
    creationWizardStep: currentStep,
    completedCreationWizardSteps: completedSteps,
    creationWizardProgressByType: wizardProgressByTypeRef.current,
  });
  const [creativityLevel, setCreativityLevel] = useState(initialImagePromptPlan?.creativityLevel || initialImageCreationPreferences?.creativityLevel || "中");
  const [genCount, setGenCount] = useState(initialImagePromptPlan?.cards?.length || initialImageCreationPreferences?.imageCount || 1);
  const {
    imagePromptPlan,
    imageCreationPreferences,
    applyImagePromptPlan,
    restoreImagePromptPlan,
    clearImagePromptPlan,
    changeImagePromptPlanField,
    changeImageRatio,
    changeImageCreativityLevel,
    changeImagePromptCard,
    moveImagePromptCard,
    removeImagePromptCard,
    addImagePromptCard,
  } = useImagePromptPlanEditor({
    initialPlan: initialImagePromptPlan,
    initialPreferences: initialImageCreationPreferences,
    onSinglePromptChange: setPrompt,
    onNegativePromptChange: setNegativePrompt,
    onPublishCopyChange: setCopyText,
    onHashtagsChange: (values) => setHashtags(values.join(" ")),
    onCountChange: setGenCount,
    onRatioChange: setRatio,
    onCreativityChange: setCreativityLevel,
  });
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [busy, setBusy] = useState("");
  const [reverseResult, setReverseResult] = useState(null);
  const [reverseHistories, setReverseHistories] = useState([]);
  const [extractingLink, setExtractingLink] = useState(false);
  const [reversing, setReversing] = useState(false);
  const [extractedImages, setExtractedImages] = useState([]);
  const [showImageParseResult, setShowImageParseResult] = useState(
    app.creation.creationState?.showImageParseResult === true
  );
  const [imageLinkPromptRows, setImageLinkPromptRows] = useState(
    app.creation.creationState?.imageLinkPromptRows || []
  );
  const imageLinkPromptRowsRef = useRef(imageLinkPromptRows);
  const [selectedExtractImage, setSelectedExtractImage] = useState(0);
  const [materials, setMaterials] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [activeTemplateId, setActiveTemplateId] = useState("");
  const [customTags, setCustomTags] = useState([]);
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [saveModalData, setSaveModalData] = useState(null);
  const mediaLightbox = useMediaLightbox();
  const [materialFiles, setMaterialFiles] = useState([]);
  const [materialPreviews, setMaterialPreviews] = useState([]);
  const [referenceStrength, setReferenceStrength] = useState(70);
  const [materialStrength, setMaterialStrength] = useState("中");
  const [imageTabActive, setImageTabActive] = useState("tags");
  const [tagSearch, setTagSearch] = useState("");
  const [tagCategoryPage, setTagCategoryPage] = useState(0);
  const [tplSearch, setTplSearch] = useState("");
  const [showNewTagModal, setShowNewTagModal] = useState(false);
  const [showTagManagerModal, setShowTagManagerModal] = useState(false);
  const [showNewCategoryModal, setShowNewCategoryModal] = useState(false);
  const [newCategoryName, setNewCategoryName] = useState("");
  const [showSaveTplModal, setShowSaveTplModal] = useState(false);
  const [savingTemplate, setSavingTemplate] = useState(false);
  const [tplSaveName, setTplSaveName] = useState("");
  const [tplSaveDesc, setTplSaveDesc] = useState("");
  const [newTagCategory, setNewTagCategory] = useState("purpose");
  const [editingTag, setEditingTag] = useState(null);
  const [editTagName, setEditTagName] = useState("");
  const [editTagPrompt, setEditTagPrompt] = useState("");
  const [recentJobsPage, setRecentJobsPage] = useState(0);
  const RECENT_JOBS_PER_PAGE = 5;
  const ratioInferenceIdRef = useRef(0);
  const detectedReferenceRatioRef = useRef("");

  useEffect(() => {
    imageLinkPromptRowsRef.current = imageLinkPromptRows;
  }, [imageLinkPromptRows]);

  const content = app.creation.content;
  const incomingImagePromptJobId = app.creation.creationState?.imagePromptJobId
    || app.creation.creationState?.promptJobId
    || "";
  const incomingActiveVideoScriptJobId = app.creation.creationState?.activeVideoScriptJobId || "";
  const promptJob = useMemo(() => app.generationJobs.find((j) => j.id === promptJobId) || null, [app.generationJobs, promptJobId]);
  const scriptRewriteJob = useMemo(() => app.generationJobs.find((j) => j.id === scriptRewriteJobId) || null, [app.generationJobs, scriptRewriteJobId]);
  const activeVideoScriptJob = useMemo(
    () => app.generationJobs.find((job) => job.id === activeVideoScriptJobId) || null,
    [app.generationJobs, activeVideoScriptJobId]
  );
  const pendingVideoScriptJobKey = useMemo(
    () => activeVideoScriptJobId
      && videoScriptTrackingError?.jobId !== activeVideoScriptJobId
      && (!activeVideoScriptJob || ["pending", "running"].includes(activeVideoScriptJob.status))
      ? activeVideoScriptJobId
      : "",
    [activeVideoScriptJob, activeVideoScriptJobId, videoScriptTrackingError]
  );
  const videoTopicScriptLoading = Boolean(
    activeVideoScriptJobId
    && videoScriptTrackingError?.jobId !== activeVideoScriptJobId
    && (!activeVideoScriptJob || ["pending", "running"].includes(activeVideoScriptJob.status))
  );
  const activeVideoScriptPackage = videoScriptPackage;
  // Recent tasks sidebar: image generation jobs only (video jobs are in video-creation sidebar)
  const allJobs = useMemo(() => {
    return (app.generationJobs || []).sort((a, b) => {
      const ta = a.createdAt || a.created_at || 0;
      const tb = b.createdAt || b.created_at || 0;
      return new Date(tb) - new Date(ta);
    });
  }, [app.generationJobs]);
  const totalJobPages = useMemo(() => Math.max(1, Math.ceil(allJobs.length / RECENT_JOBS_PER_PAGE)), [allJobs.length]);
  const safeJobPage = useMemo(() => Math.min(recentJobsPage, totalJobPages - 1), [recentJobsPage, totalJobPages]);
  const recentJobs = useMemo(() => allJobs.slice(safeJobPage * RECENT_JOBS_PER_PAGE, (safeJobPage + 1) * RECENT_JOBS_PER_PAGE), [allJobs, safeJobPage]);
  const relatedExtractHistories = useMemo(() => {
    const cId = app.creation.creationId;
    const all = (app.extractHistories || []).filter((i) => !i.creationId || i.creationId === cId);
    // Image mode: only show image extracts (exclude video-only parses)
    return all.filter((i) => (i.images || []).length > 0 && !(i.videos || []).length);
  }, [app.creation.creationId, app.extractHistories]);
  const recentExtractHistories = useMemo(() => relatedExtractHistories.slice(0, 6), [relatedExtractHistories]);
  const relatedVideoAnalysisJobs = useMemo(() => { const cId = app.creation.creationId; return (app.videoAnalysisJobs||[]).filter((j) => { if (cId&&j.creationId&&j.creationId!==cId) return false; if (app.currentAccountId&&j.accountId&&j.accountId!==app.currentAccountId) return false; return true; }); }, [app.creation.creationId, app.currentAccountId, app.videoAnalysisJobs]);
  const activeVideoAnalysisJob = useMemo(
    () => videoAnalysisJobId
      ? relatedVideoAnalysisJobs.find((job) => job.id === videoAnalysisJobId) || null
      : null,
    [relatedVideoAnalysisJobs, videoAnalysisJobId],
  );
  const pendingVideoAnalysisJobKey = useMemo(() => relatedVideoAnalysisJobs.filter((job) => ["pending", "running"].includes(job.status)).map((job) => job.id).join("|"), [relatedVideoAnalysisJobs]);
  const videoAnalysisLoading = Boolean(
    busy === "video-extract"
    || busy === "video-analysis"
    || (
      Boolean(videoAnalysisJobId)
      && activeVideoAnalysisJob?.id === videoAnalysisJobId
      && ["pending", "running"].includes(activeVideoAnalysisJob.status)
    )
  );
  const linkReferenceImages = linkReference?.images || [];
  const imageUsesLinkFlow = type === "image" && (showImageParseResult || imageLinkPromptRows.length > 0 || linkReferenceImages.length > 0);
  const imageGroupsBySlot = useMemo(() => new Map(imageGroups.map((group) => [group.slotId, group])), [imageGroups]);
  const linkReferenceVideos = linkReference?.videos || [];
  const linkReferencePreviewVideos = useMemo(() => {
    const cacheKey = Date.now();
    return linkReferenceVideos.map((video) => ({
      ...video,
      previewUrl: buildVideoPreviewUrl(video.url, cacheKey),
    }));
  }, [linkReferenceVideos]);
  const imageJobs = useMemo(() => imageJobIds.map((id) => app.generationJobs.find((j) => j.id === id)).filter(Boolean), [app.generationJobs, imageJobIds]);
  const pendingImageJobs = useMemo(() => imageJobs.filter((job) => ["pending", "running"].includes(job.status)), [imageJobs]);
  const pendingImageJobKey = useMemo(() => pendingImageJobs.map((job) => job.id).join("|"), [pendingImageJobs]);
  const imageGenerationLoading = submitting || pendingImageJobs.length > 0;
  const pendingPromptJobKey = useMemo(() => (promptJob && ["pending", "running"].includes(promptJob.status) ? promptJob.id : ""), [promptJob]);
  const pendingScriptRewriteJobKey = useMemo(() => (scriptRewriteJob && ["pending", "running"].includes(scriptRewriteJob.status) ? scriptRewriteJob.id : ""), [scriptRewriteJob]);
  const kimVideoScriptRewriting = busy === "video-rewrite" || Boolean(
    scriptRewriteJob
    && scriptRewriteJob.id === activeKimVideoScriptRewriteJobId
    && ["pending", "running"].includes(scriptRewriteJob.status)
  );
  // Only show error for the currently active job, not every failed job in history
  const activeImageJob = useMemo(() => imageJobs.find((job) => job.id === activeImageJobId) || null, [imageJobs, activeImageJobId]);
  const activeJobFailed = activeImageJob?.status === "failed";
  const activeImageJobTerminal = Boolean(
    activeImageJob && !["pending", "running"].includes(activeImageJob.status)
  );
  const resultPanelVisible = imageGroups.length > 0 || imageJobs.length > 0 || !!generating;
  const accountPlatforms = app.currentAccount?.platforms?.length ? app.currentAccount.platforms : ACCOUNT_PLATFORM_OPTIONS;
  const currentTargetPlatform = accountPlatforms.includes(app.creation.targetPlatform) ? app.creation.targetPlatform : accountPlatforms[0];
  const normalizedVideoTargetPlatform = accountPlatforms.includes(videoScriptTargetPlatform) ? videoScriptTargetPlatform : currentTargetPlatform;
  const effectiveTargetPlatform = resolveCreationTargetPlatform(type, currentTargetPlatform, normalizedVideoTargetPlatform);
  const videoPreferences = useMemo(() => ({
    targetPlatform: normalizedVideoTargetPlatform,
    durationSeconds: videoScriptDurationSeconds,
    contentGoal: videoScriptContentGoal,
    videoFormat: videoScriptFormat,
    toneStyle: videoScriptToneStyle,
    customRequirements: videoScriptCustomRequirements,
  }), [normalizedVideoTargetPlatform, videoScriptContentGoal, videoScriptCustomRequirements, videoScriptDurationSeconds, videoScriptFormat, videoScriptToneStyle]);
  const persistedVideoScriptPackage = useMemo(() => {
    if (type !== "video" && !videoScriptPackage) return null;
    return buildPersistedVideoScriptPackage(videoScriptPackage, {
      title: videoTitle,
      draftText: videoScriptOriginal,
      finalText: videoScriptRewritten,
      body: videoCopyText,
      publishCopy: videoPublishText,
      hashtagsText: videoHashtags,
      bgmSuggestion: videoBgmSuggestion,
    });
  }, [type, videoBgmSuggestion, videoCopyText, videoHashtags, videoPublishText, videoScriptOriginal, videoScriptPackage, videoScriptRewritten, videoTitle]);
  const publishSetting = app.currentAccount?.publishSettings?.[effectiveTargetPlatform];
  const publishDeviceConfigured = Boolean(publishSetting?.androidId);
  const assetPersistenceState = app.creation.creationState?.assetPersistence || null;
  const activeWizardSteps = getKimCreationSteps(imageUsesLinkFlow ? "image-link" : type);
  const imageResultsReady = type === "image"
    && currentStep === activeWizardSteps.length - 1
    && imageGroups.length > 0
    && !imageGenerationLoading
    && imageGroups.every((group) => {
      const variants = group.variants || [];
      return variants.length > 0 && variants.some((variant) => variant.variantId === selectedVariants[group.slotId]);
    })
    && (!imageUsesLinkFlow || (
      imageLinkPromptRows.length > 0
      && imageLinkPromptRows.every((row) => (imageGroupsBySlot.get(row.id)?.variants || []).length > 0)
    ));
  const videoResultsReady = type === "video"
    && currentStep === activeWizardSteps.length - 1
    && !videoTopicScriptLoading
    && !videoAnalysisLoading
    && !kimVideoScriptRewriting
    && Boolean(videoScriptRewritten.trim() || videoScriptOriginal.trim() || videoPublishText.trim());
  const readyForWorkflowCompletion = imageResultsReady || videoResultsReady;
  const activeDigitalHumanJob = (app.generationJobs || []).find((job) => job.id === activeDigitalHumanWorkflowId);
  const activeDigitalHumanVideoUrl = activeDigitalHumanJob?.resultPayload?.finalVideoUrl || "";
  const hasDigitalHumanVideoResult = Boolean(activeDigitalHumanVideoUrl);
  const effectiveWorkflowStageOptions = type === "video"
    ? [["shooting", "拍摄"], ["review", "审核"], ["pending_review", "待发布"]]
    : [["review", "审核"], ["pending_review", "待发布"]];
  const workflowStageOptions = type === "video"
    ? [["script", "脚本"], ["review", "审核"], ["pending_review", "待发布"]]
    : [["review", "审核"], ["pending_review", "待发布"]];
  const loadingOverlayMessage = extractingLink
    ? "正在解析素材链接..."
    : reversing
      ? "正在反推图片提示词..."
      : submitting
        ? "正在生成图片..."
        : busy === "video-extract"
          ? "正在解析视频素材..."
          : busy === "video-analysis" || videoAnalysisLoading
            ? "正在分析视频内容..."
            : busy === "video-script"
              ? "正在生成视频脚本..."
              : "";

  const completeStep = useCallback((stepIndex, nextStep = stepIndex + 1, targetType = activeCreationTypeRef.current) => {
    const lastStep = (targetType === "image" ? IMAGE_STEPS : VIDEO_STEPS).length - 1;
    const previousProgress = wizardProgressByTypeRef.current[targetType] || { currentStep: 0, completedSteps: [] };
    const nextCompletedSteps = previousProgress.completedSteps.includes(stepIndex)
      ? previousProgress.completedSteps
      : [...previousProgress.completedSteps, stepIndex];
    const nextProgress = {
      currentStep: Math.min(Math.max(nextStep, 0), lastStep),
      completedSteps: nextCompletedSteps,
    };
    wizardProgressByTypeRef.current = {
      ...wizardProgressByTypeRef.current,
      [targetType]: nextProgress,
    };
    if (activeCreationTypeRef.current === targetType) {
      setCompletedSteps(nextCompletedSteps);
      setCurrentStep(nextProgress.currentStep);
    }
  }, []);

  const handleStepClick = useCallback((stepIndex) => {
    if (stepIndex === currentStep || stepIndex < currentStep || completedSteps.includes(stepIndex)) {
      wizardProgressByTypeRef.current = {
        ...wizardProgressByTypeRef.current,
        [type]: { currentStep: stepIndex, completedSteps },
      };
      setCurrentStep(stepIndex);
    }
  }, [completedSteps, currentStep, type]);

  const switchCreationType = (nextType) => {
    if (nextType === type) return;
    wizardProgressByTypeRef.current = {
      ...wizardProgressByTypeRef.current,
      [type]: { currentStep, completedSteps },
    };
    const nextProgress = wizardProgressByTypeRef.current[nextType] || { currentStep: 0, completedSteps: [] };
    const lastStep = (nextType === "image" ? IMAGE_STEPS : VIDEO_STEPS).length - 1;
    activeCreationTypeRef.current = nextType;
    setCurrentStep(Math.min(Math.max(nextProgress.currentStep || 0, 0), lastStep));
    setCompletedSteps(Array.isArray(nextProgress.completedSteps) ? nextProgress.completedSteps : []);
    setType(nextType);
  };

  const selectCreationType = (nextType) => {
    switchCreationType(nextType);
    app.updateCreation?.({
      type: nextType,
      creationState: {
        ...(app.creation.creationState || {}),
        entryModeSelectionRequired: false,
      },
    });
    setShowCreationTypePicker(false);
  };

  const changeCreationType = (nextType) => {
    if (nextType === type) return;
    switchCreationType(nextType);
    app.updateCreation?.({
      type: nextType,
      creationState: {
        ...(app.creation.creationState || {}),
        entryModeSelectionRequired: false,
        creationWizardProgressByType: {
          ...wizardProgressByTypeRef.current,
          [nextType]: wizardProgressByTypeRef.current[nextType] || { currentStep: 0, completedSteps: [] },
        },
      },
    });
  };

  const refreshTrackedVideoScriptJob = useCallback(async (jobId) => {
    if (!jobId || !app.refreshGenerationJob) return null;
    try {
      const job = await app.refreshGenerationJob(jobId);
      if (!job) throw new Error("视频脚本任务暂时不可用");
      videoScriptRefreshFailureCountsRef.current.delete(jobId);
      setVideoScriptTrackingError((current) => current?.jobId === jobId ? null : current);
      return job;
    } catch (error) {
      if (jobId !== activeVideoScriptJobIdRef.current) return null;
      const failure = advanceVideoScriptRefreshFailure(
        videoScriptRefreshFailureCountsRef.current.get(jobId) || 0,
        error,
        VIDEO_SCRIPT_REFRESH_FAILURE_LIMIT
      );
      videoScriptRefreshFailureCountsRef.current.set(jobId, failure.count);
      if (failure.blocked) {
        setVideoScriptTrackingError({ jobId, message: failure.message, count: failure.count });
      }
      return null;
    }
  }, [app.refreshGenerationJob]);

  const retryVideoScriptTracking = () => {
    if (!activeVideoScriptJobId) return;
    videoScriptRefreshFailureCountsRef.current.delete(activeVideoScriptJobId);
    setVideoScriptTrackingError(null);
    refreshTrackedVideoScriptJob(activeVideoScriptJobId);
  };

  /* ═══════ sync materials from backend ═══════ */
  useEffect(() => { if (app.materials?.length) setMaterials(app.materials); }, [app.materials]);

  /* ═══════ sync templates from backend ═══════ */
  useEffect(() => { setTemplates((app.promptTemplates || []).map(mapBackendTemplate)); }, [app.promptTemplates]);

  /* ═══════ persist image state to backend (survives cross-device) ═══════ */
  const activeLinkReference = type === "video" ? videoLinkReference : linkReference;
  const activeLinkText = type === "video" ? videoLinkText : linkText;
  // Keep latest save state in ref so beforeunload can access it
  useEffect(() => {
    const creationWizardProgressByType = {
      ...wizardProgressByTypeRef.current,
      [type]: { currentStep, completedSteps },
    };
    wizardProgressByTypeRef.current = creationWizardProgressByType;
    const publishMediaCandidates = type === "image"
      ? buildImagePublishMediaCandidates(imageGroups, selectedVariants)
      : undefined;
    latestSaveStateRef.current = {
      imageGroups,
      selectedVariants,
      ...(publishMediaCandidates ? { publishMediaCandidates } : {}),
      imageJobIds,
      activeImageJobId,
      imagePromptJobId: promptJobId,
      promptJobId,
      imagePromptPlanStartError,
      imagePromptPlan,
      imageCreationPreferences,
      imageLinkPromptRows,
      showImageParseResult,
      scriptRewriteJobId,
      activeKimVideoScriptRewriteJobId,
      videoPublishText,
      activeVideoScriptJobId,
      activeDigitalHumanWorkflowId,
      digitalHumanWorkflowIds,
      videoScriptPackage: persistedVideoScriptPackage,
      videoScriptTargetPlatform,
      videoScriptDurationSeconds,
      videoScriptContentGoal,
      videoScriptFormat,
      videoScriptToneStyle,
      videoScriptCustomRequirements,
      ratio,
      imagePrompt: prompt,
      linkReference: activeLinkReference,
      linkText: activeLinkText,
      useOriginalAsReference,
      creationWizardStep: currentStep,
      completedCreationWizardSteps: completedSteps,
      creationWizardProgressByType,
    };
  }, [imageGroups, selectedVariants, imageJobIds, activeImageJobId, promptJobId, imagePromptPlanStartError, imagePromptPlan, imageCreationPreferences, imageLinkPromptRows, showImageParseResult, scriptRewriteJobId, activeKimVideoScriptRewriteJobId, videoPublishText, activeVideoScriptJobId, activeDigitalHumanWorkflowId, digitalHumanWorkflowIds, persistedVideoScriptPackage, videoScriptTargetPlatform, videoScriptDurationSeconds, videoScriptContentGoal, videoScriptFormat, videoScriptToneStyle, videoScriptCustomRequirements, ratio, prompt, linkReference, linkText, videoLinkReference, videoLinkText, useOriginalAsReference, currentStep, completedSteps, type]);
  // Update local state immediately for responsive UI
  useEffect(() => {
    if (app.updateCreation) {
      const publishMediaCandidates = type === "image"
        ? buildImagePublishMediaCandidates(imageGroups, selectedVariants)
        : undefined;
      app.updateCreation({
        creationState: {
          ...(app.creation.creationState || {}),
          imageGroups,
          selectedVariants,
          ...(publishMediaCandidates ? { publishMediaCandidates } : {}),
          imageJobIds,
          activeImageJobId,
          imagePromptJobId: promptJobId,
          promptJobId,
          imagePromptPlanStartError,
          imagePromptPlan,
          imageCreationPreferences,
          imageLinkPromptRows,
          showImageParseResult,
          scriptRewriteJobId,
          activeKimVideoScriptRewriteJobId,
          videoPublishText,
          activeVideoScriptJobId,
          activeDigitalHumanWorkflowId,
          digitalHumanWorkflowIds,
          videoScriptPackage: persistedVideoScriptPackage,
          videoScriptTargetPlatform,
          videoScriptDurationSeconds,
          videoScriptContentGoal,
          videoScriptFormat,
          videoScriptToneStyle,
          videoScriptCustomRequirements,
          ratio,
          linkReference: activeLinkReference,
          linkText: activeLinkText,
          useOriginalAsReference,
          creationWizardStep: currentStep,
          completedCreationWizardSteps: completedSteps,
          creationWizardProgressByType: {
            ...wizardProgressByTypeRef.current,
            [type]: { currentStep, completedSteps },
          },
        },
      });
    }
  }, [imageGroups, selectedVariants, imageJobIds, activeImageJobId, promptJobId, imagePromptPlanStartError, imagePromptPlan, imageCreationPreferences, imageLinkPromptRows, showImageParseResult, scriptRewriteJobId, activeKimVideoScriptRewriteJobId, videoPublishText, activeVideoScriptJobId, activeDigitalHumanWorkflowId, digitalHumanWorkflowIds, persistedVideoScriptPackage, videoScriptTargetPlatform, videoScriptDurationSeconds, videoScriptContentGoal, videoScriptFormat, videoScriptToneStyle, videoScriptCustomRequirements, ratio, linkReference, linkText, videoLinkReference, videoLinkText, useOriginalAsReference, currentStep, completedSteps, type]);
  // Debounce backend save — only when meaningful data changes
  useEffect(() => {
    if (saveDebounceRef.current) window.clearTimeout(saveDebounceRef.current);
    saveDebounceRef.current = window.setTimeout(() => {
      if (app.saveCreationState) {
        app.saveCreationState(latestSaveStateRef.current);
      }
    }, 1500);
    return () => { if (saveDebounceRef.current) window.clearTimeout(saveDebounceRef.current); };
  }, [imageJobIds, activeImageJobId, promptJobId, imagePromptPlanStartError, imagePromptPlan, imageCreationPreferences, imageLinkPromptRows, showImageParseResult, scriptRewriteJobId, activeKimVideoScriptRewriteJobId, videoPublishText, activeVideoScriptJobId, activeDigitalHumanWorkflowId, digitalHumanWorkflowIds, persistedVideoScriptPackage, videoScriptTargetPlatform, videoScriptDurationSeconds, videoScriptContentGoal, videoScriptFormat, videoScriptToneStyle, videoScriptCustomRequirements, imageGroups, selectedVariants, linkReference, linkText, videoLinkReference, videoLinkText, useOriginalAsReference, currentStep, completedSteps, type]);
  // Flush pending saves on tab close / visibility change to prevent data loss
  useEffect(() => {
    const flushSave = () => {
      if (saveDebounceRef.current) {
        window.clearTimeout(saveDebounceRef.current);
        saveDebounceRef.current = null;
      }
      if (app.saveCreationState) {
        // Fire-and-forget — browser may not wait but request is sent
        app.saveCreationState(latestSaveStateRef.current);
      }
    };
    const onVisibility = () => {
      if (document.visibilityState === "hidden") flushSave();
    };
    window.addEventListener("beforeunload", flushSave);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("beforeunload", flushSave);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [app.saveCreationState]);

  /* ═══════ load missing jobs from backend on mount ═══════ */
  useEffect(() => {
    const stateJobIds = [
      promptJobId,
      ...(app.creation.creationState?.imageJobIds || []),
      app.creation.creationState?.activeImageJobId,
      app.creation.creationState?.scriptRewriteJobId,
      activeVideoScriptJobId,
    ].filter(Boolean);
    if (!stateJobIds.length) return;
    const knownIds = new Set(app.generationJobs.map((j) => j.id));
    const missing = [...new Set(stateJobIds)].filter((id) => !knownIds.has(id));
    if (!missing.length) return;
    missing.forEach((jobId) => {
      if (jobId === activeVideoScriptJobId) refreshTrackedVideoScriptJob(jobId);
      else app.refreshGenerationJob(jobId).catch(() => {});
    });
  }, [app.creation.creationId, activeVideoScriptJobId, promptJobId, refreshTrackedVideoScriptJob]);

  useEffect(() => {
    if (!pendingImageJobKey || !app.refreshGenerationJob) return undefined;
    const pendingImageJobIds = pendingImageJobKey.split("|").filter(Boolean);
    const timer = window.setInterval(() => {
      pendingImageJobIds.forEach((jobId) => {
        app.refreshGenerationJob(jobId).catch(() => {});
      });
    }, 5000);
    return () => window.clearInterval(timer);
  }, [app.refreshGenerationJob, pendingImageJobKey]);

  useEffect(() => {
    if (!pendingPromptJobKey || !app.refreshGenerationJob) return undefined;
    const pendingPromptJobIds = pendingPromptJobKey.split("|").filter(Boolean);
    const timer = window.setInterval(() => {
      pendingPromptJobIds.forEach((jobId) => {
        app.refreshGenerationJob(jobId).catch(() => {});
      });
    }, 5000);
    return () => window.clearInterval(timer);
  }, [app.refreshGenerationJob, pendingPromptJobKey]);

  useEffect(() => {
    if (!pendingScriptRewriteJobKey || !app.refreshGenerationJob) return undefined;
    const pendingScriptRewriteJobIds = pendingScriptRewriteJobKey.split("|").filter(Boolean);
    const timer = window.setInterval(() => {
      pendingScriptRewriteJobIds.forEach((jobId) => {
        app.refreshGenerationJob(jobId).catch(() => {});
      });
    }, 5000);
    return () => window.clearInterval(timer);
  }, [app.refreshGenerationJob, pendingScriptRewriteJobKey]);

  useEffect(() => {
    if (!pendingVideoScriptJobKey || !app.refreshGenerationJob) return undefined;
    const pendingVideoScriptJobIds = pendingVideoScriptJobKey.split("|").filter(Boolean);
    const timer = window.setInterval(() => {
      pendingVideoScriptJobIds.forEach((jobId) => {
        refreshTrackedVideoScriptJob(jobId);
      });
    }, 5000);
    return () => window.clearInterval(timer);
  }, [pendingVideoScriptJobKey, refreshTrackedVideoScriptJob]);

  useEffect(() => {
    if (!pendingVideoAnalysisJobKey || !app.refreshVideoAnalysisJob) return undefined;
    const pendingVideoAnalysisJobIds = pendingVideoAnalysisJobKey.split("|").filter(Boolean);
    const timer = window.setInterval(() => {
      pendingVideoAnalysisJobIds.forEach((jobId) => {
        app.refreshVideoAnalysisJob(jobId).catch(() => {});
      });
    }, 5000);
    return () => window.clearInterval(timer);
  }, [app.refreshVideoAnalysisJob, pendingVideoAnalysisJobKey]);

  /* ═══════ effects ═══════ */
  useEffect(() => {
    ratioInferenceIdRef.current += 1;
    detectedReferenceRatioRef.current = "";
    const restoredVideoScriptJobId = app.creation.creationState?.activeVideoScriptJobId || "";
    const restoredVideoScriptPackage = app.creation.creationState?.videoScriptPackage || null;
    const restoredVideoDraft = restoreVideoScriptDraft({
      packageResult: restoredVideoScriptPackage,
      content: app.creation.content,
      videoPublishText: app.creation.creationState?.videoPublishText,
      topicTitle: app.creation.topicTitle,
    });
    const restoredType = app.creation.type || "image";
    const restoredWizardProgressByType = app.creation.creationState?.creationWizardProgressByType || {};
    const restoredWizardProgress = restoredWizardProgressByType[restoredType] || {
      currentStep: app.creation.creationState?.creationWizardStep || 0,
      completedSteps: app.creation.creationState?.completedCreationWizardSteps || [],
    };
    const restoredLastStep = (restoredType === "image" ? IMAGE_STEPS : VIDEO_STEPS).length - 1;
    wizardProgressByTypeRef.current = {
      ...restoredWizardProgressByType,
      [restoredType]: restoredWizardProgress,
    };
    activeCreationTypeRef.current = restoredType;
    setType(restoredType);
    setCurrentStep(Math.min(Math.max(restoredWizardProgress.currentStep || 0, 0), restoredLastStep));
    setCompletedSteps(Array.isArray(restoredWizardProgress.completedSteps) ? restoredWizardProgress.completedSteps : []);
    setTitle(app.creation.content.title||app.creation.topicTitle||"");
    setCopyText(app.creation.content.body||"");
    setHashtags((app.creation.content.hashtags||[]).join(" "));
    setScriptOriginalText((app.creation.content.scriptOriginal||[]).join("\n"));
    setScriptRewrittenText((app.creation.content.scriptRewritten||[]).join("\n"));
    setPrompt(app.creation.content.imagePrompt||"");
    setImageLinkPromptRows(app.creation.creationState?.imageLinkPromptRows || []);
    setShowImageParseResult(app.creation.creationState?.showImageParseResult === true);
    setRatio(app.creation.creationState?.imagePromptPlan?.ratio || app.creation.creationState?.imageCreationPreferences?.ratio || app.creation.creationState?.ratio || DEFAULT_IMAGE_RATIO);
    setImageGroups(app.creation.creationState?.imageGroups||[]);
    setSelectedVariants(app.creation.creationState?.selectedVariants||{});
    setImageJobIds(app.creation.creationState?.imageJobIds||[]);
    setActiveImageJobId(app.creation.creationState?.activeImageJobId||"");
    const restoredImagePromptPlan = restorePersistedImagePromptPlan(app.creation.creationState?.imagePromptPlan);
    restoreImagePromptPlan(restoredImagePromptPlan, app.creation.creationState?.imageCreationPreferences || null);
    const restoredPromptJobId = app.creation.creationState?.imagePromptJobId
      || app.creation.creationState?.promptJobId
      || "";
    setPromptJobId(restoredPromptJobId);
    setImagePromptPlanStartError(app.creation.creationState?.imagePromptPlanStartError || "");
    setPromptPlanRetrying(false);
    promptJobIdRef.current = restoredPromptJobId;
    appliedImagePromptJobIdsRef.current = new Set(
      restoredImagePromptPlan?.sourceJobId === restoredPromptJobId ? [restoredPromptJobId] : []
    );
    setScriptRewriteJobId(app.creation.creationState?.scriptRewriteJobId||"");
    setActiveKimVideoScriptRewriteJobId(app.creation.creationState?.activeKimVideoScriptRewriteJobId || "");
    setActiveVideoScriptJobId(restoredVideoScriptJobId);
    activeVideoScriptJobIdRef.current = restoredVideoScriptJobId;
    setVideoScriptPackage(restoredVideoScriptPackage);
    appliedVideoScriptJobIdsRef.current = new Set(
      restoredVideoScriptPackage?.sourceJobId === restoredVideoScriptJobId ? [restoredVideoScriptJobId] : []
    );
    setVideoScriptTargetPlatform(app.creation.creationState?.videoScriptTargetPlatform || app.creation.targetPlatform || "");
    setVideoScriptDurationSeconds(app.creation.creationState?.videoScriptDurationSeconds || 60);
    setVideoScriptContentGoal(app.creation.creationState?.videoScriptContentGoal || "auto");
    setVideoScriptFormat(app.creation.creationState?.videoScriptFormat || "auto");
    setVideoScriptToneStyle(app.creation.creationState?.videoScriptToneStyle || "auto");
    setVideoScriptCustomRequirements(app.creation.creationState?.videoScriptCustomRequirements || "");
    setVideoAnalysisJobId(app.creation.creationState?.videoAnalysisJobId||"");
    setVideoTitle(restoredVideoDraft.title);
    setVideoCopyText(restoredVideoDraft.body);
    setVideoPublishText(restoredVideoDraft.publishCopy);
    setVideoHashtags(restoredVideoDraft.hashtagsText);
    setVideoScriptOriginal(restoredVideoDraft.draftText);
    setVideoScriptRewritten(restoredVideoDraft.finalText);
    setVideoBgmSuggestion(restoredVideoDraft.bgmSuggestion);
    setUseOriginalAsReference(app.creation.creationState?.useOriginalAsReference ?? true);
    const ref = app.creation.creationState?.linkReference || pickInitialLinkReference(app.extractHistories, app.creation) || null;
    const restoredLinkText = app.creation.creationState?.linkText || ref?.url || "";
    if (restoredType === "video") {
      setVideoLinkReference(ref);
      setVideoLinkText(restoredLinkText);
      setLinkReference(null);
      setLinkText("");
    } else {
      setLinkReference(ref);
      setLinkText(restoredLinkText);
      setVideoLinkReference(null);
      setVideoLinkText("");
    }
  }, [app.creation.creationId]);
  useEffect(() => {
    promptJobIdRef.current = promptJobId;
  }, [promptJobId]);
  useEffect(() => {
    const incomingError = app.creation.creationState?.imagePromptPlanStartError || "";
    if (incomingError) setImagePromptPlanStartError(incomingError);
  }, [app.creation.creationState?.imagePromptPlanStartError]);
  useEffect(() => {
    const nextPromptJobId = resolveActiveImagePromptJobId(
      promptJobIdRef.current,
      incomingImagePromptJobId
    );
    if (!incomingImagePromptJobId || nextPromptJobId === promptJobIdRef.current) return;
    promptJobIdRef.current = nextPromptJobId;
    setPromptJobId(nextPromptJobId);
  }, [app.creation.creationState?.imagePromptJobId, app.creation.creationState?.promptJobId]);
  useEffect(() => {
    const nextActiveVideoScriptJobId = resolveActiveVideoScriptJobId(activeVideoScriptJobIdRef.current, incomingActiveVideoScriptJobId);
    if (!incomingActiveVideoScriptJobId || nextActiveVideoScriptJobId === activeVideoScriptJobIdRef.current) return;
    activeVideoScriptJobIdRef.current = nextActiveVideoScriptJobId;
    setActiveVideoScriptJobId(nextActiveVideoScriptJobId);
  }, [app.creation.creationState?.activeVideoScriptJobId]);
  useEffect(() => {
    activeVideoScriptJobIdRef.current = activeVideoScriptJobId;
    videoScriptRefreshFailureCountsRef.current.clear();
    setVideoScriptTrackingError((current) => current?.jobId === activeVideoScriptJobId ? current : null);
  }, [activeVideoScriptJobId]);
  useEffect(() => {
    if (!activeVideoScriptJob) return;
    videoScriptRefreshFailureCountsRef.current.delete(activeVideoScriptJob.id);
    setVideoScriptTrackingError((current) => current?.jobId === activeVideoScriptJob.id ? null : current);
  }, [activeVideoScriptJob]);
  useEffect(() => {
    if (activeVideoScriptJob?.status !== "completed") return;
    const completedJobId = activeVideoScriptJob.id;
    if (completedJobId !== activeVideoScriptJobIdRef.current) return;
    if (appliedVideoScriptJobIdsRef.current.has(completedJobId)) return;

    const packageResult = activeVideoScriptJob.resultPayload || {};
    const fields = buildVideoScriptDraftFields(activeVideoScriptJob.resultPayload || {});
    appliedVideoScriptJobIdsRef.current.add(completedJobId);
    setVideoScriptPackage({ ...packageResult, sourceJobId: completedJobId });
    setVideoTitle(fields.title);
    setVideoScriptOriginal(fields.draftText);
    setVideoScriptRewritten(fields.finalText);
    setVideoCopyText(fields.body);
    setVideoPublishText(fields.publishCopy);
    setVideoHashtags(fields.hashtagsText);
    setVideoBgmSuggestion(fields.bgmSuggestion);
    if (app.creation.topicId) completeStep(0, 1, "video");
    else setCurrentStep(0);
    app.addToast("视频脚本包已生成，可继续编辑", "success");
  }, [activeVideoScriptJob, completeStep]);
  useEffect(() => {
    if (app.creation.type === "video") return;
    const ref = app.creation.creationState?.linkReference || pickInitialLinkReference(app.extractHistories, app.creation);
    if (!ref) return;
    setLinkReference((current) => current || ref);
    setLinkText((current) => current || ref.url || "");
  }, [app.creation.creationId, app.creation.type, app.extractHistories]);
  useEffect(() => () => { previewUrlsRef.current.forEach((u) => URL.revokeObjectURL(u)); previewUrlsRef.current = []; }, []);
  useEffect(() => {
    if (!shouldApplyImagePromptPlanJob(promptJobIdRef.current, promptJob, appliedImagePromptJobIdsRef.current)) return;
    const inputPreferences = promptJob.inputPayload || promptJob.input_payload || {};
    const savedPreferences = app.creation.creationState?.imageCreationPreferences || {};
    const preferences = { ...inputPreferences, ...savedPreferences };
    const nextPlan = buildEditableImagePromptPlan(promptJob.resultPayload || {}, preferences, promptJob.id);
    if (detectedReferenceRatioRef.current) nextPlan.ratio = detectedReferenceRatioRef.current;
    appliedImagePromptJobIdsRef.current.add(promptJob.id);
    applyImagePromptPlan(nextPlan);
    setImageTabActive("input");
    app.addToast("图片 Prompt 计划已生成，请检查后再生成图片", "success");
  }, [promptJob]);
  useEffect(() => {
    if (promptJob?.status !== "completed") return;
    const mode = promptJob.inputPayload?.mode || promptJob.input_payload?.mode;
    if (mode === "topic_image_plan" || promptJob.id !== promptJobIdRef.current) return;
    const nextPrompt = promptJob.resultPayload?.prompt || promptJob.prompt || "";
    if (!nextPrompt) return;
    setPrompt(nextPrompt);
    setImageTabActive("input");
  }, [promptJob]);
  useEffect(() => {
    if (scriptRewriteJob?.status !== "completed" || !scriptRewriteJob.resultPayload?.script) return;
    const canApplyLegacyRewrite = shouldApplyLegacyScriptRewrite({
      creationType: type,
      activeVideoScriptJobId,
      trackedScriptRewriteJobId: scriptRewriteJobId,
      completedJobId: scriptRewriteJob.id,
      legacyVideoFlowActive: app.creation.creationState?.activeLegacyVideoScriptRewriteJobId === scriptRewriteJob.id
        || activeKimVideoScriptRewriteJobId === scriptRewriteJob.id,
    });
    if (!canApplyLegacyRewrite) return;
    const nextScript = scriptRewriteJob.resultPayload.script.join("\n");
    if (type === "video") setVideoScriptRewritten(nextScript);
    else setScriptRewrittenText(nextScript);
  }, [activeKimVideoScriptRewriteJobId, activeVideoScriptJobId, scriptRewriteJob, scriptRewriteJobId, type]);
  useEffect(() => {
    const completedJobs = imageJobs.filter((job) => job.status === "completed");
    if (!completedJobs.length) return;
    completedJobs.forEach((job) => {
      const groups = normalizeImageGroups(job);
      if (!groups.length) return;
      // Cache for instant restore next time
      cacheJob(job.id, { imageGroups: groups, selectedVariants: selectFirstVariants(groups, {}) });
      setImageGroups((prev) => {
        const merged = mergeImageGroups(prev, groups);
        setSelectedVariants((current) => selectFirstVariants(merged, current));
        return merged;
      });
    });
    if (wizardProgressByTypeRef.current.image?.currentStep === 2) completeStep(2, 2, "image");
    if (!pendingImageJobs.length) setGenerating(false);
  }, [completeStep, imageJobs, pendingImageJobs.length]);
  useEffect(() => {
    if (!pendingImageJobs.length && activeImageJobTerminal) setGenerating(false);
  }, [activeImageJobTerminal, pendingImageJobs.length]);

  /* ═══════ tag / template / generation actions ═══════ */
  const toggleTag = useCallback((id) => {
    setActiveTemplateId("");
    setSelectedTagIds((p) => p.includes(id) ? p.filter((x) => x!==id) : [...p, id]);
  }, []);
  const clearTags = useCallback(() => { setActiveTemplateId(""); setSelectedTagIds([]); }, []);

  const addCustomTag = useCallback(async (tag) => {
    try {
      const created = await app.createCustomTag(tag.category, { label: tag.name, prompt: tag.prompt });
      if (created) {
        setCustomTags((p) => [...p, { ...tag, id: created.id }]);
        app.refreshPromptTags();
        return true;
      }
    } catch (e) {
      app.addToast(e.message || "自定义标签保存失败", "warning");
    }
    return false;
  }, [app]);
  const openNewTagModal = useCallback((categoryId) => {
    setNewTagCategory(categoryId);
    setShowNewTagModal(true);
  }, []);
  const deleteCustomTag = useCallback(async (id) => {
    try {
      await app.deleteCustomTag(id);
      app.refreshPromptTags();
      setCustomTags((p) => p.filter((t) => t.id!==id));
      setSelectedTagIds((p) => p.filter((x) => x!==id));
    } catch (e) {
      app.addToast(e.message || "标签删除失败", "warning");
    }
  }, [app]);

  const applyTemplate = useCallback((tpl) => {
    clearImagePromptPlan();
    setPrompt(tpl.prompt || "");
    setNegativePrompt(tpl.negativePrompt || "");
    setSelectedTagIds(tpl.selectedTagIds || []);
    if (tpl.params?.ratio) changeImageRatio(tpl.params.ratio);
    const templateCount = Number(tpl.params?.count);
    if (Number.isInteger(templateCount) && templateCount >= 1 && templateCount <= 4) setGenCount(templateCount);
    setActiveTemplateId(tpl.id);
    setImageTabActive("input");
    app.addToast(`已应用模板「${tpl.name}」`, "success");
  }, [app, changeImageRatio, clearImagePromptPlan]);
  const saveTemplate = useCallback(async (data) => {
    const tplData = {
      name: data.name,
      description: data.description || "",
      prompt: data.prompt || "",
      selectedTagIds: data.selectedTagIds || [],
      negativePrompt: data.negativePrompt || "",
      params: data.params || { ratio: DEFAULT_IMAGE_RATIO, count: "same" },
    };
    try {
      const created = await app.savePromptTemplate(tplData);
      if (created) {
        setTemplates((prev) => {
          if (prev.some((t) => t.id === created.id)) return prev;
          return [mapBackendTemplate(created), ...prev];
        });
        setActiveTemplateId(created.id);
        return true;
      }
    } catch (e) {
      app.addToast(e.message || "模板保存到服务器失败", "warning");
    }
    return false;
  }, [app]);
  const deleteTemplate = useCallback(async (id) => {
    try {
      await app.deletePromptTemplate(id);
      setTemplates((p) => p.filter((t) => t.id!==id));
      setActiveTemplateId((current) => current === id ? "" : current);
    } catch (e) {
      app.addToast(e.message || "模板删除失败", "warning");
    }
  }, [app]);

  const openSaveTemplateModal = useCallback(() => {
    setTplSaveName("");
    setTplSaveDesc("");
    setShowSaveTplModal(true);
  }, []);

  const confirmSaveTemplate = useCallback(async () => {
    if (!tplSaveName.trim() || savingTemplate) return;
    setSavingTemplate(true);
    const saved = await saveTemplate({
      name: tplSaveName.trim(),
      description: tplSaveDesc.trim(),
      prompt,
      selectedTagIds,
      negativePrompt,
      params: { ratio: ratio || DEFAULT_IMAGE_RATIO, count: String(genCount || 1) },
    });
    setSavingTemplate(false);
    if (saved) setShowSaveTplModal(false);
  }, [genCount, negativePrompt, prompt, ratio, saveTemplate, savingTemplate, selectedTagIds, tplSaveDesc, tplSaveName]);

  /* merged tag categories with custom tags */
  const mergedCategories = useMemo(() => mergeCategories(app.promptTagCategories, customTags), [app.promptTagCategories, customTags]);
  const newTagCategoryDetails = useMemo(() => {
    const category = mergedCategories.find((item) => item.id === newTagCategory);
    if (!category) return null;
    const ui = TAG_CATEGORY_UI_CONFIG[category.id] || {};
    return { id: category.id, label: ui.label || category.name, emoji: ui.emoji || "🏷️", color: ui.color || "#22D3EE" };
  }, [mergedCategories, newTagCategory]);
  const filteredCategories = useMemo(() => { if (!tagSearch) return mergedCategories; return mergedCategories.map((c) => ({...c, tags:c.tags.filter((t) => t.name.includes(tagSearch))})).filter((c) => c.tags.length>0); }, [mergedCategories, tagSearch]);
  const safeTagCategoryPage = Math.min(tagCategoryPage, Math.max(filteredCategories.length - 1, 0));
  const pagedTagCategories = filteredCategories.length ? [filteredCategories[safeTagCategoryPage]] : [];
  const customTagCategories = useMemo(() => mergedCategories.map((c) => ({ ...c, tags: c.tags.filter((t) => t.isCustom) })).filter((c) => c.tags.length > 0), [mergedCategories]);

  const getFinalPrompt = useCallback(() => {
    const allTags = mergedCategories.flatMap((c) => c.tags);
    const tags = selectedTagIds.map((id) => allTags.find((t) => t.id === id)).filter(Boolean);
    const qualityTags = tags.filter((t) => t.category === "quality").map((t) => t.prompt);
    const otherTags = tags.filter((t) => t.category !== "quality").map((t) => t.prompt);
    const parts = [];
    if (prompt?.trim()) parts.push(prompt.trim());
    if (otherTags.length) parts.push(otherTags.join(", "));
    if (qualityTags.length) parts.push(qualityTags.join(", "));
    return parts.join(", ");
  }, [selectedTagIds, prompt, mergedCategories]);

  const applyReferenceImageRatio = useCallback(async (references) => {
    const requestId = ++ratioInferenceIdRef.current;
    const inferredRatio = await inferImageRatioFromReferences(references);
    if (requestId === ratioInferenceIdRef.current) {
      detectedReferenceRatioRef.current = inferredRatio;
      changeImageRatio(inferredRatio);
    }
  }, [changeImageRatio]);
  const primaryReferenceForRatio = useMemo(
    () => (linkReference?.images || []).find(Boolean)
      || imageLinkPromptRows.find((row) => row?.imageUrl)?.imageUrl
      || null,
    [imageLinkPromptRows, linkReference],
  );
  useEffect(() => {
    if (type === "image" && primaryReferenceForRatio) {
      void applyReferenceImageRatio([primaryReferenceForRatio]);
    }
  }, [applyReferenceImageRatio, primaryReferenceForRatio, type]);

  /* link extraction (real API) */
  const extractLink = useCallback(async () => {
    if (!linkText.trim()) { app.addToast("请先粘贴分享链接","warning"); return; }
    setExtractingLink(true);
    try {
      const r = await app.extractLinkReference(linkText.trim());
      const fields = buildFieldsFromExtract(r);
      const cleanTitle = stripHashtagsFromTitle(fields.title);
      setLinkReference({
        ...r,
        title: cleanTitle,
        description: fields.body,
        hashtags: fields.hashtags,
      });
      setExtractedImages(r.images||[]); setSelectedExtractImage(0);
      if (cleanTitle) setTitle(cleanTitle);
      if (!copyText.trim() && fields.body) setCopyText(fields.body);
      if (fields.hashtags.length) setHashtags(fields.hashtags.join(" "));
      setImageLinkPromptRows([]);
      detectedReferenceRatioRef.current = "";
      void applyReferenceImageRatio(r.images || []);
      setShowImageParseResult(true);
    } catch (err) { app.addToast(err.message || "链接解析失败","warning"); }
    finally { setExtractingLink(false); }
  }, [linkText, copyText, app, applyReferenceImageRatio]);

  const continueImageLinkFlow = useCallback(async () => {
    const images = linkReferenceImages.slice(0, 8).map((image) => ({ ...image, url: image.previewUrl || image.url || image.src || image.originalUrl || "" })).filter((image) => image.url);
    setReversing(true);
    try {
      const rows = await Promise.all(images.map(async (image, index) => {
        let result = {};
        try {
          result = await app.reversePrompt(image.url, {
            silent: true,
            title: stripHashtagsFromTitle(linkReference?.title || title),
            description: linkReference?.description || "",
            targetPlatform: effectiveTargetPlatform,
          });
        } catch {}
        return { id: `link_${index + 1}`, index: index + 1, imageUrl: image.url, prompt: result.positive || image.analysis || image.prompt || "", negativePrompt: result.negative || "", publishCopy: result.publishCopy || "" };
      }));
      setImageLinkPromptRows(rows);
      imageLinkPromptRowsRef.current = rows;
      setPrompt(rows.map((row) => row.prompt).filter(Boolean).join("\n\n"));
      const generatedPublishCopy = rows.find((row) => row.publishCopy.trim())?.publishCopy || "";
      if (generatedPublishCopy) setCopyText(generatedPublishCopy);
      setShowImageParseResult(false);
      completeStep(0, 1, "image");
    } finally {
      setReversing(false);
    }
  }, [app, completeStep, effectiveTargetPlatform, linkReference, linkReferenceImages, title]);

  const updateImageLinkPromptRow = useCallback((rowId, value) => {
    setImageLinkPromptRows((rows) => {
      const nextRows = rows.map((row) => row.id === rowId ? { ...row, prompt: value } : row);
      imageLinkPromptRowsRef.current = nextRows;
      return nextRows;
    });
  }, []);

  const generateImageLinkRows = useCallback(async () => {
    const rows = imageLinkPromptRowsRef.current.slice(0, 8);
    if (!rows.length || rows.some((row) => !row.prompt.trim())) {
      app.addToast("请先补全每张图片的对应提示词", "warning");
      return;
    }
    setSubmitting(true);
    try {
      const job = await app.createImageJob({
        prompt: rows.map((row) => row.prompt.trim()).join("\n\n"),
        selectedTagIds: [],
        negativePrompt: rows.map((row) => row.negativePrompt).filter(Boolean).join("\n"),
        count: rows.length,
        ratio: ratio || DEFAULT_IMAGE_RATIO,
        slots: rows.map((row) => ({ slotId: row.id, sourceType: "link_reference", sourceUrl: row.imageUrl, sourcePrompt: row.prompt.trim() })),
        variantsPerSlot: 1,
        referenceUrls: rows.map((row) => row.imageUrl),
        materialImages: materialFiles,
      });
      if (job) {
        setImageJobIds((prev) => addUniqueId(prev, job.id));
        setActiveImageJobId(job.id || "");
        setGenerating(true);
        completeStep(1, 2, "image");
      }
    } catch (error) {
      app.addToast(error.message || "图片生成失败", "warning");
    } finally {
      setSubmitting(false);
    }
  }, [app, completeStep, materialFiles, ratio]);

  const regenerateImageLinkRow = useCallback(async (row) => {
    const requirement = window.prompt("输入这张图片的改写要求", "");
    if (requirement === null) return;
    const nextPrompt = requirement.trim() ? `${row.prompt.trim()}，改写要求：${requirement.trim()}` : row.prompt.trim();
    setImageLinkPromptRows((current) => current.map((item) => item.id === row.id ? { ...item, prompt: nextPrompt } : item));
    try {
      const job = await app.createImageJob({ prompt: nextPrompt, selectedTagIds: [], negativePrompt: row.negativePrompt || "", count: 1, ratio: ratio || DEFAULT_IMAGE_RATIO, slots: [{ slotId: row.id, sourceType: "link_reference", sourceUrl: row.imageUrl, sourcePrompt: nextPrompt }], variantsPerSlot: 1, regenerateSlotId: row.id, referenceUrls: [row.imageUrl], materialImages: materialFiles });
      if (job) { setImageJobIds((prev) => addUniqueId(prev, job.id)); setActiveImageJobId(job.id || ""); setGenerating(true); }
    } catch (error) { app.addToast(error.message || "改写失败", "warning"); }
  }, [app, materialFiles, ratio]);

  /* reverse prompt (real API with fallback) */
  const reversePrompt = useCallback(async (imageUrl, imageFile = null) => {
    setReversing(true); setReverseResult(null);
    try {
      let result;
      if (app.reversePrompt) {
        result = await app.reversePrompt(imageFile || imageUrl);
      } else {
        // fallback: compose prompt from image via AI
        result = { positive: prompt, negative: negativePrompt, styleTags: [], keyParams: {} };
      }
      const persistedImageUrl = result.imageUrl || imageUrl;
      const nextResult = { ...result, imageUrl: persistedImageUrl, createdAt: new Date().toISOString() };
      setReverseResult(nextResult);
      setReverseHistories((prev) => [nextResult, ...prev.filter((item) => item.imageUrl !== persistedImageUrl)].slice(0, 6));
      setImageTabActive("input");
      if (result.positive) setPrompt(result.positive);
      if (result.negative) setNegativePrompt(result.negative||"");
      if (result.publishCopy) setCopyText(result.publishCopy);
      if (result.styleTags?.length) {
        const categories = mergeCategories(app.promptTagCategories, customTags);
        const tagIds = [];
        for (const name of result.styleTags) {
          for (const cat of categories) {
            const f = cat.tags.find((t) => t.name===name || t.name===name);
            if (f) tagIds.push(f.id);
          }
        }
        if (tagIds.length) setSelectedTagIds(tagIds);
      }
      completeStep(0, 1, "image");
    } catch (err) { app.addToast(err.message || "反推失败，请重试","warning"); }
    finally { setReversing(false); }
  }, [app, prompt, negativePrompt, customTags, completeStep]);

  /* file helpers */
  const resetImageLinkFlow = useCallback(() => {
    setLinkReference(null);
    setImageLinkPromptRows([]);
    setShowImageParseResult(false);
    imageLinkPromptRowsRef.current = [];
    setExtractedImages([]);
  }, []);
  const selectFiles = useCallback((e) => {
    const sf = Array.from(e.target.files || []);
    if (!sf.length) return;
    detectedReferenceRatioRef.current = "";
    const previews = sf.map((file) => URL.createObjectURL(file));
    const nextFiles = [...files, ...sf];
    const nextPreviews = [...imagePreviews, ...previews];
    previewUrlsRef.current = nextPreviews;
    setFiles(nextFiles);
    setImagePreviews(nextPreviews);
    resetImageLinkFlow();
    void applyReferenceImageRatio(nextFiles);
    if (e.target) e.target.value = "";
  }, [applyReferenceImageRatio, files, imagePreviews, resetImageLinkFlow]);
  const clearFiles = useCallback(() => {
    ratioInferenceIdRef.current += 1;
    detectedReferenceRatioRef.current = "";
    previewUrlsRef.current.forEach((u) => URL.revokeObjectURL(u));
    previewUrlsRef.current = [];
    setFiles([]);
    setImagePreviews([]);
    changeImageRatio(DEFAULT_IMAGE_RATIO);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }, [changeImageRatio]);
  const removeReferencePreview = useCallback((index) => {
    const removedPreview = imagePreviews[index];
    if (removedPreview) URL.revokeObjectURL(removedPreview);
    const nextFiles = files.filter((_, fileIndex) => fileIndex !== index);
    const nextPreviews = imagePreviews.filter((_, previewIndex) => previewIndex !== index);
    previewUrlsRef.current = nextPreviews;
    setFiles(nextFiles);
    setImagePreviews(nextPreviews);
    if (fileInputRef.current) fileInputRef.current.value = "";
    if (nextFiles.length) {
      detectedReferenceRatioRef.current = "";
      void applyReferenceImageRatio(nextFiles);
      return;
    }
    ratioInferenceIdRef.current += 1;
    detectedReferenceRatioRef.current = "";
    changeImageRatio(DEFAULT_IMAGE_RATIO);
  }, [applyReferenceImageRatio, changeImageRatio, files, imagePreviews]);
  const selectMaterialFiles = useCallback((e) => { const sf = Array.from(e.target.files||[]); materialPreviews.forEach((u) => URL.revokeObjectURL(u)); const pv = sf.map((f) => URL.createObjectURL(f)); setMaterialFiles(sf); setMaterialPreviews(pv); }, [materialPreviews]);
  const clearMaterialFiles = useCallback(() => { materialPreviews.forEach((u) => URL.revokeObjectURL(u)); setMaterialFiles([]); setMaterialPreviews([]); if (materialInputRef.current) materialInputRef.current.value = ""; }, [materialPreviews]);
  const startNewCreation = useCallback(() => {
    if (currentStep <= 0) return;
    if (!window.confirm("是否放弃当前操作并重新开始？")) return;
    clearFiles();
    clearMaterialFiles();
    resetImageLinkFlow();
    setShowCreationExtras(false);
    setShowWorkflowModal(false);
    setShowVideoPreferences(false);
    setShowVideoRegenerateConfirm(false);
    setPendingVideoPreferences(null);
    setVideoScriptTrackingError(null);
    app.startBlankCreation?.();
  }, [app, clearFiles, clearMaterialFiles, currentStep, resetImageLinkFlow]);
  const applyImageJobReferenceInput = useCallback((job) => {
    const input = getJobInputPayload(job);
    const ref = buildReferenceFromImageJob(job);
    clearFiles();
    setLinkReference(ref);
    setLinkText(ref?.url || "");
    setUseOriginalAsReference(Boolean(ref) || Boolean(input.referenceImageCount) || Boolean(input.referenceUrlCount));
    const nextReferenceStrength = Number(input.referenceStrength);
    if (Number.isFinite(nextReferenceStrength)) setReferenceStrength(nextReferenceStrength);
  }, [clearFiles]);

  const retryImagePromptPlan = useCallback(async () => {
    if (promptPlanRetrying) return;
    try {
      if (canRetryImagePromptPlan({
        topicId: app.creation.topicId,
        preferences: imageCreationPreferences,
        promptJobId,
        promptJob,
        startError: imagePromptPlanStartError,
        isRetrying: promptPlanRetrying,
      }) && app.createTopicPromptJob) {
        setPromptPlanRetrying(true);
        let retryReference = linkReference;
        const referenceUrl = app.creation.creationState?.referenceNote?.publicUrl;
        if (!(retryReference?.images || []).length && referenceUrl) {
          if (!app.extractLinkReference) throw new Error("参考爆款笔记暂时无法解析");
          retryReference = await app.extractLinkReference(referenceUrl);
          setLinkReference(retryReference);
          setLinkText(referenceUrl);
        }
        const retryReferenceUrls = (retryReference?.images || [])
          .map((image) => image?.url || image?.sourceUrl || "")
          .filter(Boolean)
          .slice(0, 8);
        if (referenceUrl && !retryReferenceUrls.length) {
          throw new Error("参考爆款笔记未解析出原图");
        }
        const retryPayload = {
          topicId: app.creation.topicId,
          ...imageCreationPreferences,
        };
        if (retryReferenceUrls.length) retryPayload.referenceUrls = retryReferenceUrls;
        const job = await app.createTopicPromptJob(retryPayload);
        const jobId = requireImagePromptJobId(job);
        promptJobIdRef.current = jobId;
        setPromptJobId(jobId);
        setImagePromptPlanStartError("");
        appliedImagePromptJobIdsRef.current.delete(jobId);
        app.updateCreation?.({
          creationState: {
            ...(app.creation.creationState || {}),
            imagePromptJobId: jobId,
            promptJobId: jobId,
            imagePromptPlanStartError: "",
          },
        });
        return;
      }
      if (promptJobId && app.refreshGenerationJob) await app.refreshGenerationJob(promptJobId);
    } catch (error) {
      setImagePromptPlanStartError(error.message || "图片 Prompt 计划创建失败");
      app.addToast(error.message || "图片 Prompt 计划加载失败", "warning");
    } finally {
      setPromptPlanRetrying(false);
    }
  }, [app, imageCreationPreferences, imagePromptPlanStartError, linkReference, promptJob, promptJobId, promptPlanRetrying]);

  /* image generation — payload exactly matches backend CreateImageWorkflowRequest */
  const createImages = useCallback(async () => {
    const fp = getFinalPrompt();
    if (!imagePromptPlan?.cards?.length && !fp.trim()) { app.addToast("请先输入提示词或选择标签","warning"); return; }
    setSubmitting(true);
    try {
      if (imagePromptPlan?.cards?.length) {
        const planPayload = buildPromptPlanGenerationPayload({
          cards: imagePromptPlan.cards,
          ratio: ratio || imagePromptPlan.ratio,
          negativePrompt,
          collectionMode: imagePromptPlan.collectionMode,
          sharedStyle: imagePromptPlan.sharedStyle,
          sourcePromptWorkflowId: imagePromptPlan.sourceJobId || promptJobId,
        });
        const job = await app.createImageJob({
          ...planPayload,
          selectedTagIds: [],
          referenceImages: [],
          referenceUrls: [],
          materialImages: [],
          referenceStrength,
          materialStrength,
        });
        if (job) {
          app.addToast(`已提交 ${planPayload.count} 组图片（共 ${planPayload.count * planPayload.variantsPerSlot} 个候选） · ${job.id?.slice(-6)}`, "success");
          setImageJobIds((prev) => addUniqueId(prev, job.id));
          setActiveImageJobId(job.id || "");
          setGenerating(true);
        }
        return;
      }
      const slots = buildGenerationSlots({
        files,
        imagePreviews,
        linkReferenceImages,
        count: "same",
        fallbackCount: genCount,
      }).map((slot) => ({
        ...slot,
        sourcePrompt: slot.sourcePrompt || fp.trim(),
      }));
      const job = await app.createImageJob({
        prompt: fp.trim(),
        selectedTagIds,
        negativePrompt: negativePrompt || "",
        count: slots.length,
        ratio: ratio || DEFAULT_IMAGE_RATIO,
        slots,
        variantsPerSlot: 2,
        referenceImages: useOriginalAsReference ? files : [],
        referenceUrls: useOriginalAsReference
          ? linkReferenceImages.map((image) => image.url).filter(Boolean)
          : [],
        materialImages: materialFiles,
        referenceStrength,
        materialStrength,
      });
      if (job) {
        app.addToast(`已提交生图任务 · ${job.id?.slice(-6)}`, "success");
        setImageJobIds((prev) => addUniqueId(prev, job.id));
        setActiveImageJobId(job.id || "");
        setGenerating(true);
      }
    } catch (err) {
      app.addToast(err.message || "图片生成失败", "warning");
    } finally {
      setSubmitting(false);
    }
  }, [app, files, genCount, getFinalPrompt, imagePreviews, imagePromptPlan, linkReferenceImages, materialFiles, materialStrength, negativePrompt, ratio, referenceStrength, selectedTagIds, useOriginalAsReference]);

  /* regenerate slot */
  const regenerateSlot = useCallback(async (group, refinement) => {
    setBusy(`regen-${group.slotId}`);
    try {
      // Build a combined prompt that includes the refinement instruction
      const basePrompt = getFinalPrompt();
      const fullPrompt = refinement ? `${basePrompt}, ${refinement}` : basePrompt;
      const job = await app.createImageJob({
        prompt: fullPrompt,
        selectedTagIds,
        negativePrompt: negativePrompt || "",
        count: 1,
        ratio: ratio || DEFAULT_IMAGE_RATIO,
        slots: [{ slotId: group.slotId, sourceType: group.sourceType || "manual", sourceUrl: group.sourceUrl || "", sourcePrompt: fullPrompt }],
        variantsPerSlot: 2,
        refinement: refinement.trim(),
        regenerateSlotId: group.slotId,
        referenceImages: useOriginalAsReference ? files : [],
        referenceUrls: useOriginalAsReference
          ? linkReferenceImages.map((image) => image.url).filter(Boolean)
          : [],
        materialImages: materialFiles,
        referenceStrength,
        materialStrength,
      });
      if (job) {
        app.addToast(`已提交重新生成任务 · ${job.id?.slice(-6)}`, "success");
        setImageJobIds((prev) => addUniqueId(prev, job.id));
        // poll for completion
        const checkComplete = () => {
          const j = app.generationJobs.find((x) => x.id === job.id);
          if (j?.status === "completed") {
            const groups = normalizeImageGroups(j);
            const newGroup = groups.find((g) => g.slotId === group.slotId);
            if (newGroup) {
              setImageGroups((p) => p.map((g) => g.slotId === group.slotId ? { ...newGroup, refinement: refinement.trim() } : g));
              setSelectedVariants((p) => ({ ...p, [group.slotId]: newGroup.variants?.[0]?.variantId || "" }));
            }
            app.addToast("重新生成完成", "success");
            setBusy("");
            return;
          }
          if (j?.status === "failed") { app.addToast(j.error || "重新生成失败", "warning"); setBusy(""); return; }
          window.setTimeout(checkComplete, 2000);
        };
        window.setTimeout(checkComplete, 2000);
      }
    } catch (err) { app.addToast(err.message || "重新生成失败", "warning"); setBusy(""); }
  }, [app, files, getFinalPrompt, linkReferenceImages, materialFiles, materialStrength, negativePrompt, ratio, referenceStrength, selectedTagIds, useOriginalAsReference]);

  const selectVariant = useCallback((slotId, variantId) => setSelectedVariants((p) => ({...p, [slotId]:variantId})), []);

  /* save to material (real API) */
  const openSaveModal = useCallback((d) => { setSaveModalData(d); setShowSaveModal(true); }, []);
  const handleSaveToLibrary = useCallback(async (d) => {
    if (app.saveMaterial) {
      await app.saveMaterial({
        name: d.name || `AI作品_${new Date().toISOString().slice(0,10)}`,
        type: "image",
        tags: d.tags || [],
        date: new Date().toISOString().slice(0,10),
        thumb: d.imageUrl || d.thumb || "",
      });
      return;
    }
    app.addToast(`「${d.name}」已保存到素材库`,"success");
  }, [app]);
  const handleBatchSave = useCallback(async (items) => {
    for (const item of items) {
      if (app.saveMaterial) {
        await app.saveMaterial({
          name: item.name || "批量保存",
          type: "image",
          tags: selectedTagIds.map((id) => mergedCategories.flatMap((c) => c.tags).find((t) => t.id === id)?.name).filter(Boolean),
          date: new Date().toISOString().slice(0,10),
          thumb: item.url || "",
        });
      }
    }
    app.addToast(`已批量保存 ${items.length} 张到素材库`,"success");
  }, [app, selectedTagIds]);

  const displayMaterials = useMemo(() => (materials || []).slice(0, 6), [materials]);

  const filteredTemplates = useMemo(() => { if (!tplSearch) return templates; return templates.filter((t) => t.name.includes(tplSearch) || t.description?.includes(tplSearch)); }, [templates, tplSearch]);

  /* ═══════ existing video helpers ═══════ */
  const startVideoScriptGeneration = async (preferences) => {
    if (!app.createVideoScriptJob || !app.creation.topicId) {
      app.addToast("缺少账号或视频选题，无法生成脚本", "warning");
      return null;
    }
    setBusy("video-script");
    try {
      const job = await app.createVideoScriptJob({
        topicId: app.creation.topicId,
        targetPlatform: preferences.targetPlatform,
        durationSeconds: preferences.durationSeconds,
        contentGoal: preferences.contentGoal,
        videoFormat: preferences.videoFormat,
        toneStyle: preferences.toneStyle,
        customRequirements: preferences.customRequirements,
      });
      setActiveVideoScriptJobId(job.id);
      activeVideoScriptJobIdRef.current = job.id;
      setVideoScriptTargetPlatform(preferences.targetPlatform);
      setVideoScriptDurationSeconds(preferences.durationSeconds);
      setVideoScriptContentGoal(preferences.contentGoal);
      setVideoScriptFormat(preferences.videoFormat);
      setVideoScriptToneStyle(preferences.toneStyle);
      setVideoScriptCustomRequirements(preferences.customRequirements);
      return job;
    } catch (error) {
      app.addToast(error.message || "视频脚本生成失败，请重试", "warning");
      return null;
    } finally {
      setBusy("");
    }
  };
  const stageVideoPreferences = (preferences) => {
    setShowVideoPreferences(false);
    setPendingVideoPreferences(preferences);
    setShowVideoRegenerateConfirm(true);
  };
  const cancelVideoScriptRegeneration = () => {
    setShowVideoRegenerateConfirm(false);
    setPendingVideoPreferences(null);
  };
  const confirmVideoScriptRegeneration = async () => {
    if (!pendingVideoPreferences) return;
    const preferences = pendingVideoPreferences;
    setShowVideoRegenerateConfirm(false);
    setPendingVideoPreferences(null);
    await startVideoScriptGeneration(preferences);
  };
  const retryVideoScriptGeneration = () => {
    startVideoScriptGeneration(videoPreferences);
  };
  const rewriteVideoScript = async () => {
    const originalScript = linesFromText(videoScriptOriginal);
    if (!originalScript.length) {
      app.addToast("请先输入爆款原版脚本", "warning");
      return;
    }
    if (!app.createScriptRewriteJob) {
      app.addToast("当前环境暂不支持 AI 改写脚本", "warning");
      return;
    }
    setBusy("video-rewrite");
    try {
      const rewriteContext = [
        videoCopyText.trim(),
        videoRewritePrompt.trim() ? `改写要求：${videoRewritePrompt.trim()}` : "",
      ].filter(Boolean).join("\n");
      const job = await app.createScriptRewriteJob({
        originalScript,
        copyText: rewriteContext,
        targetPlatform: effectiveTargetPlatform,
        topicTitle: videoTitle.trim() || app.creation.topicTitle || null,
      });
      if (!job?.id) throw new Error("AI 改写任务未返回任务编号");
      setScriptRewriteJobId(job.id);
      setActiveKimVideoScriptRewriteJobId(job.id);
      setShowVideoRewritePrompt(false);
      setVideoRewritePrompt("");
    } catch (error) {
      app.addToast(error.message || "AI 改写脚本失败，请重试", "warning");
    } finally {
      setBusy("");
    }
  };
  const applyVideoAnalysisResult = (job) => {
    const result = job?.resultPayload || {};
    const fields = buildVideoAnalysisDraftFields(result);
    const packageResult = buildVideoScriptPackageFromAnalysis(result, {
      title: job?.title || videoTitle,
      hashtags: String(videoHashtags || "").split(/[,，\s]+/),
    });
    setVideoScriptPackage({ ...packageResult, sourceJobId: job?.id || "" });
    if (fields.copyText) setVideoCopyText(fields.copyText);
    if (fields.publishCopy) setVideoPublishText(fields.publishCopy);
    if (fields.scriptOriginalText) setVideoScriptOriginal(fields.scriptOriginalText);
    if (fields.scriptRewrittenText) setVideoScriptRewritten(fields.scriptRewrittenText);
    completeStep(0, 1, "video");
    app.addToast("视频解析结果已填入稿件", "success");
  };
  useEffect(() => {
    if (!videoAnalysisJobId || activeVideoAnalysisJob?.id !== videoAnalysisJobId) return;
    if (activeVideoAnalysisJob.status !== "completed" || !activeVideoAnalysisJob.resultPayload) return;
    if (appliedVideoAnalysisJobIdsRef.current.has(activeVideoAnalysisJob.id)) return;

    appliedVideoAnalysisJobIdsRef.current.add(activeVideoAnalysisJob.id);
    applyVideoAnalysisResult(activeVideoAnalysisJob);
  }, [activeVideoAnalysisJob, videoAnalysisJobId]);
  const analyzeVideoLink = async () => {
    const sourceText = videoLinkText.trim();
    if (!sourceText) return;
    setBusy("video-extract");
    try {
      const reference = await app.extractLinkReference(sourceText);
      setVideoLinkReference(reference);
      const cleanTitle = stripHashtagsFromTitle(reference.title);
      if (cleanTitle) setVideoTitle(cleanTitle);
      const referenceText = referenceTextFromExtract(reference);
      if (!videoCopyText.trim() && referenceText) setVideoCopyText(referenceText);
      if (reference.hashtags?.length) setVideoHashtags(reference.hashtags.join(" "));
      const videos = reference.videos || [];
      const directUrl = /^https?:\/\//i.test(sourceText);
      if (!videos.length && !directUrl) {
        app.addToast("链接解析成功，未发现视频素材", "success");
        return;
      }
      setVideoAnalysisJobId("");
      app.addToast("视频链接解析完成，请确认素材后点击下一步", "success");
    } catch (error) {
      app.addToast(error.message || "视频链接解析失败", "warning");
    } finally {
      setBusy("");
    }
  };
  const continueVideoReferenceFlow = async () => {
    const sourceText = videoLinkText.trim();
    const reference = videoLinkReference;
    const videos = reference?.videos || [];
    const videoUrl = videos[0]?.url || (/^https?:\/\//i.test(sourceText) ? sourceText : "");
    if (!reference || !videoUrl) {
      app.addToast("请先解析并确认视频素材", "warning");
      return;
    }
    if (!app.createVideoAnalysisJob) {
      app.addToast("当前环境暂不支持视频音轨分析", "warning");
      return;
    }
    setBusy("video-analysis");
    try {
      const job = await app.createVideoAnalysisJob({
        sourceUrl: reference.resolvedUrl || reference.url || sourceText,
        videoUrl,
        coverUrl: reference.cover || reference.images?.[0]?.url || "",
        platform: reference.platform || effectiveTargetPlatform || "",
        title: reference.title || videoTitle,
        description: reference.description || videoCopyText,
        hashtags: reference.hashtags || [],
        images: reference.images || [],
        videos,
      });
      if (!job?.id) throw new Error("视频分析任务未返回任务编号");
      setVideoAnalysisJobId(job.id);
      app.addToast("已开始提取音轨并生成分镜", "success");
    } catch (error) {
      app.addToast(error.message || "视频音轨分析启动失败", "warning");
    } finally {
      setBusy("");
    }
  };
  const selectVideoAnalysisJob = (job) => {
    setType("video");
    setVideoAnalysisJobId(job.id);
    if (job.sourceUrl || job.title) {
      setVideoLinkReference({
        url: job.sourceUrl || "",
        platform: job.platform || "",
        title: job.title || "",
        description: job.description || "",
        images: job.images || [],
        videos: job.videos || [],
        cover: job.coverUrl || "",
      });
      setVideoLinkText(job.sourceUrl || "");
    }
    if (job.resultPayload) {
      const fields = buildVideoAnalysisDraftFields(job.resultPayload);
      const packageResult = buildVideoScriptPackageFromAnalysis(job.resultPayload, {
        title: job.title || videoTitle,
        hashtags: String(videoHashtags || "").split(/[,，\s]+/),
      });
      setVideoScriptPackage({ ...packageResult, sourceJobId: job.id });
      if (fields.copyText) setVideoCopyText(fields.copyText);
      if (fields.publishCopy) setVideoPublishText(fields.publishCopy);
      if (fields.scriptOriginalText) setVideoScriptOriginal(fields.scriptOriginalText);
      if (fields.scriptRewrittenText) setVideoScriptRewritten(fields.scriptRewrittenText);
    }
    app.refreshVideoAnalysisJob?.(job.id).catch(() => {});
    const label = job.title || (job.sourceUrl ? job.sourceUrl.split("/").pop()?.slice(0, 20) : "") || "视频解析";
    app.addToast(`已加载「${label}」`, "success");
  };
  const buildContentPayload = () => {
    if (type === "video") {
      return {
        scriptOriginal: linesFromText(videoScriptOriginal),
        scriptRewritten: linesFromText(videoScriptRewritten),
        title: videoTitle.trim()||app.creation.topicTitle||"未命名创作",
        body: videoCopyText.trim(),
        hashtags: linesFromText(videoHashtags.replaceAll("，","\n").replaceAll(",","\n").replaceAll(" ","\n")),
        cover: content.cover||{fileId:"",url:""},
        bgmSuggestion: videoBgmSuggestion.trim(),
        sensitiveCheck: content.sensitiveCheck||{status:"passed",issues:[]},
        imagePrompt: "",
        assets: (() => {
          const videoUrl = getPublishVideoUrl();
          return videoUrl ? [{ id: activeDigitalHumanWorkflowId || "video", url: videoUrl, type: "video" }] : [];
        })(),
      };
    }
    return { scriptOriginal:linesFromText(scriptOriginalText), scriptRewritten:linesFromText(scriptRewrittenText), title:title.trim()||app.creation.topicTitle||"未命名创作", body:copyText.trim(), hashtags:linesFromText(hashtags.replaceAll("，","\n").replaceAll(",","\n").replaceAll(" ","\n")), cover:content.cover||{fileId:"",url:""}, bgmSuggestion:content.bgmSuggestion||"", sensitiveCheck:content.sensitiveCheck||{status:"passed",issues:[]}, imagePrompt:imagePromptPlan?.cards?.length ? imagePromptPlan.cards.map((card) => card.prompt.trim()).filter(Boolean).join("\n\n") : getFinalPrompt(), assets:getSelectedVariantAssets(imageGroups, selectedVariants) };
  };
  const resolveCurrentExtractReference = () => {
    const activeReference = type === "video" ? videoLinkReference : linkReference;
    if (!activeReference) return null;
    if (activeReference.historyId || activeReference.id) {
      return { ...activeReference, historyId: activeReference.historyId || activeReference.id };
    }
    const activeUrls = new Set([activeReference.url, activeReference.resolvedUrl].filter(Boolean));
    const matched = relatedExtractHistories.find((item) => activeUrls.has(item.url) || activeUrls.has(item.resolvedUrl));
    return matched ? { ...matched, historyId: matched.historyId || matched.id } : activeReference;
  };
  const getPublishVideoUrl = () => {
    const digitalHumanJob = (app.generationJobs || []).find((job) => job.id === activeDigitalHumanWorkflowId);
    const generatedVideo = digitalHumanJob?.resultPayload?.finalVideoUrl || "";
    const parsedVideo = videoLinkReference?.videos?.[0]?.url || "";
    const activeJobInput = getJobInputPayload(activeVideoAnalysisJob);
    const jobVideo = activeVideoAnalysisJob?.videoUrl || activeJobInput.videoUrl || "";
    const directInput = /^https:\/\//i.test(videoLinkText.trim()) ? videoLinkText.trim() : "";
    return generatedVideo || parsedVideo || jobVideo || directInput;
  };
  const buildPublishMediaCandidates = () => type === "video"
    ? [getPublishVideoUrl()]
      .filter(Boolean)
      .map((url) => ({ url, kind: "video", label: "创作视频" }))
    : buildImagePublishMediaCandidates(imageGroups, selectedVariants);
  const buildCreationState = (currentReference = resolveCurrentExtractReference()) => ({
    version: 1,
    linkReference: currentReference,
    linkText,
    useOriginalAsReference,
    selectedExtractHistoryIds: currentReference?.historyId ? [currentReference.historyId] : [],
    imagePromptJobId: promptJobId,
    promptJobId,
    imagePromptPlanStartError,
    imagePromptPlan,
    imageCreationPreferences,
    imageLinkPromptRows,
    showImageParseResult,
    imageJobIds,
    activeImageJobId,
    imageGroups,
    selectedVariants,
    videoPublishText,
    videoAnalysisJobId,
    scriptRewriteJobId,
    activeKimVideoScriptRewriteJobId,
    activeVideoScriptJobId,
    activeDigitalHumanWorkflowId,
    digitalHumanWorkflowIds,
    videoScriptPackage: persistedVideoScriptPackage,
    videoScriptTargetPlatform,
    videoScriptDurationSeconds,
    videoScriptContentGoal,
    videoScriptFormat,
    videoScriptToneStyle,
    videoScriptCustomRequirements,
    ratio,
    countMode: "same",
    publishMediaCandidates: buildPublishMediaCandidates(),
    publishCopy: type === "video" ? videoPublishText.trim() : copyText.trim(),
    creationWizardStep: currentStep,
    completedCreationWizardSteps: completedSteps,
    creationWizardProgressByType: {
      ...wizardProgressByTypeRef.current,
      [type]: { currentStep, completedSteps },
    },
  });
  const submitExplicit = async (saveScriptMaterial = false) => {
    const cp = buildContentPayload();
    if (!cp.body&&!cp.scriptOriginal.length&&!cp.scriptRewritten.length&&!cp.imagePrompt) { app.addToast("请先编辑脚本文案或提示词","warning"); return; }
    const currentExtractReference = resolveCurrentExtractReference();
    const hasExtractedMedia = Boolean(currentExtractReference?.images?.length || currentExtractReference?.videos?.length);
    const finalStep = (type === "image" ? IMAGE_STEPS : VIDEO_STEPS).length - 1;
    const finalCompletedSteps = completedSteps.includes(finalStep) ? completedSteps : [...completedSteps, finalStep];
    const submissionCreationState = {
      ...buildCreationState(currentExtractReference),
      creationWizardStep: finalStep,
      completedCreationWizardSteps: finalCompletedSteps,
      creationWizardProgressByType: {
        ...wizardProgressByTypeRef.current,
        [type]: { currentStep: finalStep, completedSteps: finalCompletedSteps },
      },
    };
    const task = await app.submitCreationToWorkflow({
      topicId:app.creation.topicId||"",
      targetPlatform:effectiveTargetPlatform,
      type,
      content:cp,
      creationState:submissionCreationState,
      persistExtractAssets:Boolean(currentExtractReference && hasExtractedMedia && currentExtractReference.type !== "image_job_reference"),
      extractHistoryId:currentExtractReference?.historyId || currentExtractReference?.id || null,
      linkReference:currentExtractReference,
      saveScriptMaterial,
      ...handoff,
    });
    completeStep(finalStep, finalStep, type);
    return task;
  };
  const saveScript = async () => submitExplicit(true);
  const closeCreationExtras = useCallback(() => setShowCreationExtras(false), []);
  const closeWorkflowModal = useCallback(() => setShowWorkflowModal(false), []);
  const changeWorkflowHandoff = useCallback((field, value) => {
    setHandoff((current) => ({ ...current, [field]: value }));
  }, []);
  const openWorkflowModal = () => {
    const validStages = effectiveWorkflowStageOptions.map(([value]) => value);
    const initialStage = type === "video" ? (hasDigitalHumanVideoResult ? "review" : "shooting") : "review";
    setHandoff((current) => ({
      ...current,
      status: type === "video" ? initialStage : validStages.includes(current.status) ? current.status : initialStage,
    }));
    setShowWorkflowModal(true);
  };
  const focusImageEditing = () => {
    const target = document.querySelector(imageUsesLinkFlow ? ".link-result-table-step" : ".prompt-input-section");
    target?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  };
  const handleSaveToWorkflow = async () => {
    setSavingWorkflow(true);
    try {
      const task = await submitExplicit(false);
      if (!task) return;
      app.addToast(
        readyForWorkflowCompletion
          ? type === "image" ? "创作已完成并进入审核" : "脚本已完成并进入流程"
          : "已保存进流程管理",
        "success"
      );
      setShowWorkflowModal(false);
      if (readyForWorkflowCompletion) {
        app.setActivePage?.("process");
      }
    } catch (error) {
      app.addToast(error.message || "保存失败", "warning");
    } finally {
      setSavingWorkflow(false);
    }
  };

  /* ═══════ render helpers ═══════ */
  const renderLinkRef = () => linkReference ? (
    <div className="link-reference-card">
      <strong>{linkReference.title||"已解析内容"}</strong>
      <small>{linkReference.platform} · {linkReference.type} · {linkReferenceImages.length} 图 · {linkReferenceVideos.length} 视频</small>
      {linkReference.description ? <p className="link-reference-desc">{linkReference.description}</p> : null}
      {linkReferenceImages.length ? (
        <div className="upload-preview-grid link-preview-grid">
          {linkReferenceImages.map((img, i) => (
            <div
              className={`upload-preview-item extract-thumb media-preview-trigger ${selectedExtractImage===i?"selected":""}`}
              key={`${img.url}_${i}`}
              title="点击预览"
              onClick={() => {
                setSelectedExtractImage(i);
                mediaLightbox.openMedia(
                  createMediaSlides(linkReferenceImages.map((item, index) => ({
                    url: item.url,
                    label: `解析图 ${index + 1}`,
                    downloadFilename: `starx-extract-${index + 1}.png`,
                  }))),
                  i,
                );
              }}
            >
              <img src={img.url} alt={`extracted ${i+1}`} />
              {selectedExtractImage===i && <span className="extract-thumb-badge">已选</span>}
            </div>
          ))}
        </div>
      ) : null}
      {linkReferenceImages.length > 0 && (
        <button className="btn btn-xs full-btn" disabled={reversing} onClick={() => reversePrompt(linkReferenceImages[selectedExtractImage]?.url)} style={{marginTop:8}}>
          {reversing ? "反推中..." : "反推提示词"}
        </button>
      )}
      {linkReferencePreviewVideos.length ? (
        <div className="video-preview-list">
          {linkReferencePreviewVideos.map((v, i) => (
            <div className="video-preview-item" key={`${v.url}_${i}`}>
              <video src={v.previewUrl} controls preload="metadata" />
              <div className="video-preview-actions">
                <button
                  type="button"
                  className="btn btn-xs"
                  onClick={() => mediaLightbox.openMedia([
                    createVideoSlide(v.previewUrl || v.url, {
                      title: `解析视频 ${i + 1}`,
                      downloadFilename: `starx-extract-video-${i + 1}.mp4`,
                    }),
                  ], 0)}
                >
                  放大预览
                </button>
                <button type="button" className="btn btn-xs" onClick={() => downloadMedia(v.url || v.previewUrl, `starx-extract-video-${i + 1}.mp4`)}>⬇️ 下载</button>
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  ) : null;

  const renderHistory = (items) => (
    <div className="history-list">
      {items.map((item) => (
        <button key={item.id} onClick={() => { setLinkReference(item); setLinkText(item.url||""); setExtractedImages(item.images||[]); setSelectedExtractImage(0); }} title={item.title||item.url}>
          <span>{item.title||"未命名链接"}</span>
          <small>{item.platform} · {item.images?.length||0} 图</small>
        </button>
      ))}
      {items.length===0 ? <p className="muted">暂无解析记录</p> : null}
    </div>
  );

  const renderJobs = (items) => (
    <div className="job-list">
      {items.map((j) => {
        // Build a meaningful title — never show UUID fragments
        const promptText = j.prompt || j.resultPayload?.prompt || "";
        const topicTitle = j.topicTitle || j.resultPayload?.topicTitle || "";
        const jobTypeLabel = j.jobType === "prompt" || j.type === "prompt" ? "提示词任务"
          : j.jobType === "script_rewrite" || j.type === "script_rewrite" ? "脚本改写"
          : "图片任务";
        const rawJobTitle = topicTitle || promptText || jobTypeLabel;
        const jobTitle = truncateJobText(rawJobTitle);
        // Time: use local time from submission timestamp
        const ts = j.createdAt || j.created_at || j.updatedAt || j.updated_at || j.submittedAt || "";
        const dateLabel = ts ? new Date(ts).toLocaleString("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }) : "";
        const displayTitle = truncateJobText(dateLabel ? `${jobTitle} · ${dateLabel}` : jobTitle, 44);
        return (
          <button key={j.id} onClick={() => {
            // ⚡ Instant navigation — clear old, load this job
            setType("image");
            setImageTabActive("input");
            // Clear old images; start fresh for this job
            setImageJobIds([j.id]);
            setActiveImageJobId(j.id || "");
            // Check cache first (persisted in localStorage) for instant restore
            const cached = getCachedJob(j.id);
            if (cached) {
              setImageGroups(cached.imageGroups || []);
              setSelectedVariants(cached.selectedVariants || {});
            } else {
              setImageGroups([]);
              // Try from list data
              if (j.resultPayload) {
                const groups = normalizeImageGroups(j);
                if (groups.length) { setImageGroups(groups); cacheJob(j.id, { imageGroups: groups, selectedVariants: selectFirstVariants(groups, {}) }); }
              }
            }
            setTitle(j.topicTitle || j.prompt?.slice(0, 30) || title);
            if (j.prompt) setPrompt(j.prompt);
            if (j.ratio) setRatio(j.ratio);
            if (j.selectedTagIds?.length) setSelectedTagIds(j.selectedTagIds);
            if (j.negativePrompt) setNegativePrompt(j.negativePrompt || "");
            applyImageJobReferenceInput(j);
            // Background refresh — cache result so next load is instant
            if (app.refreshGenerationJob) {
              app.refreshGenerationJob(j.id).then((fullJob) => {
                if (fullJob) applyImageJobReferenceInput(fullJob);
                if (fullJob?.resultPayload) {
                  const groups = normalizeImageGroups(fullJob);
                  cacheJob(fullJob.id, { imageGroups: groups, selectedVariants: selectFirstVariants(groups, {}) });
                }
              }).catch(() => {});
            }
            app.addToast(`已加载「${jobTitle}」`, "success");
          }}
          title={`${rawJobTitle}\nID: ${j.id}`}
          >
            <span className="job-title">{displayTitle}</span>
            <span className={`badge job-${j.status}`}>{statusText[j.status] || j.status}</span>
          </button>
        );
      })}
      {items.length === 0 ? <p className="muted">暂无任务</p> : null}
    </div>
  );

  const renderReverseHistories = () => (
    <div className="reverse-history-list">
      {reverseHistories.map((item, index) => {
        const titleText = item.positive || item.imageUrl || "未命名反推";
        const timeText = item.createdAt
          ? new Date(item.createdAt).toLocaleString("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false })
          : "";
        return (
          <button
            key={`${item.imageUrl || "reverse"}_${item.createdAt || index}`}
            onClick={() => {
              setReverseResult(item);
              if (item.positive) setPrompt(item.positive);
              setNegativePrompt(item.negative || "");
              setImageTabActive("input");
              app.addToast("已恢复反推提示词", "success");
            }}
            title={titleText}
          >
            {item.imageUrl ? <img src={item.imageUrl} alt="反推来源" /> : null}
            <span>
              <strong>{titleText.length > 28 ? `${titleText.slice(0, 28)}...` : titleText}</strong>
              <small>{timeText || "刚刚反推"}</small>
            </span>
          </button>
        );
      })}
      {reverseHistories.length === 0 ? <p className="muted">暂无反推记录</p> : null}
    </div>
  );

  /* ═══════ RENDER ═══════ */
  if (showCreationTypePicker) {
    return <CreationTypePicker onSelect={selectCreationType} />;
  }

  return (
    <div className="creation-page kim-creation-shell">
      {(loadingOverlayMessage || videoAnalysisLoading || videoTopicScriptLoading || imageGenerationLoading) ? <LoadingOverlay
        message={loadingOverlayMessage || (imageGenerationLoading ? "正在生成图片..." : videoAnalysisLoading ? "正在分析视频内容..." : "AI 正在生成视频脚本...")}
        subMessage={
          videoTopicScriptLoading
            ? "脚本生成完成后会自动进入编辑页"
            : videoAnalysisLoading
              ? (app.creation.topicId ? "分析完成后会自动进入脚本创作" : "分析完成后先展示原视频")
              : undefined
        }
      /> : null}
      <header className="creation-masthead">
        <KimCreationHeader
          accountName={app.currentAccount?.name}
          accountType={app.currentAccount?.type}
          creationType={type}
          onCreationTypeChange={changeCreationType}
          platforms={accountPlatforms}
          targetPlatform={effectiveTargetPlatform}
          onPlatformChange={(targetPlatform) => {
            if (type === "video") setVideoScriptTargetPlatform(targetPlatform);
            app.updateCreation({ targetPlatform });
          }}
          onNewCreation={startNewCreation}
          newCreationDisabled={currentStep <= 0}
        />

        <KimStepWizard
          steps={activeWizardSteps}
          currentStep={currentStep}
          completedSteps={completedSteps}
          onStepClick={handleStepClick}
        />
      </header>

      {/* ═══════════ IMAGE CREATION ═══════════ */}
      {type === "image" ? (
        <div className="wizard-container">
        {currentStep === 0 ? (showImageParseResult ? <KimLinkParseResult
          data={linkReference}
          onBack={() => setShowImageParseResult(false)}
          onToast={(message, type) => app.addToast(message, type)}
          onPreviewImage={(index) => {
            const images = (linkReference?.images || [])
              .map((image) => image?.previewUrl || image?.url || image?.src || image?.originalUrl || "")
              .filter(Boolean);
            mediaLightbox.openMedia(
              createMediaSlides(images.map((url, imageIndex) => ({
                url,
                label: `素材 ${imageIndex + 1}`,
                downloadFilename: `starx-parse-${imageIndex + 1}.png`,
              }))),
              index,
            );
          }}
        /> : <KimImageReferenceStep
          fileInputRef={fileInputRef}
          previews={imagePreviews}
          dragging={imageReferenceDragging}
          uploadLimitBytes={app.uploadLimits?.imageMaxBytes || app.referenceUploadMaxBytes}
          linkPlatform={imageLinkPlatform}
          linkText={linkText}
          extractingLink={extractingLink}
          reversing={reversing}
          onDraggingChange={setImageReferenceDragging}
          onFileSelect={selectFiles}
          onFileDrop={(droppedFiles) => selectFiles({ target: { files: droppedFiles } })}
          onRemovePreview={removeReferencePreview}
          onReverse={() => imagePreviews[0] && reversePrompt(imagePreviews[0], files[0])}
          onLinkPlatformChange={setImageLinkPlatform}
          onLinkTextChange={setLinkText}
          onExtractLink={extractLink}
          onSkip={() => { ratioInferenceIdRef.current += 1; detectedReferenceRatioRef.current = ""; changeImageRatio(DEFAULT_IMAGE_RATIO); resetImageLinkFlow(); completeStep(0, 1, "image"); }}
          onPreview={(index) => mediaLightbox.openMedia(
            createMediaSlides(imagePreviews.map((url, previewIndex) => ({
              url,
              label: `参考图 ${previewIndex + 1}`,
              downloadFilename: `starx-reference-${previewIndex + 1}.png`,
            }))),
            index,
          )}
        />) : imageUsesLinkFlow ? (currentStep === 1 ? <KimLinkPromptStep
          rows={imageLinkPromptRows}
          ratio={ratio}
          submitting={submitting || reversing}
          onBack={() => handleStepClick(0)}
          onRowPromptChange={updateImageLinkPromptRow}
          onRatioChange={changeImageRatio}
          onGenerate={generateImageLinkRows}
          onPreview={(index) => mediaLightbox.openMedia(
            createMediaSlides(imageLinkPromptRows.map((row, rowIndex) => ({
              url: row.imageUrl,
              label: `解析图片 ${rowIndex + 1}`,
              downloadFilename: `starx-prompt-ref-${rowIndex + 1}.png`,
            }))),
            index,
          )}
        /> : <KimLinkResultStep
          rows={imageLinkPromptRows}
          groupsBySlot={imageGroupsBySlot}
          selectedVariants={selectedVariants}
          title={title}
          hashtags={hashtags}
          copy={copyText}
          submitting={submitting}
          onBack={() => handleStepClick(1)}
          onTitleChange={setTitle}
          onHashtagsChange={setHashtags}
          onCopyChange={setCopyText}
          onRegenerateAll={generateImageLinkRows}
          onRegenerateRow={regenerateImageLinkRow}
          onSelectVariant={selectVariant}
          onSave={(row, imageUrl) => openSaveModal({ imageUrl, prompt: row.prompt })}
          onPreview={(rowIndex, candidateIndex = 0) => {
            const slides = imageLinkPromptRows.flatMap((row, candidateRowIndex) => {
              const group = imageGroupsBySlot.get(row.id);
              return [
                createImageSlide(row.imageUrl, {
                  title: `原图 ${candidateRowIndex + 1}`,
                  downloadFilename: `starx-original-${candidateRowIndex + 1}.png`,
                }),
                ...(group?.variants || []).map((image, variantIndex) => createImageSlide(image?.url, {
                  title: `生成图片 ${candidateRowIndex + 1} · 候选 ${variantIndex + 1}`,
                  downloadFilename: `starx-${candidateRowIndex + 1}-${variantIndex + 1}.png`,
                })),
              ].filter(Boolean);
            }).filter(Boolean);
            const previewIndex = imageLinkPromptRows.slice(0, rowIndex).reduce((count, row) => (
              count + 1 + (imageGroupsBySlot.get(row.id)?.variants?.length || 0)
            ), 0) + candidateIndex;
            mediaLightbox.openMedia(slides, previewIndex);
          }}
        />) : currentStep === 1 ? <KimTagSelectionStep
          categories={mergedCategories}
          selectedTagIds={selectedTagIds}
          templates={templates}
          activeTemplateId={activeTemplateId}
          onApplyTemplate={applyTemplate}
          onToggle={toggleTag}
          onCreateTag={openNewTagModal}
          onClear={clearTags}
          onBack={() => handleStepClick(0)}
          onSkip={() => { setImageTabActive("input"); completeStep(1, 2, "image"); }}
          onNext={() => { setImageTabActive("input"); completeStep(1, 2, "image"); }}
        /> : currentStep === 2 ? <KimImagePromptStep
          prompt={prompt}
          negativePrompt={negativePrompt}
          selectedTagCount={selectedTagIds.length}
          ratio={ratio}
          creativityLevel={creativityLevel === "low" ? "低" : creativityLevel === "medium" ? "中" : creativityLevel === "high" ? "高" : creativityLevel}
          genCount={imagePromptPlan?.cards?.length || genCount}
          materialInputRef={materialInputRef}
          materialPreviews={materialPreviews}
          imageGroups={imageGroups}
          selectedVariants={selectedVariants}
          referenceImages={imagePreviews.map((url) => ({ url, prompt }))}
          reverseResult={reverseResult}
          submitting={submitting}
          generating={generating}
          canGenerate={Boolean(imagePromptPlan?.cards?.length || prompt.trim() || selectedTagIds.length)}
          onSaveTemplate={openSaveTemplateModal}
          onBack={() => handleStepClick(1)}
          onClearReverse={() => setReverseResult(null)}
          onPromptChange={(value) => { setActiveTemplateId(""); if (imagePromptPlan?.cards?.length === 1) changeImagePromptCard(0, "prompt", value); else setPrompt(value); }}
          onNegativePromptChange={(value) => { setActiveTemplateId(""); setNegativePrompt(value); }}
          onRatioChange={(value) => { setActiveTemplateId(""); changeImageRatio(value); }}
          onCreativityChange={(level) => changeImageCreativityLevel(imagePromptPlan ? ({ 低: "low", 中: "medium", 高: "high" }[level]) : level)}
          onMaterialSelect={selectMaterialFiles}
          onMaterialOpen={() => materialInputRef.current?.click()}
          onCountChange={(value) => { setActiveTemplateId(""); setGenCount(value); }}
          onGenerate={createImages}
          onSelectVariant={selectVariant}
          onPreview={(variant) => {
            const slides = imageGroups.flatMap((group, groupIndex) =>
              (group.variants || []).map((item, variantIndex) => createImageSlide(item.url, {
                title: `图片 ${groupIndex + 1} · 变体 ${variantIndex + 1}`,
                downloadFilename: `AI生图_${groupIndex + 1}_${variantIndex + 1}.png`,
              }))
            ).filter(Boolean);
            const index = slides.findIndex((slide) => slide.src === variant.url);
            mediaLightbox.openMedia(slides, Math.max(0, index));
          }}
          onPreviewOriginal={(image, index) => mediaLightbox.openMedia(
            createMediaSlides(imagePreviews.map((url, previewIndex) => ({
              url,
              label: `原图 ${previewIndex + 1}`,
              downloadFilename: `starx-original-${previewIndex + 1}.png`,
            }))),
            index,
          )}
          onPreviewMaterials={(index) => mediaLightbox.openMedia(
            createMediaSlides(materialPreviews.map((url, previewIndex) => ({
              url,
              label: `素材图 ${previewIndex + 1}`,
              downloadFilename: `starx-material-${previewIndex + 1}.png`,
            }))),
            index,
          )}
          onDownload={(group, groupIndex) => {
            const variant = group.variants?.find((item) => item.variantId === selectedVariants[group.slotId]) || group.variants?.[0];
            if (variant?.url) downloadMedia(variant.url, `AI生图_${groupIndex + 1}.png`);
          }}
        /> : null}
        </div>
      ) : (
        /* ═══════════ VIDEO CREATION (with independent state) ═══════════ */
        <div className="wizard-container">
          {currentStep === 0 ? <KimVideoReferenceStep
            linkText={videoLinkText}
            busy={videoAnalysisLoading ? (busy || "video-analysis") : busy}
            reference={videoLinkReference}
            activeJob={activeVideoAnalysisJob}
            onLinkTextChange={setVideoLinkText}
            onAnalyze={analyzeVideoLink}
            onSkip={() => completeStep(0, 1, "video")}
            onPreviewCover={(coverUrl) => mediaLightbox.openMedia([
              createImageSlide(coverUrl, { title: "视频封面", downloadFilename: "starx-video-cover.png" }),
            ], 0)}
            onPreviewVideo={(videoUrl, coverUrl) => mediaLightbox.openMedia([
              createVideoSlide(videoUrl, {
                title: "视频预览",
                poster: coverUrl,
                downloadFilename: "starx-video.mp4",
              }),
            ], 0)}
          /> : null}

          {currentStep === 1 ? <KimVideoScriptStep
            packageResult={activeVideoScriptPackage}
            originalScript={videoScriptOriginal}
            rewrittenScript={videoScriptRewritten}
            title={videoTitle}
            hashtags={videoHashtags}
            publishCopy={videoPublishText}
            rewritePrompt={videoRewritePrompt}
            showRewritePrompt={showVideoRewritePrompt}
            rewriting={kimVideoScriptRewriting}
            trackingError={videoScriptTrackingError?.jobId === activeVideoScriptJobId ? readableError(videoScriptTrackingError.message) : ""}
            error={scriptRewriteJob?.id === activeKimVideoScriptRewriteJobId && scriptRewriteJob.status === "failed"
              ? readableError(scriptRewriteJob.error) || "AI 改写脚本失败"
              : activeVideoScriptJob?.status === "failed" ? readableError(activeVideoScriptJob.error) || "视频脚本生成失败" : ""}
            onOriginalScriptChange={setVideoScriptOriginal}
            onRewrittenScriptChange={(value) => { setVideoScriptRewritten(value); setVideoCopyText(value); }}
            onTitleChange={setVideoTitle}
            onHashtagsChange={setVideoHashtags}
            onPublishCopyChange={setVideoPublishText}
            onRewritePromptChange={setVideoRewritePrompt}
            onToggleRewritePrompt={() => setShowVideoRewritePrompt(true)}
            onCancelRewrite={() => { setShowVideoRewritePrompt(false); setVideoRewritePrompt(""); }}
            onRewrite={rewriteVideoScript}
            onCopy={() => navigator.clipboard?.writeText(videoScriptRewritten).then(() => app.addToast("已复制", "success")).catch(() => {})}
            onBack={() => handleStepClick(0)}
            onRetry={scriptRewriteJob?.id === activeKimVideoScriptRewriteJobId ? rewriteVideoScript : retryVideoScriptGeneration}
            onReconnect={retryVideoScriptTracking}
          /> : null}

          {currentStep === 1 ? (
            <section className="optional-digital-human-panel">
              <div className="optional-digital-human-copy">
                <span className="dh-kicker">OPTIONAL</span>
                <h4>数字人成片</h4>
                <p>这是可选步骤。脚本已经可以保存到流程管理进入拍摄；需要数字人口播时，再选择数字人生成成片。</p>
              </div>
              <div className="button-row">
                <button className="btn" type="button" onClick={() => setShowDigitalHumanGenerator((value) => !value)}>
                  {showDigitalHumanGenerator ? "收起数字人生成" : "选择数字人生成"}
                </button>
                {hasDigitalHumanVideoResult ? <span className="badge job-completed">已有数字人成片</span> : null}
              </div>
              {showDigitalHumanGenerator ? (
                <DigitalHumanGenerator
                  app={app}
                  creationId={app.creation.creationId}
                  initialTitle={videoTitle}
                  initialScript={videoScriptRewritten || videoCopyText}
                  onJobCreated={(job) => {
                    if (!job?.id) return;
                    setActiveDigitalHumanWorkflowId(job.id);
                    setDigitalHumanWorkflowIds((current) => current.includes(job.id) ? current : [...current, job.id]);
                    app.updateCreation?.({
                      creationState: {
                        ...(app.creation.creationState || {}),
                        activeDigitalHumanWorkflowId: job.id,
                        digitalHumanWorkflowIds: [
                          ...(app.creation.creationState?.digitalHumanWorkflowIds || []).filter((id) => id !== job.id),
                          job.id,
                        ],
                      },
                    });
                  }}
                />
              ) : null}
            </section>
          ) : null}

          <div className="creation-step-actions">
            {currentStep > 0 ? <button type="button" className="btn" onClick={() => handleStepClick(currentStep - 1)}>← 上一步</button> : <span />}
            {currentStep === 0 ? <button
              type="button"
              className="btn btn-primary"
              disabled={videoAnalysisLoading}
              onClick={continueVideoReferenceFlow}
            >{videoAnalysisLoading ? "正在分析音轨..." : "下一步：分析音轨并生成脚本 →"}</button> : null}
          </div>
        </div>
      )}

      <div className="button-row kim-creation-actions" style={{ marginTop: 16 }}>
        {readyForWorkflowCompletion ? (
          <div className="creation-completion-hint" role="status">
            <strong>✓ 创作内容已准备完成</strong>
            <small>{type === "image" ? "你仍可以继续修改或重新生成图片" : "你仍可以继续调整脚本内容"}</small>
          </div>
        ) : null}
        <button className="btn" type="button" onClick={() => setShowCreationExtras(true)}>专业工具</button>
        {readyForWorkflowCompletion && type === "image" ? (
          <button className="btn" type="button" onClick={focusImageEditing}>继续修改图片</button>
        ) : null}
        <button className={readyForWorkflowCompletion ? "btn btn-primary" : "btn"} type="button" onClick={openWorkflowModal}>
          {readyForWorkflowCompletion
            ? type === "image" ? "完成创作，进入审核 →" : "完成脚本，进入流程 →"
            : "保存到流程管理"}
        </button>
        {type === "image" && currentStep === 0 ? <button
          className="btn btn-primary creation-reference-footer-next"
          type="button"
          disabled={extractingLink || reversing}
          onClick={showImageParseResult
            ? continueImageLinkFlow
            : () => imagePreviews[0] ? reversePrompt(imagePreviews[0], files[0]) : (resetImageLinkFlow(), completeStep(0, 1, "image"))}
        >{reversing ? "处理中..." : showImageParseResult ? "继续创作 →" : "进入标签选择 →"}</button> : null}
      </div>

      <KimCreationExtrasDrawer open={showCreationExtras} onClose={closeCreationExtras}>
        {type === "video" ? <>
          <section className="kim-extras-section">
            <div className="section-row">
              <h4>视频创作偏好</h4>
              {activeVideoScriptJob ? <span className={`badge job-${activeVideoScriptJob.status}`}>{statusText[activeVideoScriptJob.status] || activeVideoScriptJob.status}</span> : null}
            </div>
            <p className="muted">{videoPreferences.targetPlatform} · {videoPreferences.durationSeconds} 秒 · {videoPreferences.videoFormat}</p>
            <button className="btn full-btn" type="button" onClick={() => { setShowCreationExtras(false); setShowVideoPreferences(true); }}>调整创作偏好</button>
          </section>
          <section className="kim-extras-section">
            <h4>拍摄执行</h4>
            <VideoShootingCardList packageResult={activeVideoScriptPackage} />
          </section>
          <section className="kim-extras-section">
            <h4>稿件补充信息</h4>
            <label className="field-label">正文 / 口播总稿</label>
            <textarea value={videoCopyText} onChange={(event) => setVideoCopyText(event.target.value)} rows={5} placeholder="编辑视频正文..." />
            <label className="field-label">BGM 建议</label>
            <input value={videoBgmSuggestion} onChange={(event) => setVideoBgmSuggestion(event.target.value)} placeholder="输入背景音乐方向" />
            {activeVideoScriptPackage?.hookSuggestion ? <p><strong>钩子：</strong>{activeVideoScriptPackage.hookSuggestion}</p> : null}
            {activeVideoScriptPackage?.rhythmNote ? <p><strong>节奏：</strong>{activeVideoScriptPackage.rhythmNote}</p> : null}
            {activeVideoScriptPackage?.contentGoalReason ? <p><strong>创作判断：</strong>{activeVideoScriptPackage.contentGoalReason}</p> : null}
            {activeVideoScriptPackage?.targetAudience ? <p><strong>目标受众：</strong>{activeVideoScriptPackage.targetAudience}</p> : null}
            {activeVideoScriptPackage?.callToAction ? <p><strong>行动引导：</strong>{activeVideoScriptPackage.callToAction}</p> : null}
            <button className="btn full-btn" type="button" onClick={saveScript}>另存为脚本素材</button>
          </section>
          <section className="kim-extras-section">
            <h4>视频解析历史</h4>
            <div className="creation-history-list">{relatedVideoAnalysisJobs.map((job) => <button type="button" className="creation-history-item" key={job.id} onClick={() => { selectVideoAnalysisJob(job); setShowCreationExtras(false); }}><strong>{job.title || "视频解析"}</strong><small>{statusText[job.status] || job.status}</small></button>)}</div>
            {relatedVideoAnalysisJobs.length === 0 ? <p className="muted">暂无视频解析记录</p> : null}
          </section>
        </> : <>
          {currentStep >= 1 && (promptJobId || imagePromptPlanStartError) && !imagePromptPlan ? <section className="kim-extras-section">
            <div className="section-row">
              <h4>图片提示词任务</h4>
              {promptJob ? <span className={`badge job-${promptJob.status}`}>{statusText[promptJob.status] || promptJob.status}</span> : null}
            </div>
            {(promptJob?.status === "failed" || imagePromptPlanStartError) ? <p className="muted">{readableError(promptJob?.error || imagePromptPlanStartError) || "图片 Prompt 计划生成失败"}</p> : <p className="muted">正在生成图片 Prompt 计划…</p>}
            <button type="button" className="btn full-btn" disabled={promptPlanRetrying} onClick={retryImagePromptPlan}>{promptPlanRetrying ? "正在重试…" : "重新生成提示词"}</button>
          </section> : null}
          <section className="kim-extras-section">
            <h4>标签与模板管理</h4>
            <div className="button-row">
              <button className="btn" type="button" onClick={() => { setShowCreationExtras(false); setShowTagManagerModal(true); }}>管理自定义标签</button>
              <button className="btn" type="button" onClick={() => { setShowCreationExtras(false); openNewTagModal("purpose"); }}>新建标签</button>
            </div>
            {templates.length > 0 ? <div className="template-list">
              {templates.map((template) => <div className="template-card" key={template.id}>
                <div className="template-card-header"><strong>{template.name}</strong><small>{template.description || "提示词模板"}</small></div>
                <div className="template-card-actions">
                  <button className="btn btn-xs btn-primary" type="button" onClick={() => { applyTemplate(template); setShowCreationExtras(false); }}>应用</button>
                  <button className="btn btn-xs btn-danger" type="button" onClick={() => deleteTemplate(template.id)}>删除</button>
                </div>
              </div>)}
            </div> : <p className="muted">暂无提示词模板</p>}
          </section>
          {currentStep >= 2 ? <section className="kim-extras-section">
            <h4>图片 Prompt 计划</h4>
            <ImagePromptPlanEditor plan={imagePromptPlan} disabled={submitting} onPlanFieldChange={changeImagePromptPlanField} onCardChange={changeImagePromptCard} onMoveCard={moveImagePromptCard} onRemoveCard={removeImagePromptCard} onAddCard={addImagePromptCard} />
            <label className="field-label">发布文案</label>
            <textarea value={copyText} onChange={(event) => imagePromptPlan ? changeImagePromptPlanField("publishCopy", event.target.value) : setCopyText(event.target.value)} rows={4} placeholder="编辑发布文案..." />
            <button className="btn full-btn" type="button" onClick={() => { setShowCreationExtras(false); openSaveTemplateModal(); }} disabled={!prompt.trim() && selectedTagIds.length === 0}>保存为模板</button>
          </section> : null}
          <section className="kim-extras-section">
            <h4>解析历史</h4>
            {renderHistory(recentExtractHistories)}
          </section>
          <section className="kim-extras-section">
            <h4>最近任务</h4>
            {renderJobs(recentJobs)}
          </section>
          <section className="kim-extras-section">
            <h4>最近反推</h4>
            {renderReverseHistories()}
          </section>
        </>}
      </KimCreationExtrasDrawer>

      {showVideoPreferences && (
        <CreationPreferenceModal
          variant="video"
          topic={{ id: app.creation.topicId, title: app.creation.topicTitle, platforms: [videoPreferences.targetPlatform] }}
          account={app.currentAccount}
          initialPreferences={videoPreferences}
          onCancel={() => setShowVideoPreferences(false)}
          onConfirm={stageVideoPreferences}
        />
      )}

      {showVideoRegenerateConfirm && pendingVideoPreferences ? (
        <ModalOverlay>
          <div className="modal video-regenerate-confirm" role="dialog" aria-modal="true" aria-labelledby="video-regenerate-title">
            <h3 id="video-regenerate-title">确认重新生成</h3>
            <p>将按新的创作偏好创建视频脚本任务。当前编辑内容会保留，只有新任务成功且仍是当前任务时才会自动填入。</p>
            <dl>
              <div><dt>平台</dt><dd>{pendingVideoPreferences.targetPlatform}</dd></div>
              <div><dt>时长</dt><dd>{pendingVideoPreferences.durationSeconds} 秒</dd></div>
              <div><dt>内容目的</dt><dd>{pendingVideoPreferences.contentGoal}</dd></div>
              <div><dt>视频形式</dt><dd>{pendingVideoPreferences.videoFormat}</dd></div>
              <div><dt>表达风格</dt><dd>{pendingVideoPreferences.toneStyle}</dd></div>
            </dl>
            <div className="modal-actions">
              <button type="button" className="btn" onClick={cancelVideoScriptRegeneration}>取消</button>
              <button type="button" className="btn btn-primary" disabled={busy === "video-script"} onClick={confirmVideoScriptRegeneration}>确认重新生成</button>
            </div>
          </div>
        </ModalOverlay>
      ) : null}

      <KimWorkflowSaveModal
        open={showWorkflowModal}
        type={type}
        handoff={handoff}
        priorityLabels={priorityLabels}
        workflowStages={effectiveWorkflowStageOptions}
        assetPersistenceState={assetPersistenceState}
        assetPersistenceText={assetPersistenceText}
        readyForCompletion={readyForWorkflowCompletion}
        saving={savingWorkflow}
        onChange={changeWorkflowHandoff}
        onCancel={closeWorkflowModal}
        onConfirm={handleSaveToWorkflow}
      />

      {/* ── Media Preview Lightbox ── */}
      <MediaLightbox
        open={mediaLightbox.open}
        index={mediaLightbox.index}
        slides={mediaLightbox.slides}
        onClose={mediaLightbox.closeMedia}
        onIndexChange={mediaLightbox.setMediaIndex}
      />

      {/* ── Save to Material Modal ── */}
      {showSaveModal && saveModalData && (
        <ModalOverlay>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>保存到素材库</h3>
            {saveModalData.imageUrl && <div className="save-modal-preview"><img src={saveModalData.imageUrl} alt="preview" /></div>}
            <label><span className="field-label">作品名称</span><input defaultValue={`AI作品_${new Date().toISOString().slice(0,10)}`} id="save-material-name" /></label>
            <label><span className="field-label">分类</span><select defaultValue="uncategorized" id="save-material-category">{MOCK_MATERIAL_CATEGORIES.filter((c) => c.id!=="all").map((c) => <option key={c.id} value={c.id}>{c.icon} {c.name}</option>)}</select></label>
            <label><span className="field-label">标签（空格分隔）</span><input id="save-material-tags" placeholder="#封面 #摄影" /></label>
            <div className="modal-actions">
              <button className="btn" onClick={() => setShowSaveModal(false)}>取消</button>
              <button className="btn btn-primary" onClick={() => { const n=document.getElementById("save-material-name")?.value; const c=document.getElementById("save-material-category")?.value; const t=document.getElementById("save-material-tags")?.value; handleSaveToLibrary({name:n||`AI作品_${Date.now()}`, category:c||"uncategorized", tags:(t||"").split(/[\s,，#]+/).filter(Boolean), imageUrl:saveModalData.imageUrl, prompt:saveModalData.prompt||getFinalPrompt()}); setShowSaveModal(false); }}>确认保存</button>
            </div>
          </div>
        </ModalOverlay>
      )}

      {/* ── Save Template Modal ── */}
      {showSaveTplModal && (
        <ModalOverlay>
          <form className="modal prompt-template-save-modal" role="dialog" aria-modal="true" aria-labelledby="prompt-template-save-title" onSubmit={(event) => { event.preventDefault(); confirmSaveTemplate(); }}>
            <div className="prompt-template-save-heading">
              <div><span>REUSABLE PROMPT</span><h3 id="prompt-template-save-title">保存为提示词模板</h3><p>保存当前提示词组合，之后可在标签选择页一键应用。</p></div>
              <button className="prompt-template-save-close" type="button" onClick={() => setShowSaveTplModal(false)} disabled={savingTemplate} aria-label="关闭">×</button>
            </div>
            <label><span className="field-label">模板名称 *</span><input value={tplSaveName} onChange={(e) => setTplSaveName(e.target.value)} placeholder="如：赛博朋克人物通用" autoFocus /></label>
            <label><span className="field-label">模板说明</span><input value={tplSaveDesc} onChange={(e) => setTplSaveDesc(e.target.value)} placeholder="描述该模板的用途、适用场景等" /></label>
            <div>
              <span className="field-label">预览内容</span>
              <div className="template-save-preview">
                <div><span>提示词</span><p>{prompt ? `${prompt.slice(0, 160)}${prompt.length > 160 ? "..." : ""}` : "仅使用所选标签"}</p></div>
                <div className="template-save-facts">
                  <span>{selectedTagIds.length} 个标签</span><span>{ratio}</span><span>{genCount} 张</span>{negativePrompt && <span>含负向提示词</span>}
                </div>
              </div>
            </div>
            <div className="modal-actions">
              <button className="btn" type="button" onClick={() => setShowSaveTplModal(false)} disabled={savingTemplate}>取消</button>
              <button className="btn btn-primary" type="submit" disabled={!tplSaveName.trim() || savingTemplate}>{savingTemplate ? "保存中..." : "确认保存"}</button>
            </div>
          </form>
        </ModalOverlay>
      )}

      {/* ── Tag Manager Modal ── */}
      {showTagManagerModal && (
        <ModalOverlay>
          <div className="modal tag-manager-modal">
            <h3>管理自定义标签</h3>
            {customTagCategories.length === 0 ? <p className="muted">暂无自定义标签</p> : (
              <div className="tag-manager-list">
                {customTagCategories.map((cat) => (
                  <section key={cat.id} className="tag-manager-category">
                    <div className="tag-manager-category-name">{cat.name}</div>
                    {cat.tags.map((tag) => (
                      <div key={tag.id} className="tag-manager-row">
                        {editingTag === tag.id ? (
                          <div className="tag-manager-edit">
                            <input value={editTagName} onChange={(e) => setEditTagName(e.target.value)} placeholder="标签名称" />
                            <textarea value={editTagPrompt} onChange={(e) => setEditTagPrompt(e.target.value)} rows={2} placeholder="提示词内容" />
                            <div className="tag-manager-edit-actions">
                              <button className="btn btn-xs btn-primary" onClick={() => {
                                if (!editTagName.trim() || !editTagPrompt.trim()) return;
                                setCustomTags((prev) => prev.map((t) => t.id === tag.id ? { ...t, name: editTagName.trim(), prompt: editTagPrompt.trim() } : t));
                                setEditingTag(null);
                                app.addToast("标签已更新", "success");
                              }}>保存</button>
                              <button className="btn btn-xs" onClick={() => setEditingTag(null)}>取消</button>
                            </div>
                          </div>
                        ) : (
                          <>
                            <div className="tag-manager-meta">
                              <strong>{tag.name}</strong>
                              {tag.prompt && <small>{tag.prompt}</small>}
                            </div>
                            <div className="tag-manager-btns">
                              <button className="btn btn-xs" onClick={() => { setEditingTag(tag.id); setEditTagName(tag.name); setEditTagPrompt(tag.prompt || ""); }}>编辑</button>
                              <button className="btn btn-xs btn-danger tag-manager-delete" onClick={() => deleteCustomTag(tag.id)}>删除</button>
                            </div>
                          </>
                        )}
                      </div>
                    ))}
                  </section>
                ))}
              </div>
            )}
            <div className="modal-actions">
              <button className="btn" onClick={() => setShowTagManagerModal(false)}>关闭</button>
              <button className="btn btn-primary" onClick={() => { setShowTagManagerModal(false); openNewTagModal("purpose"); }}>新建标签</button>
            </div>
          </div>
        </ModalOverlay>
      )}

      <NewPromptTagModal
        open={showNewTagModal}
        category={newTagCategoryDetails}
        onClose={() => setShowNewTagModal(false)}
        onSubmit={addCustomTag}
      />
      {/* ── New Custom Tag Category Modal ── */}
      {showNewCategoryModal && (
        <ModalOverlay>
          <div className="modal">
            <h3>新建标签分类</h3>
            <label><span className="field-label">分类名称 *</span><input value={newCategoryName} onChange={(e) => setNewCategoryName(e.target.value)} placeholder="如：光线、季节..." autoFocus /></label>
            <div className="modal-actions">
              <button className="btn" onClick={() => setShowNewCategoryModal(false)}>取消</button>
              <button className="btn btn-primary" onClick={async () => {
                if (!newCategoryName.trim()) return;
                if (app.createCustomTagCategory) {
                  const cat = await app.createCustomTagCategory(newCategoryName.trim());
                  if (!cat) return;
                  await app.refreshPromptTags();
                }
                setNewCategoryName("");
                setShowNewCategoryModal(false);
              }} disabled={!newCategoryName.trim()}>确认创建</button>
            </div>
          </div>
        </ModalOverlay>
      )}
    </div>
  );
}
