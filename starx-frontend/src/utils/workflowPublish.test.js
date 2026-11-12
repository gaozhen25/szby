import assert from "node:assert/strict";
import test from "node:test";

import {
  buildWorkflowPublishDraft,
  buildWorkflowPublishPayload,
  createWorkflowPublishRequestGate,
  isPublishDeviceConfigurationError,
  isWorkflowPublishActive,
} from "./workflowPublish.js";

test("buildWorkflowPublishDraft restores persisted workflow media", () => {
  assert.deepEqual(buildWorkflowPublishDraft({
    creationId: "creation-1",
    type: "video",
    targetPlatform: "抖音",
    content: { title: "创作标题", body: "正文" },
    creationState: {
      publishCopy: "发布文案",
      publishMediaCandidates: [
        { url: "https://cdn.test/a.mp4", kind: "video", label: "创作视频" },
      ],
    },
  }, { id: "task-1" }), {
    creationId: "creation-1",
    taskId: "task-1",
    type: "video",
    targetPlatform: "抖音",
    title: "创作标题",
    description: "发布文案",
    mediaCandidates: [
      { url: "https://cdn.test/a.mp4", kind: "video", label: "创作视频" },
    ],
    selectedMediaUrls: ["https://cdn.test/a.mp4"],
    visibility: "0",
    copyToAlbum: true,
    retry: false,
  });
});

test("buildWorkflowPublishDraft falls back to saved assets and task copy", () => {
  assert.deepEqual(buildWorkflowPublishDraft({
    creationId: "creation-2",
    type: "image",
    targetPlatform: "小红书",
    content: {
      body: "",
      assets: [
        { url: "https://cdn.test/cover.png", kind: "image", label: "封面" },
        "https://cdn.test/detail.png",
      ],
    },
    creationState: {},
  }, { id: "task-2", title: "任务标题", body: "任务正文" }), {
    creationId: "creation-2",
    taskId: "task-2",
    type: "image",
    targetPlatform: "小红书",
    title: "任务标题",
    description: "任务正文",
    mediaCandidates: [
      { url: "https://cdn.test/cover.png", kind: "image", label: "封面" },
      { url: "https://cdn.test/detail.png", kind: "image", label: "图片 2" },
    ],
    selectedMediaUrls: [
      "https://cdn.test/cover.png",
      "https://cdn.test/detail.png",
    ],
    visibility: "0",
    copyToAlbum: true,
    retry: false,
  });
});

test("buildWorkflowPublishDraft appends normalized hashtags to the publish description", () => {
  const draft = buildWorkflowPublishDraft({
    creationId: "creation-with-hashtags",
    creationState: { publishCopy: "今天分享一个实用技巧 #已有标签" },
    content: {
      hashtags: ["新标签", "#已有标签", "##另一个标签", "新标签", ""],
    },
  });

  assert.equal(
    draft.description,
    "今天分享一个实用技巧 #已有标签\n\n#新标签 #另一个标签",
  );
});

test("buildWorkflowPublishDraft uses hashtags as the description when copy is empty", () => {
  const draft = buildWorkflowPublishDraft({
    creationId: "creation-only-hashtags",
    content: { hashtags: ["#标签一", "标签二"] },
  });

  assert.equal(draft.description, "#标签一 #标签二");
});

test("buildWorkflowPublishDraft selects only media matching the creation type", () => {
  const draft = buildWorkflowPublishDraft({
    creationId: "creation-mixed",
    type: "image",
    creationState: {
      publishMediaCandidates: [
        { url: "https://cdn.test/cover.png", kind: "image" },
        { url: "https://cdn.test/trailer.mp4", kind: "video" },
      ],
    },
  });

  assert.deepEqual(draft.mediaCandidates, [
    { url: "https://cdn.test/cover.png", kind: "image", label: "图片 1" },
  ]);
  assert.deepEqual(draft.selectedMediaUrls, ["https://cdn.test/cover.png"]);
});

test("buildWorkflowPublishDraft hides uploaded video candidates owned by another workflow task", () => {
  const draft = buildWorkflowPublishDraft({
    creationId: "creation-scoped",
    type: "video",
    creationState: {
      publishMediaCandidates: [
        { url: "https://cdn.test/current.mp4", kind: "video", workflowTaskId: "task-current" },
        { url: "https://cdn.test/other.mp4", kind: "video", workflowTaskId: "task-other" },
      ],
    },
  }, { id: "task-current" });

  assert.deepEqual(draft.mediaCandidates, [{
    url: "https://cdn.test/current.mp4",
    kind: "video",
    label: "视频 1",
    workflowTaskId: "task-current",
  }]);
  assert.deepEqual(draft.selectedMediaUrls, ["https://cdn.test/current.mp4"]);
});

test("buildWorkflowPublishPayload sends all selected image media in display order", () => {
  assert.deepEqual(buildWorkflowPublishPayload({
    type: "image",
    selectedMediaUrls: [
      "https://cdn.test/path/a.png?version=2",
      "https://cdn.test/path/b.png",
    ],
    title: "  夏日护肤实测  ",
    description: "文案",
    visibility: "1",
    copyToAlbum: false,
  }), {
    targetPlatform: "",
    assetList: [
      "https://cdn.test/path/a.png?version=2",
      "https://cdn.test/path/b.png",
    ],
    filename: "a.png",
    title: "夏日护肤实测",
    description: "文案",
    visibility: "1",
    copyToAlbum: false,
    retry: false,
  });
});

test("buildWorkflowPublishPayload sends exactly one selected video", () => {
  assert.deepEqual(buildWorkflowPublishPayload({
    type: "video",
    selectedMediaUrls: ["https://cdn.test/uploaded.mp4"],
    description: "视频文案",
  }).assetList, ["https://cdn.test/uploaded.mp4"]);

  assert.throws(
    () => buildWorkflowPublishPayload({
      type: "video",
      selectedMediaUrls: [
        "https://cdn.test/a.mp4",
        "https://cdn.test/b.mp4",
      ],
      description: "视频文案",
    }),
    /视频发布只能选择一个素材/,
  );
});

test("buildWorkflowPublishPayload sends the selected publish platform", () => {
  const payload = buildWorkflowPublishPayload({
    targetPlatform: " 抖音 ",
    selectedMediaUrl: "https://cdn.test/a.mp4",
    description: "视频文案",
  });

  assert.equal(payload.targetPlatform, "抖音");
});

test("buildWorkflowPublishPayload preserves the exact supported visibility mapping", () => {
  const labelsByVisibility = new Map([
    ["0", "默认公开"],
    ["1", "好友可见"],
    ["2", "仅自己可见"],
  ]);

  for (const [visibility, label] of labelsByVisibility) {
    const payload = buildWorkflowPublishPayload({
      selectedMediaUrl: "https://cdn.test/a.png",
      description: "发布文案",
      visibility,
    });
    assert.equal(payload.visibility, visibility, label);
  }
});

test("buildWorkflowPublishPayload rejects unsupported visibility values", () => {
  for (const visibility of ["", "3", "public", -1]) {
    assert.throws(
      () => buildWorkflowPublishPayload({
        selectedMediaUrl: "https://cdn.test/a.png",
        visibility,
      }),
      /发布可见性仅支持 0（默认公开）、1（好友可见）或 2（仅自己可见）/,
    );
  }
});

test("buildWorkflowPublishPayload rejects an empty publish description", () => {
  for (const description of ["", "   ", null, undefined]) {
    assert.throws(
      () => buildWorkflowPublishPayload({
        selectedMediaUrl: "https://cdn.test/a.png",
        description,
      }),
      /请填写发布文案后再发布/,
    );
  }
});

test("buildWorkflowPublishPayload sends an explicit retry boolean", () => {
  const baseDraft = {
    selectedMediaUrl: "https://cdn.test/a.png",
    description: "发布文案",
  };

  assert.equal(buildWorkflowPublishPayload(baseDraft).retry, false);
  assert.equal(buildWorkflowPublishPayload({ ...baseDraft, retry: true }).retry, true);
  assert.equal(buildWorkflowPublishPayload({ ...baseDraft, retry: false }).retry, false);
});

test("buildWorkflowPublishPayload rejects missing or non-HTTPS media", () => {
  assert.throws(
    () => buildWorkflowPublishPayload({ selectedMediaUrl: "http://cdn.test/a.png" }),
    /请选择可发布的 HTTPS 素材/,
  );
  assert.throws(
    () => buildWorkflowPublishPayload({ selectedMediaUrl: "" }),
    /请选择可发布的 HTTPS 素材/,
  );
});

test("device configuration errors are recognized from current or persisted messages", () => {
  for (const message of [
    "device is offline",
    "Android ID 无效",
    "publishSettings missing",
    "发布设备未连接",
    "请检查发布设备配置",
    "对应设备不存在",
  ]) {
    assert.equal(isPublishDeviceConfigurationError(message), true, message);
  }

  assert.equal(
    isPublishDeviceConfigurationError("普通发布失败", "设备配置不存在"),
    true,
  );
  assert.equal(isPublishDeviceConfigurationError("网络超时，请重试"), false);
  assert.equal(isPublishDeviceConfigurationError("发布素材不存在"), false);
  assert.equal(isPublishDeviceConfigurationError("内容配置错误"), false);
});

test("isWorkflowPublishActive only tracks unfinished publish jobs", () => {
  for (const status of ["pending", "queued", "running"]) {
    assert.equal(isWorkflowPublishActive(status), true);
  }
  for (const status of ["succeeded", "failed", "cancelled", "", null]) {
    assert.equal(isWorkflowPublishActive(status), false);
  }
});

test("workflow request gate accepts only the latest request for a channel", () => {
  const gate = createWorkflowPublishRequestGate();
  const first = gate.begin("publish:creation-1", "account-a");
  const second = gate.begin("publish:creation-1", "account-a");

  assert.equal(gate.isCurrent(first, "account-a"), false);
  assert.equal(gate.isCurrent(second, "account-a"), true);
});

test("workflow request gate rejects A to B to A lifecycle responses", () => {
  const gate = createWorkflowPublishRequestGate();
  const staleAccountA = gate.begin("publish:creation-1", "account-a");

  gate.reset();
  gate.begin("publish:creation-1", "account-b");
  gate.reset();
  const currentAccountA = gate.begin("publish:creation-1", "account-a");

  assert.equal(gate.isCurrent(staleAccountA, "account-a"), false);
  assert.equal(gate.isCurrent(currentAccountA, "account-a"), true);
});

test("workflow request gate makes the last task-open request win", () => {
  const gate = createWorkflowPublishRequestGate();
  const taskA = gate.begin("load-task-creation", "account-a");
  const taskB = gate.begin("load-task-creation", "account-a");

  assert.equal(gate.isCurrent(taskA, "account-a"), false);
  assert.equal(gate.isCurrent(taskB, "account-a"), true);
});
