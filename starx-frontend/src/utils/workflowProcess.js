export const WORKFLOW_STAGES = Object.freeze([
  { key: "draft", label: "草稿", color: "#7b879f" },
  { key: "script", label: "脚本", color: "#b4a0ff" },
  { key: "shooting", label: "拍摄", color: "#f0a0c8" },
  { key: "editing", label: "剪辑中", color: "#00d8ff" },
  { key: "review", label: "审核", color: "#f0c060" },
  { key: "pending_review", label: "待发布", color: "#ff9f43" },
  { key: "done", label: "已完成", color: "#40d080" },
]);

const STATUS_ALIASES = Object.freeze({
  pending: "pending_review",
  pending_publish: "pending_review",
  completed: "done",
});

const WORKFLOW_STAGE_KEYS = new Set(WORKFLOW_STAGES.map((stage) => stage.key));
const ALL_FILTER_VALUES = new Set([
  "",
  "all",
  "全部",
  "全部负责人",
  "全部阶段",
  "全部平台",
]);

function text(value) {
  return String(value ?? "").trim();
}

function normalizedFilter(value) {
  const normalized = text(value);
  return ALL_FILTER_VALUES.has(normalized) ? "" : normalized;
}

export function normalizeWorkflowStatus(status) {
  const normalized = text(status);
  return STATUS_ALIASES[normalized] || normalized;
}

export function getNextWorkflowStatus(status) {
  const normalized = normalizeWorkflowStatus(status);
  if (!WORKFLOW_STAGE_KEYS.has(normalized)) return null;

  const currentIndex = WORKFLOW_STAGES.findIndex((stage) => stage.key === normalized);
  return WORKFLOW_STAGES[currentIndex + 1]?.key || null;
}

export function getPreviousWorkflowStatus(status) {
  const normalized = normalizeWorkflowStatus(status);
  if (!WORKFLOW_STAGE_KEYS.has(normalized)) return null;

  const currentIndex = WORKFLOW_STAGES.findIndex((stage) => stage.key === normalized);
  return WORKFLOW_STAGES[currentIndex - 1]?.key || null;
}

export function canPublishWorkflowTask(task = {}) {
  return text(task?.status) === "pending_review"
    && text(task?.creationId).length > 0;
}

export function matchesWorkflowTask(task = {}, filters = {}) {
  const keyword = normalizedFilter(filters.keyword).toLocaleLowerCase();
  const assignee = normalizedFilter(filters.assignee);
  const stage = normalizedFilter(filters.stage);
  const platform = normalizedFilter(filters.platform);

  if (keyword) {
    const searchableText = [task.title, task.body, task.description, task.note]
      .map(text)
      .join(" ")
      .toLocaleLowerCase();
    if (!searchableText.includes(keyword)) return false;
  }

  if (assignee && text(task.assignee) !== assignee) return false;
  if (stage && normalizeWorkflowStatus(task.status) !== normalizeWorkflowStatus(stage)) return false;
  if (platform && text(task.targetPlatform) !== platform) return false;

  return true;
}
