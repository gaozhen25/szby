import assert from "node:assert/strict";
import test from "node:test";

import {
  ACCOUNT_PLATFORM_OPTIONS,
  KNOWLEDGE_BASE_FIELD_OPTIONS,
  createEmptyAccountProfileForm,
  createEmptyKnowledgeBaseForm,
  createAccountProfileFormFromAccount,
  normalizeAccountProfilePayload,
  normalizeKnowledgeBasePayload,
  validateAccountProfileForm,
  validateAccountProfileStep,
} from "./accountProfileForm.js";

test("createEmptyAccountProfileForm seeds a single default platform and blank fields", () => {
  const form = createEmptyAccountProfileForm();

  assert.deepEqual(form.platforms, ["小红书"]);
  assert.deepEqual(form.accountLinks, {});
  assert.deepEqual(form.platformAccounts, { 小红书: "" });
  assert.equal(form.knowledgeBaseId, "");
  assert.equal(form.industry, "");
  assert.ok(ACCOUNT_PLATFORM_OPTIONS.includes("视频号"));
  assert.ok(ACCOUNT_PLATFORM_OPTIONS.includes("快手"));
});

test("validateAccountProfileForm accepts configured Douyin and Xiaohongshu handles", () => {
  const errors = validateAccountProfileForm({
    name: "星颜小红书主号",
    description: "护肤内容种草",
    type: "专业号",
    platforms: ["小红书", "抖音"],
    platformAccounts: {
      小红书: "starx_xhs",
      抖音: "starx_douyin",
    },
    benchmarkAccounts: {
      小红书: "bench_xhs",
      抖音: "bench_dy",
    },
    purpose: "",
    industry: "",
    productService: "",
    targetCity: "",
    targetAudience: "",
    conversionGoal: "",
    knowledgeBaseId: "",
  });

  assert.deepEqual(errors, []);
});

test("validateAccountProfileForm allows missing optional benchmark accounts", () => {
  const errors = validateAccountProfileForm({
    name: "星颜小红书主号",
    description: "护肤内容种草",
    type: "专业号",
    platforms: ["小红书", "抖音"],
    platformAccounts: {
      小红书: "starx_xhs",
      抖音: "starx_douyin",
    },
    benchmarkAccounts: {
      小红书: "bench_xhs",
    },
  });

  assert.deepEqual(errors, []);
});

test("validateAccountProfileForm reports every missing required field by name", () => {
  const errors = validateAccountProfileForm({
    name: " ",
    description: "",
    type: "",
    platforms: [],
  });

  assert.deepEqual(errors, [
    "请填写账号名称",
    "请选择账号类型",
    "请填写账号定位",
    "请至少选择一个平台",
  ]);
});

test("validateAccountProfileStep only checks required fields for the current step", () => {
  assert.deepEqual(
    validateAccountProfileStep({ name: "", type: "", description: "", platforms: [] }, 1),
    ["请填写账号名称", "请选择账号类型", "请填写账号定位"]
  );
  assert.deepEqual(
    validateAccountProfileStep({ name: "主号", type: "普通号", description: "定位", platforms: [] }, 2),
    ["请至少选择一个平台"]
  );
  assert.deepEqual(
    validateAccountProfileStep({ name: "", type: "", description: "", platforms: [] }, 3),
    []
  );
});

test("normalizeAccountProfilePayload trims fields and keeps only selected platform links", () => {
  const payload = normalizeAccountProfilePayload({
    name: " 星颜小红书主号 ",
    description: " 护肤内容种草 ",
    purpose: " 私域转化 ",
    type: "专业号",
    platforms: ["小红书", "抖音"],
    accountLinks: {
      小红书: " https://www.xiaohongshu.com/user/profile/demo ",
      抖音: " https://www.douyin.com/user/demo ",
      视频号: "https://channels.weixin.qq.com/profile/should-remove",
    },
    platformAccounts: {
      小红书: " xhs-demo ",
      抖音: " douyin-demo ",
      视频号: "should-remove",
    },
    benchmarkAccounts: {
      小红书: " bench_xhs ",
      抖音: " bench_dy ",
      视频号: "should-remove",
    },
    industry: " 美妆护肤 ",
    productService: " 修护精华 ",
    targetCity: " 上海 ",
    targetAudience: " 白领女性 ",
    conversionGoal: " 留资 ",
    knowledgeBaseId: " kb-1 ",
  });

  assert.deepEqual(payload, {
    name: "星颜小红书主号",
    description: "护肤内容种草",
    purpose: "私域转化",
    type: "专业号",
    platforms: ["小红书", "抖音"],
    accountLinks: {
      小红书: "https://www.xiaohongshu.com/user/profile/demo",
      抖音: "https://www.douyin.com/user/demo",
    },
    platformAccounts: {
      小红书: "xhs-demo",
      抖音: "douyin-demo",
    },
    benchmarkAccounts: {
      小红书: "bench_xhs",
      抖音: "bench_dy",
    },
    publishSettings: {},
    industry: "美妆护肤",
    productService: "修护精华",
    targetCity: "上海",
    targetAudience: "白领女性",
    conversionGoal: "留资",
    knowledgeBaseId: "kb-1",
  });
});

test("createAccountProfileFormFromAccount hydrates editable fields and publish settings", () => {
  const form = createAccountProfileFormFromAccount({
    name: "星颜全域号",
    description: "多平台内容种草",
    purpose: "私域转化",
    type: "专业号",
    platforms: ["小红书", "抖音"],
    accountLinks: {
      小红书: "https://www.xiaohongshu.com/user/profile/demo",
      抖音: "https://www.douyin.com/user/demo",
    },
    platformAccounts: {
      小红书: "xhs-demo",
      抖音: "douyin-demo",
    },
    benchmarkAccounts: {
      小红书: "bench_xhs",
      抖音: "bench_dy",
    },
    publishSettings: {
      抖音: { androidId: "android-dy", platform: "douyin" },
    },
    industry: "美妆护肤",
    productService: "修护精华",
    targetCity: "上海",
    targetAudience: "白领女性",
    conversionGoal: "留资",
    knowledgeBaseId: "kb-1",
  });

  assert.deepEqual(form.platforms, ["小红书", "抖音"]);
  assert.deepEqual(form.accountLinks, {
    小红书: "https://www.xiaohongshu.com/user/profile/demo",
    抖音: "https://www.douyin.com/user/demo",
  });
  assert.deepEqual(form.platformAccounts, {
    小红书: "xhs-demo",
    抖音: "douyin-demo",
  });
  assert.deepEqual(form.benchmarkAccounts, {
    小红书: "bench_xhs",
    抖音: "bench_dy",
  });
  assert.deepEqual(form.publishSettings, {
    小红书: { androidId: "" },
    抖音: { androidId: "android-dy" },
  });
  assert.equal(form.knowledgeBaseId, "kb-1");
});

test("normalizeAccountProfilePayload includes only configured android publish settings", () => {
  const payload = normalizeAccountProfilePayload({
    name: " 星颜全域号 ",
    description: " 多平台内容种草 ",
    purpose: " 私域转化 ",
    type: "专业号",
    platforms: ["小红书", "抖音"],
    accountLinks: {
      小红书: " https://www.xiaohongshu.com/user/profile/demo ",
      抖音: " https://www.douyin.com/user/demo ",
    },
    publishSettings: {
      小红书: { androidId: "   " },
      抖音: { androidId: " android-dy " },
    },
    industry: " 美妆护肤 ",
    productService: " 修护精华 ",
    targetCity: " 上海 ",
    targetAudience: " 白领女性 ",
    conversionGoal: " 留资 ",
    knowledgeBaseId: " kb-1 ",
  });

  assert.deepEqual(payload.publishSettings, {
    抖音: { androidId: "android-dy" },
  });
});

test("createEmptyKnowledgeBaseForm enables every optional field by default", () => {
  const form = createEmptyKnowledgeBaseForm();

  assert.equal(form.name, "");
  assert.equal(form.industry, "");
  assert.deepEqual(form.imageMaterials, [""]);
  assert.equal(Object.keys(form.enabledFields).length, KNOWLEDGE_BASE_FIELD_OPTIONS.length);
  assert.ok(Object.values(form.enabledFields).every(Boolean));
});

test("normalizeKnowledgeBasePayload trims values and removes blank image materials", () => {
  const payload = normalizeKnowledgeBasePayload({
    name: " 品牌基础库 ",
    productName: " 星颜精华 ",
    industry: " 美妆护肤 ",
    productIntro: " 主打修护 ",
    brandStory: " 来自实验室团队 ",
    price: " 299元 ",
    logoUrl: " https://cdn.example.com/logo.png ",
    imageMaterials: [" https://cdn.example.com/1.png ", "   ", "https://cdn.example.com/2.png"],
    contactInfo: " VX: starx ",
    websiteUrl: " https://brand.example.com ",
    enabledFields: {
      productIntro: true,
      brandStory: false,
      price: true,
      logoUrl: true,
      imageMaterials: true,
      contactInfo: true,
      websiteUrl: false,
    },
  });

  assert.deepEqual(payload, {
    name: "品牌基础库",
    productName: "星颜精华",
    industry: "美妆护肤",
    productIntro: "主打修护",
    brandStory: "来自实验室团队",
    price: "299元",
    logoUrl: "https://cdn.example.com/logo.png",
    imageMaterials: ["https://cdn.example.com/1.png", "https://cdn.example.com/2.png"],
    contactInfo: "VX: starx",
    websiteUrl: "https://brand.example.com",
    enabledFields: {
      productIntro: true,
      brandStory: false,
      price: true,
      logoUrl: true,
      imageMaterials: true,
      contactInfo: true,
      websiteUrl: false,
    },
  });
});
