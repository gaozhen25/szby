import assert from "node:assert/strict";
import test from "node:test";

import { starxApi } from "./starx.js";

function directUploadFetch(calls, businessPayload = { id: "ok" }) {
  let uploadIndex = 0;
  return async (url, options = {}) => {
    const href = String(url);
    calls.push({ url: href, options });
    if (href.endsWith("/uploads/presign")) {
      uploadIndex += 1;
      const currentUploadIndex = uploadIndex;
      const request = JSON.parse(options.body);
      return {
        ok: true,
        status: 200,
        json: async () => ({
          uploadId: `upl_${currentUploadIndex}`,
          method: "PUT",
          uploadUrl: `https://upload.example.test/upl_${currentUploadIndex}`,
          objectUrl: `https://oss.example.test/upl_${currentUploadIndex}/${request.filename}`,
          headers: { "Content-Type": request.contentType },
        }),
      };
    }
    if (href.startsWith("https://upload.example.test/")) {
      return {
        ok: true,
        status: 200,
        headers: { get: (name) => name === "ETag" ? `"etag-${uploadIndex}"` : null },
      };
    }
    return { ok: true, status: 200, json: async () => businessPayload };
  };
}

test("digital human APIs use account-scoped profiles and video workflows", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = directUploadFetch(calls, { id: "wf_dh" });

  try {
    await starxApi.getDigitalHumanTrainingScript();
    await starxApi.getDigitalHumanProfiles("acc1");
    await starxApi.createDigitalHumanProfile("acc1", {
      name: "创始人",
      videoFile: new Blob(["video"], { type: "video/mp4" }),
      trainingScriptVersion: "zh_cn_v1",
      consentConfirmed: true,
    });
    await starxApi.createDigitalHumanVideo("acc1", {
      profileId: "dhp1",
      title: "产品口播",
      scriptText: "新的文案",
    });
    await starxApi.getDigitalHumanVideoJobs("acc1", {
      page: 2,
      pageSize: 4,
      creationId: "creation 1",
    });
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(calls[0].url, "http://127.0.0.1:8000/api/v1/digital-human/training-script");
  assert.equal(calls[1].url, "http://127.0.0.1:8000/api/v1/accounts/acc1/digital-human/profiles");
  assert.equal(calls[2].url, "http://127.0.0.1:8000/api/v1/uploads/presign");
  assert.equal(JSON.parse(calls[2].options.body).purpose, "digital_human_source");
  assert.equal(calls[3].url, "https://upload.example.test/upl_1");
  assert.equal(calls[4].url, "http://127.0.0.1:8000/api/v1/accounts/acc1/digital-human/profiles");
  assert.equal(JSON.parse(calls[4].options.body).sourceVideo.uploadId, "upl_1");
  assert.equal(calls[5].url, "http://127.0.0.1:8000/api/v1/accounts/acc1/digital-human/videos");
  assert.equal(JSON.parse(calls[5].options.body).profileId, "dhp1");
  assert.equal(
    calls[6].url,
    "http://127.0.0.1:8000/api/v1/accounts/acc1/digital-human/videos?page=2&pageSize=4&creationId=creation+1"
  );
});

test("digital human editing assets use the unified direct upload endpoint", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = directUploadFetch(calls);

  try {
    await starxApi.uploadDigitalHumanEditingAsset(
      "acc1",
      new Blob(["music"], { type: "audio/mpeg" }),
    );
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(calls[0].url, "http://127.0.0.1:8000/api/v1/uploads/presign");
  assert.equal(JSON.parse(calls[0].options.body).purpose, "digital_human_editing_asset");
  assert.equal(JSON.parse(calls[0].options.body).accountId, "acc1");
  assert.equal(calls[1].url, "https://upload.example.test/upl_1");
});

test("digital human MP4 background music uses the dedicated upload purpose", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = directUploadFetch(calls);

  try {
    await starxApi.uploadDigitalHumanEditingAsset(
      "acc1",
      new File(["music"], "music.mp4", { type: "video/mp4" }),
      "digital_human_background_music",
    );
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(
    JSON.parse(calls[0].options.body).purpose,
    "digital_human_background_music",
  );
  assert.equal(JSON.parse(calls[0].options.body).contentType, "video/mp4");
});

test("digital human image uploads normalize local JPG and extension-only MIME types", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = directUploadFetch(calls);

  try {
    await starxApi.uploadDigitalHumanEditingAsset(
      "acc1",
      new File(["jpg"], "background.jpg", { type: "image/jpg" }),
    );
    await starxApi.uploadDigitalHumanEditingAsset(
      "acc1",
      new File(["png"], "bubble.png"),
    );
  } finally {
    globalThis.fetch = originalFetch;
  }

  const declarations = calls
    .filter((call) => call.url.endsWith("/uploads/presign"))
    .map((call) => JSON.parse(call.options.body));
  assert.equal(declarations[0].contentType, "image/jpeg");
  assert.equal(declarations[1].contentType, "image/png");
});

test("getAccounts appends pagination and search query params", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options });
    return {
      ok: true,
      status: 200,
      json: async () => ({ items: [], total: 0, page: 2, pageSize: 12 }),
    };
  };

  try {
    await starxApi.getAccounts({ page: 2, pageSize: 12, keyword: "美妆", platform: "小红书" });
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(
    calls[0].url,
    "http://127.0.0.1:8000/api/v1/accounts?page=2&pageSize=12&keyword=%E7%BE%8E%E5%A6%86&platform=%E5%B0%8F%E7%BA%A2%E4%B9%A6"
  );
});

test("topic refresh workflow api methods call topic endpoints", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options });
    return {
      ok: true,
      status: 200,
      json: async () => ({ id: "wf_topic" }),
    };
  };

  try {
    await starxApi.refreshTopics("acc1");
    await starxApi.getTopicRefreshWorkflow("acc1", "wf_topic");
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(calls[0].url, "http://127.0.0.1:8000/api/v1/accounts/acc1/topics/refresh-batch");
  assert.equal(calls[0].options.method, "POST");
  assert.equal(
    calls[1].url,
    "http://127.0.0.1:8000/api/v1/accounts/acc1/topics/refresh-workflows/wf_topic"
  );
});

test("duplicate task api posts to the account-scoped workflow endpoint", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options });
    return {
      ok: true,
      status: 200,
      json: async () => ({ id: "task-copy" }),
    };
  };

  try {
    await starxApi.duplicateTask("acc1", "task-source");
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(
    calls[0].url,
    "http://127.0.0.1:8000/api/v1/accounts/acc1/tasks/task-source/duplicate"
  );
  assert.equal(calls[0].options.method, "POST");
});

test("topic favorites use account-scoped persistence endpoints", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options });
    const deleting = options.method === "DELETE";
    return {
      ok: true,
      status: deleting ? 204 : 200,
      json: async () => deleting ? null : [],
    };
  };

  try {
    await starxApi.getFavoriteTopics("acc1");
    await starxApi.favoriteTopic("acc1", "t1");
    await starxApi.deleteFavoriteTopic("acc1", "fav_1");
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(calls[0].url, "http://127.0.0.1:8000/api/v1/accounts/acc1/favorite-topics");
  assert.equal(calls[1].url, "http://127.0.0.1:8000/api/v1/accounts/acc1/favorite-topics/t1");
  assert.equal(calls[1].options.method, "POST");
  assert.equal(calls[2].url, "http://127.0.0.1:8000/api/v1/accounts/acc1/favorite-topics/fav_1");
  assert.equal(calls[2].options.method, "DELETE");
});

test("report workflow api methods call report workflow endpoints", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options });
    return {
      ok: true,
      status: 200,
      json: async () => ({ id: "wf_report" }),
    };
  };

  try {
    await starxApi.createReportWorkflow("acc1", true);
    await starxApi.createSimilarAccountsReportWorkflow("acc1", false);
    await starxApi.createComplianceRulesReportWorkflow("acc1", true);
    await starxApi.createTargetUserProfileReportWorkflow("acc1", false);
    await starxApi.createHotContentsReportWorkflow("acc1", true);
    await starxApi.getLatestReportWorkflow("acc1");
    await starxApi.getActiveReportWorkflows("acc1");
    await starxApi.getReportWorkflow("acc1", "wf_report");
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(calls[0].url, "http://127.0.0.1:8000/api/v1/accounts/acc1/report/workflows");
  assert.equal(calls[0].options.method, "POST");
  assert.deepEqual(JSON.parse(calls[0].options.body), {
    referenceComments: true,
  });
  assert.equal(calls[1].url, "http://127.0.0.1:8000/api/v1/accounts/acc1/report/similar-accounts/workflows");
  assert.equal(calls[2].url, "http://127.0.0.1:8000/api/v1/accounts/acc1/report/compliance-rules/workflows");
  assert.equal(calls[3].url, "http://127.0.0.1:8000/api/v1/accounts/acc1/report/target-user-profile/workflows");
  assert.equal(calls[4].url, "http://127.0.0.1:8000/api/v1/accounts/acc1/report/hot-contents/workflows");
  assert.equal(calls[5].url, "http://127.0.0.1:8000/api/v1/accounts/acc1/report/workflows/latest");
  assert.equal(calls[5].options.method, undefined);
  assert.equal(calls[6].url, "http://127.0.0.1:8000/api/v1/accounts/acc1/report/workflows/active");
  assert.equal(calls[6].options.method, undefined);
  assert.equal(calls[7].url, "http://127.0.0.1:8000/api/v1/accounts/acc1/report/workflows/wf_report");
  assert.equal(calls[7].options.method, undefined);
});

test("manual report similar accounts use account-scoped add and delete endpoints", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options });
    return { ok: true, status: 200, json: async () => ({ similarAccounts: [] }) };
  };
  const payload = {
    name: "手动对标账号",
    platform: "小红书",
    profileUrl: "https://www.xiaohongshu.com/user/profile/manual-peer",
    similarityReason: "内容定位接近",
  };

  try {
    await starxApi.resolveReportSimilarAccount("acc1", payload.profileUrl);
    await starxApi.addReportSimilarAccount("acc1", payload);
    await starxApi.deleteReportSimilarAccount("acc1", "manual_key/with spaces");
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(
    calls[0].url,
    "http://127.0.0.1:8000/api/v1/accounts/acc1/report/similar-accounts/resolve"
  );
  assert.deepEqual(JSON.parse(calls[0].options.body), { profileUrl: payload.profileUrl });
  assert.equal(
    calls[1].url,
    "http://127.0.0.1:8000/api/v1/accounts/acc1/report/similar-accounts"
  );
  assert.equal(calls[1].options.method, "POST");
  assert.deepEqual(JSON.parse(calls[1].options.body), payload);
  assert.equal(
    calls[2].url,
    "http://127.0.0.1:8000/api/v1/accounts/acc1/report/similar-accounts/manual_key%2Fwith%20spaces"
  );
  assert.equal(calls[2].options.method, "DELETE");
});

test("report latest 404 keeps the response status available for quiet legacy fallback", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => ({
    ok: false,
    status: 404,
    json: async () => ({ detail: "account report workflow was not found" }),
  });

  try {
    await assert.rejects(
      starxApi.getLatestReportWorkflow("legacy-account"),
      (error) => error.status === 404
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("topic prompt job api calls text-only prompt endpoint", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options });
    return {
      ok: true,
      status: 200,
      json: async () => ({ id: "wf_prompt" }),
    };
  };

  try {
    await starxApi.createTopicPromptJob("acc1", {
      topicTitle: "通勤妆",
      copyText: "轻薄持妆",
      targetPlatform: "小红书",
    });
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(calls[0].url, "http://127.0.0.1:8000/api/v1/accounts/acc1/generation/topic-prompt-jobs");
  assert.equal(calls[0].options.method, "POST");
  assert.deepEqual(JSON.parse(calls[0].options.body), {
    topicTitle: "通勤妆",
    copyText: "轻薄持妆",
    targetPlatform: "小红书",
  });
});

test("topic prompt job api preserves structured image preferences", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options });
    return { ok: true, status: 200, json: async () => ({ id: "wf_image_plan" }) };
  };

  const payload = {
    topicId: "topic-image-1",
    targetPlatform: "小红书",
    imageCount: 4,
    collectionMode: "series",
    ratio: "3:4",
    creativityLevel: "high",
    visualStyle: "commercial_poster",
    customRequirements: "统一人物和色调",
  };
  try {
    await starxApi.createTopicPromptJob("acc1", payload);
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.deepEqual(JSON.parse(calls[0].options.body), payload);
});

test("video script job api posts confirmed preferences to the video endpoint", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options });
    return {
      ok: true,
      status: 200,
      json: async () => ({ id: "wf_video_script" }),
    };
  };

  const payload = {
    topicId: "topic-video-1",
    targetPlatform: "抖音",
    durationSeconds: 90,
    contentGoal: "acquisition",
    videoFormat: "knowledge_explainer",
    toneStyle: "conversational",
    customRequirements: "开头直接点出通勤时间紧张",
  };

  try {
    await starxApi.createVideoScriptJob("acc1", payload);
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(
    calls[0].url,
    "http://127.0.0.1:8000/api/v1/accounts/acc1/generation/video-script-jobs"
  );
  assert.equal(calls[0].options.method, "POST");
  assert.deepEqual(JSON.parse(calls[0].options.body), payload);
});

test("updateAccount calls account patch endpoint", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options });
    return {
      ok: true,
      status: 200,
      json: async () => ({ id: "acc1", name: "编辑后账号" }),
    };
  };

  try {
    await starxApi.updateAccount("acc1", {
      name: "编辑后账号",
      platforms: ["抖音"],
      accountLinks: { 抖音: "https://www.douyin.com/user/demo" },
    });
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(calls[0].url, "http://127.0.0.1:8000/api/v1/accounts/acc1");
  assert.equal(calls[0].options.method, "PATCH");
  assert.deepEqual(JSON.parse(calls[0].options.body), {
    name: "编辑后账号",
    platforms: ["抖音"],
    accountLinks: { 抖音: "https://www.douyin.com/user/demo" },
  });
});

test("publishCreation calls creation publish endpoint", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options });
    return {
      ok: true,
      status: 200,
      json: async () => ({ externalId: "starx_creation_douyin", status: "queued" }),
    };
  };

  try {
    await starxApi.publishCreation("acc1", "creation1", {
      assetList: ["https://cdn.example.test/video.mp4"],
      filename: "video.mp4",
    });
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(calls[0].url, "http://127.0.0.1:8000/api/v1/accounts/acc1/creations/creation1/publish");
  assert.equal(calls[0].options.method, "POST");
  assert.deepEqual(JSON.parse(calls[0].options.body), {
    assetList: ["https://cdn.example.test/video.mp4"],
    filename: "video.mp4",
  });
});

test("uploadPublishVideo sends the local MP4 directly to OSS", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = directUploadFetch(calls);

  try {
    const file = new File(["video"], "local.mp4", { type: "video/mp4" });
    await starxApi.uploadPublishVideo("acc1", "creation1", "task1", file);
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(calls[0].url, "http://127.0.0.1:8000/api/v1/uploads/presign");
  assert.equal(calls[0].options.method, "POST");
  assert.deepEqual(JSON.parse(calls[0].options.body), {
    accountId: "acc1", purpose: "publish_video", filename: "local.mp4",
    contentType: "video/mp4", sizeBytes: 5,
  });
  assert.equal(calls[1].url, "https://upload.example.test/upl_1");
  assert.equal(calls[1].options.body.name, "local.mp4");
});

test("uploadPublishImages sends multiple local images directly to OSS", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = directUploadFetch(calls);

  try {
    const files = [
      new File(["cover"], "cover.jpg", { type: "image/jpeg" }),
      new File(["detail"], "detail.webp", { type: "image/webp" }),
    ];
    await starxApi.uploadPublishImages("acc1", "creation1", "task1", files);
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(calls.filter((call) => call.url.endsWith("/uploads/presign")).length, 2);
  assert.equal(calls.filter((call) => call.url.startsWith("https://upload.example.test/")).length, 2);
  assert.deepEqual(
    calls.filter((call) => call.url.endsWith("/uploads/presign"))
      .map((call) => JSON.parse(call.options.body).purpose),
    ["publish_image", "publish_image"],
  );
});

test("reversePrompt uploads a local reference image directly to OSS", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = directUploadFetch(calls, { positive: "柔和自然光" });

  try {
    const image = new File(["image-bytes"], "reference.png", { type: "image/png" });
    await starxApi.reversePrompt("acc1", image);
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(calls[0].url, "http://127.0.0.1:8000/api/v1/uploads/presign");
  assert.equal(calls[1].url, "https://upload.example.test/upl_1");
  assert.equal(calls[2].url, "http://127.0.0.1:8000/api/v1/accounts/acc1/generation/reverse-prompt");
  assert.equal(JSON.parse(calls[2].options.body).uploadId, "upl_1");
});

test("reversePrompt keeps remote references as JSON URLs", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options });
    return { ok: true, status: 200, json: async () => ({ positive: "远程参考图" }) };
  };

  try {
    await starxApi.reversePrompt("acc1", "https://cdn.example.test/reference.png");
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.deepEqual(JSON.parse(calls[0].options.body), {
    imageUrl: "https://cdn.example.test/reference.png",
  });
  assert.equal(calls[0].options.headers["Content-Type"], "application/json");
});

test("reversePrompt forwards image post context for AI publish copy", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options });
    return { ok: true, status: 200, json: async () => ({ positive: "图片提示词", publishCopy: "发布文案" }) };
  };

  try {
    await starxApi.reversePrompt("acc1", {
      imageUrl: "https://cdn.example.test/reference.png",
      title: "随机一日三餐",
      description: "看看今天会吃到什么",
      targetPlatform: "小红书",
    });
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.deepEqual(JSON.parse(calls[0].options.body), {
    imageUrl: "https://cdn.example.test/reference.png",
    title: "随机一日三餐",
    description: "看看今天会吃到什么",
    targetPlatform: "小红书",
  });
});

test("getPublishStatus calls creation publish status endpoint", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options });
    return {
      ok: true,
      status: 200,
      json: async () => ({ externalId: "starx_creation_douyin", status: "succeeded" }),
    };
  };

  try {
    await starxApi.getPublishStatus("acc1", "creation1");
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(calls[0].url, "http://127.0.0.1:8000/api/v1/accounts/acc1/creations/creation1/publish/status");
});

test("video analysis api methods call extract video analysis endpoints", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options });
    return {
      ok: true,
      status: 200,
      json: async () => ({}),
    };
  };

  try {
    await starxApi.createVideoAnalysisJob({ videoUrl: "https://example.test/video.mp4" });
    await starxApi.getVideoAnalysisJobs({ accountId: "acc1", creationId: "creation1" });
    await starxApi.getVideoAnalysisJob("vaj_1");
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(calls[0].url, "http://127.0.0.1:8000/api/v1/extract/video-analysis-jobs");
  assert.equal(calls[0].options.method, "POST");
  assert.equal(
    calls[1].url,
    "http://127.0.0.1:8000/api/v1/extract/video-analysis-jobs?accountId=acc1&creationId=creation1"
  );
  assert.equal(calls[2].url, "http://127.0.0.1:8000/api/v1/extract/video-analysis-jobs/vaj_1");
});

test("knowledge base list api sends pagination and keyword query params", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options });
    return {
      ok: true,
      status: 200,
      json: async () => ({ items: [], total: 0, page: 2, pageSize: 12 }),
    };
  };

  try {
    await starxApi.getKnowledgeBases({ page: 2, pageSize: 12, keyword: "门店 服务" });
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(
    calls[0].url,
    "http://127.0.0.1:8000/api/v1/knowledge-bases?page=2&pageSize=12&keyword=%E9%97%A8%E5%BA%97+%E6%9C%8D%E5%8A%A1"
  );
});

test("knowledge base image upload sends local files directly to OSS", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = directUploadFetch(calls);

  try {
    const file = new File(["image"], "material.png", { type: "image/png" });
    await starxApi.uploadKnowledgeBaseImages([file]);
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(
    JSON.parse(calls[0].options.body).purpose,
    "knowledge_base_image"
  );
  assert.equal(calls[1].url, "https://upload.example.test/upl_1");
});

test("createImageJob sends slot and refinement fields", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options });
    return {
      ok: true,
      status: 200,
      json: async () => ({ id: "gj_1" }),
    };
  };

  try {
    await starxApi.createImageJob("acc1", {
      prompt: "prompt",
      count: 1,
      ratio: "3:4",
      variantsPerSlot: 2,
      sourcePromptWorkflowId: "wf_prompt_selected_platform",
      regenerateSlotId: "slot_1",
      refinement: "更清爽",
      slots: [{ slotId: "slot_1", sourceType: "manual" }],
    });
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(calls[0].url, "http://127.0.0.1:8000/api/v1/accounts/acc1/generation/image-jobs");
  assert.equal(JSON.parse(calls[0].options.body).variantsPerSlot, 2);
  assert.equal(JSON.parse(calls[0].options.body).regenerateSlotId, "slot_1");
  assert.equal(JSON.parse(calls[0].options.body).sourcePromptWorkflowId, "wf_prompt_selected_platform");
});

test("createImageJob sends reference urls in json payload", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options });
    return {
      ok: true,
      status: 200,
      json: async () => ({ id: "gj_ref_url" }),
    };
  };

  try {
    await starxApi.createImageJob("acc1", {
      prompt: "prompt",
      count: 1,
      ratio: "3:4",
      referenceUrls: ["https://oss.example.test/extract/source.webp"],
    });
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.deepEqual(JSON.parse(calls[0].options.body).referenceUrls, [
    "https://oss.example.test/extract/source.webp",
  ]);
});

test("createImageJob uploads reference and material images to OSS before JSON submission", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = directUploadFetch(calls, { id: "gj_2" });

  try {
    await starxApi.createImageJob("acc1", {
      prompt: "prompt",
      count: 1,
      ratio: "3:4",
      selectedTagIds: ["style_1"],
      slots: [{ slotId: "upload_1", sourceType: "upload", sourceUrl: "blob:ref" }],
      referenceUrls: ["https://oss.example.test/extract/source.webp"],
      referenceImages: [new Blob(["ref"], { type: "image/png" })],
      materialImages: [new Blob(["mat"], { type: "image/webp" })],
    });
  } finally {
    globalThis.fetch = originalFetch;
  }

  const businessCall = calls.find((call) => call.url.endsWith("/generation/image-jobs"));
  const body = JSON.parse(businessCall.options.body);
  assert.equal(body.prompt, "prompt");
  assert.equal(body.ratio, "3:4");
  assert.deepEqual(body.referenceUrls, [
    "https://oss.example.test/upl_1/upload.png",
    "https://oss.example.test/extract/source.webp",
  ]);
  assert.deepEqual(body.materialUrls, ["https://oss.example.test/upl_2/upload.webp"]);
  assert.deepEqual(body.slots, [
    { slotId: "upload_1", sourceType: "upload", sourceUrl: "blob:ref" },
  ]);
});

test("createPersonReplacementJob uploads both image roles before JSON submission", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = directUploadFetch(calls, { id: "wf_person_replacement" });
  const targetImage = new Blob(["target"], { type: "image/jpeg" });
  const personImage = new Blob(["person"], { type: "image/png" });

  try {
    await starxApi.createPersonReplacementJob("acc1", {
      targetImage,
      personImage,
      consentConfirmed: true,
      ratio: "4:3",
      count: 2,
    });
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(
    calls.at(-1).url,
    "http://127.0.0.1:8000/api/v1/accounts/acc1/generation/person-replacement-jobs"
  );
  const body = JSON.parse(calls.at(-1).options.body);
  assert.equal(body.targetImage.uploadId, "upl_1");
  assert.equal(body.personImage.uploadId, "upl_2");
  assert.equal(body.consentConfirmed, true);
  assert.equal(body.ratio, "4:3");
  assert.equal(body.count, 2);
});

test("createPersonReplacementJobs uploads one person image for multiple scene jobs", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = directUploadFetch(calls, { id: "wf_person_replacement_batch" });
  const targetImages = [
    new Blob(["target-1"], { type: "image/jpeg" }),
    new Blob(["target-2"], { type: "image/webp" }),
    new Blob(["target-3"], { type: "image/png" }),
  ];
  const personImage = new Blob(["person"], { type: "image/png" });

  let results;
  try {
    results = await starxApi.createPersonReplacementJobs("acc1", {
      targetImages,
      personImage,
      consentConfirmed: true,
      ratios: ["4:3", "1:1", "9:16"],
      count: 3,
      concurrency: 2,
    });
  } finally {
    globalThis.fetch = originalFetch;
  }

  const presignBodies = calls
    .filter((call) => call.url.endsWith("/uploads/presign"))
    .map((call) => JSON.parse(call.options.body));
  const jobBodies = calls
    .filter((call) => call.url.endsWith("/generation/person-replacement-jobs"))
    .map((call) => JSON.parse(call.options.body));
  assert.equal(presignBodies.filter((body) => body.purpose === "person_replacement_person").length, 1);
  assert.equal(presignBodies.filter((body) => body.purpose === "person_replacement_target").length, 3);
  assert.equal(jobBodies.length, 3);
  assert.equal(new Set(jobBodies.map((body) => body.personImage.uploadId)).size, 1);
  assert.deepEqual(jobBodies.map((body) => body.ratio), ["4:3", "1:1", "9:16"]);
  assert.deepEqual(jobBodies.map((body) => body.count), [3, 3, 3]);
  assert.equal(results.filter((result) => result.job).length, 3);
});

test("downloadPersonReplacementResult requests an authenticated binary result endpoint", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  const expectedBlob = new Blob(["generated"], { type: "image/png" });
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options });
    return {
      ok: true,
      status: 200,
      blob: async () => expectedBlob,
    };
  };

  try {
    const blob = await starxApi.downloadPersonReplacementResult("acc1", "wf1");
    assert.equal(blob, expectedBlob);
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(
    calls[0].url,
    "http://127.0.0.1:8000/api/v1/accounts/acc1/generation/jobs/wf1/result-image"
  );
  assert.equal(calls[0].options.method, undefined);
});

test("downloadPersonReplacementResult requests a specific generated variant", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options });
    return { ok: true, status: 200, blob: async () => new Blob(["variant"]) };
  };

  try {
    await starxApi.downloadPersonReplacementResult("acc1", "wf1", 2);
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(
    calls[0].url,
    "http://127.0.0.1:8000/api/v1/accounts/acc1/generation/jobs/wf1/result-image?imageIndex=2"
  );
});

test("competitor account and video APIs support add delete refresh and workflow lookup", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options });
    return {
      ok: true,
      status: options.method === "DELETE" ? 204 : 200,
      json: async () => ({ id: "wf_1", workflows: [] }),
    };
  };

  try {
    await starxApi.getCompetitorAccounts("acc1");
    await starxApi.getCompetitorAccountContentTrends("acc1", "ca_1", 7);
    await starxApi.getCompetitorAccountMetricTrends("acc1", "ca_1", 30);
    await starxApi.addCompetitorAccount("acc1", "https://www.douyin.com/user/a");
    await starxApi.addCompetitorAccount("acc1", {
      platform: "抖音",
      reference: "2012721597",
    });
    await starxApi.addCompetitorAccount("acc1", {
      platform: "小红书",
      reference: "11672196288",
    });
    await starxApi.deleteCompetitorAccount("acc1", "ca_1");
    await starxApi.refreshCompetitorAccount("acc1", "ca_1");
    await starxApi.refreshCompetitorAccounts("acc1");
    await starxApi.getCompetitorVideos("acc1");
    await starxApi.addCompetitorVideo("acc1", "https://www.douyin.com/video/1");
    await starxApi.deleteCompetitorVideo("acc1", "cv_1");
    await starxApi.refreshCompetitorVideo("acc1", "cv_1");
    await starxApi.refreshCompetitorVideos("acc1");
    await starxApi.getCompetitorRefreshWorkflow("acc1", "wf_1");
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.deepEqual(calls.map(({ options }) => options.method), [
    undefined, undefined, undefined, "POST", "POST", "POST", "DELETE", "POST", "POST",
    undefined, "POST", "DELETE", "POST", "POST", undefined,
  ]);
  assert.equal(
    calls[2].url,
    "http://127.0.0.1:8000/api/v1/accounts/acc1/competitors/accounts/ca_1/metric-trends?days=30"
  );
  assert.deepEqual(JSON.parse(calls[3].options.body), {
    profileUrl: "https://www.douyin.com/user/a",
  });
  assert.deepEqual(JSON.parse(calls[4].options.body), {
    platform: "抖音",
    reference: "2012721597",
  });
  assert.deepEqual(JSON.parse(calls[5].options.body), {
    platform: "小红书",
    reference: "11672196288",
  });
  assert.deepEqual(JSON.parse(calls[10].options.body), {
    contentUrl: "https://www.douyin.com/video/1",
  });
  assert.equal(
    calls[14].url,
    "http://127.0.0.1:8000/api/v1/accounts/acc1/competitors/refresh-workflows/wf_1"
  );
});

test("hot board APIs support get and refresh beside competitor routes", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options });
    return {
      ok: true,
      status: 200,
      json: async () => ({ boardType: "topic_total", items: [] }),
    };
  };

  try {
    await starxApi.getHotBoard("acc1", { boardType: "topic_rising", keyword: "美妆", dateWindow: 24, limit: 20 });
    await starxApi.refreshHotBoard("acc1", { boardType: "topic_total", keyword: "美妆", dateWindow: 24 });
    await starxApi.getHotTopicDetail("acc1", "1708968821050379", { sortType: 1, forceRefresh: true });
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.match(calls[0].url, /\/accounts\/acc1\/hot-boards\?/);
  assert.match(calls[0].url, /boardType=topic_rising/);
  assert.match(calls[0].url, /keyword=%E7%BE%8E%E5%A6%86/);
  assert.match(calls[0].url, /dateWindow=24/);
  assert.equal(calls[1].url, "http://127.0.0.1:8000/api/v1/accounts/acc1/hot-boards/refresh");
  assert.equal(calls[1].options.method, "POST");
  assert.deepEqual(JSON.parse(calls[1].options.body), {
    platform: "抖音",
    boardType: "topic_total",
    keyword: "美妆",
    category: "",
    dateWindow: 24,
    limit: 30,
  });
  assert.match(calls[2].url, /\/accounts\/acc1\/hot-boards\/topics\/1708968821050379\?/);
  assert.match(calls[2].url, /sortType=1/);
  assert.match(calls[2].url, /forceRefresh=true/);
});
