export const ACCOUNT_PLATFORM_OPTIONS = ["小红书", "视频号", "抖音", "快手"];

export const KNOWLEDGE_BASE_FIELD_OPTIONS = [
  "productIntro",
  "brandStory",
  "price",
  "logoUrl",
  "imageMaterials",
  "contactInfo",
  "websiteUrl",
];

function trimValue(value) {
  return typeof value === "string" ? value.trim() : "";
}

function buildEnabledFields(seed = {}) {
  return KNOWLEDGE_BASE_FIELD_OPTIONS.reduce((result, key) => {
    result[key] = seed[key] ?? true;
    return result;
  }, {});
}

function buildPublishSettings(platforms = [], seed = {}) {
  return platforms.reduce((result, platform) => {
    result[platform] = {
      androidId: trimValue(seed?.[platform]?.androidId),
    };
    return result;
  }, {});
}

export function createEmptyAccountProfileForm() {
  return {
    name: "",
    description: "",
    purpose: "",
    type: "普通号",
    platforms: ["小红书"],
    accountLinks: {},
    platformAccounts: { 小红书: "" },
    benchmarkAccounts: { 小红书: "" },
    publishSettings: { 小红书: { androidId: "" } },
    industry: "",
    productService: "",
    targetCity: "",
    targetAudience: "",
    conversionGoal: "",
    knowledgeBaseId: "",
  };
}

export function createAccountProfileFormFromAccount(account = {}) {
  const platforms = Array.isArray(account.platforms) && account.platforms.length > 0
    ? account.platforms
    : account.platform
      ? [account.platform]
      : ["小红书"];
  const accountLinks = platforms.reduce((result, platform) => {
    result[platform] = account.accountLinks?.[platform] || "";
    return result;
  }, {});
  const platformAccounts = platforms.reduce((result, platform) => {
    if (platform === "抖音" || platform === "小红书") {
      result[platform] = account.platformAccounts?.[platform] || "";
    }
    return result;
  }, {});
  const benchmarkAccounts = platforms.reduce((result, platform) => {
    if (platform === "抖音" || platform === "小红书") {
      result[platform] = account.benchmarkAccounts?.[platform] || "";
    }
    return result;
  }, {});

  return {
    name: account.name || "",
    description: account.description || "",
    purpose: account.purpose || "",
    type: account.type || "普通号",
    platforms,
    accountLinks,
    platformAccounts,
    benchmarkAccounts,
    publishSettings: buildPublishSettings(platforms, account.publishSettings || {}),
    industry: account.industry || "",
    productService: account.productService || "",
    targetCity: account.targetCity || "",
    targetAudience: account.targetAudience || "",
    conversionGoal: account.conversionGoal || "",
    knowledgeBaseId: account.knowledgeBaseId || account.knowledgeBaseSummary?.id || "",
  };
}

export function createEmptyKnowledgeBaseForm() {
  return {
    name: "",
    productName: "",
    industry: "",
    productIntro: "",
    brandStory: "",
    price: "",
    logoUrl: "",
    imageMaterials: [""],
    contactInfo: "",
    websiteUrl: "",
    enabledFields: buildEnabledFields(),
  };
}

export function validateAccountProfileStep(form, step = 1) {
  const errors = [];

  if (step === 1) {
    if (!trimValue(form?.name)) {
      errors.push("请填写账号名称");
    }
    if (!trimValue(form?.type)) {
      errors.push("请选择账号类型");
    }
    if (!trimValue(form?.description)) {
      errors.push("请填写账号定位");
    }
  }

  if (step === 2) {
    if (!Array.isArray(form?.platforms) || form.platforms.length === 0) {
      errors.push("请至少选择一个平台");
    }
    for (const platform of form?.platforms || []) {
      const usesPlatformAccount = platform === "抖音" || platform === "小红书";
      const hasPlatformAccount = trimValue(form?.platformAccounts?.[platform]);
      const hasLegacyLink = trimValue(form?.accountLinks?.[platform]);
      if (usesPlatformAccount && !hasPlatformAccount && !hasLegacyLink) {
        errors.push(`请填写${platform}号`);
      }
      if (!usesPlatformAccount && !hasLegacyLink) {
        errors.push(`请填写${platform}主页链接`);
      }
    }
  }

  return errors;
}

export function validateAccountProfileForm(form) {
  return [
    ...validateAccountProfileStep(form, 1),
    ...validateAccountProfileStep(form, 2),
  ];
}

export function normalizeAccountProfilePayload(form) {
  const platforms = Array.isArray(form?.platforms) ? form.platforms.filter(Boolean) : [];
  const accountLinks = platforms.reduce((result, platform) => {
    const value = trimValue(form?.accountLinks?.[platform]);
    if (value) result[platform] = value;
    return result;
  }, {});
  const platformAccounts = platforms.reduce((result, platform) => {
    const value = trimValue(form?.platformAccounts?.[platform]);
    if (value && (platform === "抖音" || platform === "小红书")) {
      result[platform] = value;
    }
    return result;
  }, {});
  const benchmarkAccounts = platforms.reduce((result, platform) => {
    const value = trimValue(form?.benchmarkAccounts?.[platform]);
    if (value && (platform === "抖音" || platform === "小红书")) {
      result[platform] = value;
    }
    return result;
  }, {});
  const publishSettings = platforms.reduce((result, platform) => {
    const androidId = trimValue(form?.publishSettings?.[platform]?.androidId);
    if (androidId) {
      result[platform] = { androidId };
    }
    return result;
  }, {});

  return {
    name: trimValue(form?.name),
    description: trimValue(form?.description),
    purpose: trimValue(form?.purpose),
    type: trimValue(form?.type) || "普通号",
    platforms,
    accountLinks,
    platformAccounts,
    benchmarkAccounts,
    publishSettings,
    industry: trimValue(form?.industry),
    productService: trimValue(form?.productService),
    targetCity: trimValue(form?.targetCity),
    targetAudience: trimValue(form?.targetAudience),
    conversionGoal: trimValue(form?.conversionGoal),
    knowledgeBaseId: trimValue(form?.knowledgeBaseId),
  };
}

export function normalizeKnowledgeBasePayload(form) {
  return {
    name: trimValue(form?.name),
    productName: trimValue(form?.productName),
    industry: trimValue(form?.industry),
    productIntro: trimValue(form?.productIntro),
    brandStory: trimValue(form?.brandStory),
    price: trimValue(form?.price),
    logoUrl: trimValue(form?.logoUrl),
    imageMaterials: Array.isArray(form?.imageMaterials)
      ? form.imageMaterials.map(trimValue).filter(Boolean)
      : [],
    contactInfo: trimValue(form?.contactInfo),
    websiteUrl: trimValue(form?.websiteUrl),
    enabledFields: buildEnabledFields(form?.enabledFields || {}),
  };
}
