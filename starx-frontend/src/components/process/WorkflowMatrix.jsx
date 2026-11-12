import { normalizeWorkflowStatus } from "../../utils/workflowProcess";

const formatDate = (value) => {
  if (!value) return "未设置";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });
};

const getMaterialCount = (task) => {
  if (Number.isFinite(Number(task.materialCount))) return Number(task.materialCount);
  if (Number.isFinite(Number(task.assetsCount))) return Number(task.assetsCount);
  if (Array.isArray(task.materials)) return task.materials.length;
  if (Array.isArray(task.assets)) return task.assets.length;
  return 0;
};

const getDueAt = (task) => task.dueDate || task.publishAt || task.scheduledAt || "";

const getOverdueLabel = (task) => {
  const dueTime = new Date(getDueAt(task)).getTime();
  if (!Number.isFinite(dueTime) || dueTime >= Date.now()) return "";
  const overdueDays = Math.max(1, Math.ceil((Date.now() - dueTime) / 86400000));
  return `逾期 ${overdueDays} 天`;
};

function TaskInfoCell({ task }) {
  const coverUrl = task.coverUrl || task.cover?.url || task.thumbnail || "";
  const dueAt = getDueAt(task);

  return (
    <div className="workflow-task-info">
      <div className={`workflow-cover ${task.type === "video" ? "video" : "image"}`}>
        {coverUrl ? <img src={coverUrl} alt="" /> : task.type === "video" ? "▶" : "▧"}
      </div>
      <div className="workflow-task-copy">
        <strong title={task.title || "未命名任务"}>{task.title || "未命名任务"}</strong>
        <div className="workflow-task-meta">
          <span className={`workflow-type ${task.type === "video" ? "video" : "image"}`}>
            {task.type === "video" ? "视频" : "图文"}
          </span>
          {task.targetPlatform ? <span className="workflow-platform">{task.targetPlatform}</span> : null}
          <span>优先级·{task.priority === "high" ? "高" : task.priority === "low" ? "低" : "普通"}</span>
        </div>
        <div className="workflow-task-submeta">
          <span>{dueAt ? `截止 ${formatDate(dueAt)}` : "未设置截止时间"}</span>
          <span>素材 {getMaterialCount(task)}</span>
          {task.assignee ? <span title={task.assignee}>负责人·{task.assignee}</span> : null}
        </div>
      </div>
    </div>
  );
}

function StageStatusCell({ task, stage, stages, onSelectTask }) {
  const currentStatus = normalizeWorkflowStatus(task.status);
  const currentIndex = stages.findIndex((item) => item.key === currentStatus);
  const stageIndex = stages.findIndex((item) => item.key === stage.key);
  const current = stageIndex === currentIndex;
  const complete = currentIndex >= 0 && stageIndex < currentIndex;
  const pending = currentIndex < 0 || stageIndex > currentIndex;
  const overdueLabel = current && currentStatus !== "done" ? getOverdueLabel(task) : "";

  return (
    <button
      type="button"
      role="cell"
      className={`workflow-stage-cell ${current ? "current" : ""} ${complete ? "complete" : ""} ${pending ? "pending" : ""} ${overdueLabel ? "overdue" : ""}`}
      style={{ "--stage-color": stage.color }}
      aria-label={`${task.title || "未命名任务"} · ${stage.label}`}
      onClick={(event) => {
        event.stopPropagation();
        onSelectTask?.(task);
      }}
    >
      {complete ? (
        <span className="workflow-check">✓</span>
      ) : current ? (
        <span className="workflow-status-block">
          <b>{overdueLabel ? "阻塞" : stage.label}</b>
          <small>{overdueLabel || (getDueAt(task) ? `${formatDate(getDueAt(task))} 截止` : currentStatus === "done" ? "流程完成" : "进行中")}</small>
        </span>
      ) : (
        <span className="workflow-pending-mark">—</span>
      )}
    </button>
  );
}

function selectRowFromKeyboard(event, task, onSelectTask) {
  if (event.key !== "Enter" && event.key !== " ") return;
  event.preventDefault();
  onSelectTask?.(task);
}

export default function WorkflowMatrix({ tasks, stages, selectedTaskId, onSelectTask, currentPage, totalPages, onPageChange }) {
  const safeTasks = Array.isArray(tasks) ? tasks : [];
  const safeStages = Array.isArray(stages) ? stages : [];
  const safeTotalPages = Math.max(1, Number(totalPages) || 1);
  const safeCurrentPage = Math.min(safeTotalPages, Math.max(1, Number(currentPage) || 1));

  return (
    <section className="workflow-matrix-shell" aria-label="任务流程矩阵与分页">
      <div className="workflow-matrix-scroll">
        <div className="workflow-matrix" role="table" aria-label="任务流程矩阵">
          <div className="workflow-matrix-header" role="row">
            <div className="workflow-task-header" role="columnheader">任务信息</div>
            {safeStages.map((stage) => (
              <div
                className="workflow-stage-header"
                role="columnheader"
                style={{ "--stage-color": stage.color }}
                key={stage.key}
              >
                {stage.label}
              </div>
            ))}
          </div>
          <div className="workflow-matrix-body" role="rowgroup">
            {safeTasks.map((task) => (
              <div
                className={`workflow-matrix-row ${selectedTaskId === task.id ? "selected" : ""}`}
                role="row"
                tabIndex={0}
                aria-label={`查看任务：${task.title || "未命名任务"}`}
                onClick={() => onSelectTask?.(task)}
                onKeyDown={(event) => selectRowFromKeyboard(event, task, onSelectTask)}
                key={task.id}
              >
                <div className="workflow-task-fixed" role="cell"><TaskInfoCell task={task} /></div>
                {safeStages.map((stage) => (
                  <StageStatusCell
                    task={task}
                    stage={stage}
                    stages={safeStages}
                    onSelectTask={onSelectTask}
                    key={stage.key}
                  />
                ))}
              </div>
            ))}
            {!safeTasks.length ? <div className="workflow-empty">暂无符合条件的任务</div> : null}
          </div>
        </div>
      </div>
      <footer className="workflow-pagination" aria-label="任务分页">
        <button
          type="button"
          className="btn btn-xs"
          disabled={safeCurrentPage <= 1}
          onClick={() => onPageChange?.(safeCurrentPage - 1)}
        >
          上一页
        </button>
        <span>第 {safeCurrentPage} / {safeTotalPages} 页</span>
        <button
          type="button"
          className="btn btn-xs"
          disabled={safeCurrentPage >= safeTotalPages}
          onClick={() => onPageChange?.(safeCurrentPage + 1)}
        >
          下一页
        </button>
      </footer>
    </section>
  );
}
