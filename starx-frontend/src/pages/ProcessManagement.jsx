import { useEffect, useMemo, useRef, useState } from "react";

import WorkflowDetailDrawer from "../components/process/WorkflowDetailDrawer";
import WorkflowMatrix from "../components/process/WorkflowMatrix";
import WorkflowPublishModal from "../components/process/WorkflowPublishModal";
import {
  WORKFLOW_STAGES,
  canPublishWorkflowTask,
  getNextWorkflowStatus,
  getPreviousWorkflowStatus,
  matchesWorkflowTask,
  normalizeWorkflowStatus,
} from "../utils/workflowProcess";
import {
  buildWorkflowPublishDraft,
  buildWorkflowPublishPayload,
  isWorkflowPublishActive,
} from "../utils/workflowPublish";

const ROWS_PER_PAGE = 8;
const SUPPORTED_PUBLISH_PLATFORMS = new Set(["小红书", "抖音", "快手"]);

function isTaskOverdue(task) {
  if (normalizeWorkflowStatus(task.status) === "done" || !task.dueDate) return false;
  const dueTime = new Date(task.dueDate).getTime();
  return Number.isFinite(dueTime) && dueTime < Date.now();
}

export default function ProcessManagement({ app }) {
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [searchKeyword, setSearchKeyword] = useState("");
  const [assigneeFilter, setAssigneeFilter] = useState("all");
  const [stageFilter, setStageFilter] = useState("all");
  const [platformFilter, setPlatformFilter] = useState("all");
  const [taskPage, setTaskPage] = useState(1);
  const [publishDraft, setPublishDraft] = useState(null);
  const [publishingTaskId, setPublishingTaskId] = useState("");
  const [publishBusy, setPublishBusy] = useState("");
  const [publishError, setPublishError] = useState("");
  const [, setMovingTaskIds] = useState(() => new Set());
  const [duplicatingTaskId, setDuplicatingTaskId] = useState("");
  const tasksRef = useRef(app.tasks);
  const selectedTaskIdRef = useRef("");
  const movingTaskIdsRef = useRef(new Set());
  const publishOpenRunRef = useRef(0);
  const publishInFlightRef = useRef(false);

  useEffect(() => {
    tasksRef.current = app.tasks;
  }, [app.tasks]);

  const selectedTask = useMemo(
    () => app.tasks.find((task) => task.id === selectedTaskId) || null,
    [app.tasks, selectedTaskId]
  );
  const assignees = useMemo(
    () => [...new Set(app.tasks.map((task) => task.assignee).filter(Boolean))],
    [app.tasks]
  );
  const platforms = useMemo(
    () => [...new Set(app.tasks.map((task) => task.targetPlatform).filter(Boolean))],
    [app.tasks]
  );
  const filteredTasks = useMemo(
    () => app.tasks.filter((task) => matchesWorkflowTask(task, {
      keyword: searchKeyword,
      assignee: assigneeFilter,
      stage: stageFilter,
      platform: platformFilter,
    })),
    [app.tasks, assigneeFilter, platformFilter, searchKeyword, stageFilter]
  );
  const totalPages = Math.max(1, Math.ceil(filteredTasks.length / ROWS_PER_PAGE));
  const currentPage = Math.min(Math.max(1, taskPage), totalPages);
  const startIndex = (currentPage - 1) * ROWS_PER_PAGE;
  const pagedTasks = filteredTasks.slice(startIndex, startIndex + ROWS_PER_PAGE);
  const stats = useMemo(() => ({
    active: app.tasks.filter((task) => normalizeWorkflowStatus(task.status) !== "done").length,
    pendingPublish: app.tasks.filter((task) => normalizeWorkflowStatus(task.status) === "pending_review").length,
    overdue: app.tasks.filter(isTaskOverdue).length,
    completed: app.tasks.filter((task) => normalizeWorkflowStatus(task.status) === "done").length,
  }), [app.tasks]);

  const publishState = publishDraft?.creationId
    ? app.publishStates?.[publishDraft.creationId] || null
    : null;
  const platformSupported = Boolean(
    publishDraft?.targetPlatform && SUPPORTED_PUBLISH_PLATFORMS.has(publishDraft.targetPlatform)
  );
  const deviceConfigured = Boolean(
    publishDraft?.targetPlatform
    && app.currentAccount?.publishSettings?.[publishDraft.targetPlatform]?.androidId
  );

  useEffect(() => {
    if (!publishDraft?.creationId || !isWorkflowPublishActive(publishState?.status)) return undefined;
    if (!app.refreshPublishStatus) return undefined;
    const creationId = publishDraft.creationId;
    const timer = window.setInterval(() => {
      app.refreshPublishStatus(creationId, { silent: true }).catch(() => {});
    }, 5000);
    return () => window.clearInterval(timer);
  }, [app.refreshPublishStatus, publishDraft?.creationId, publishState?.status]);

  const invalidatePendingPublishOpen = () => {
    publishOpenRunRef.current += 1;
    setPublishBusy((current) => current === "loading" ? "" : current);
  };

  const selectTask = (task) => {
    invalidatePendingPublishOpen();
    const nextTaskId = task?.id || "";
    selectedTaskIdRef.current = nextTaskId;
    setSelectedTaskId(nextTaskId);
  };

  const closeTaskDetails = () => selectTask(null);

  const isTaskTransitioning = (taskId) => Boolean(
    taskId && movingTaskIdsRef.current.has(taskId)
  );

  const markTaskTransitioning = (taskId, transitioning) => {
    const next = new Set(movingTaskIdsRef.current);
    if (transitioning) next.add(taskId);
    else next.delete(taskId);
    movingTaskIdsRef.current = next;
    setMovingTaskIds(next);
  };

  const moveTask = async (task, status) => {
    if (
      !task?.id
      || isTaskTransitioning(task.id)
      || normalizeWorkflowStatus(task.status) === status
      || !WORKFLOW_STAGES.some((stage) => stage.key === status)
    ) return;
    markTaskTransitioning(task.id, true);
    try {
      await app.moveTask(task.id, status);
    } catch (error) {
      app.addToast(error.message || "任务阶段更新失败", "warning");
    } finally {
      markTaskTransitioning(task.id, false);
    }
  };

  const advanceTask = async (task) => {
    const nextStatus = getNextWorkflowStatus(task?.status);
    if (nextStatus) await moveTask(task, nextStatus);
  };

  const retreatTask = async (task) => {
    const previousStatus = getPreviousWorkflowStatus(task?.status);
    if (previousStatus) await moveTask(task, previousStatus);
  };

  const deleteTask = async (task) => {
    if (!task?.id || isTaskTransitioning(task.id)) return;
    await app.deleteTask(task.id);
    if (selectedTaskId === task.id) closeTaskDetails();
  };

  const duplicateTask = async (task) => {
    if (!task?.id || duplicatingTaskId || isTaskTransitioning(task.id)) return;
    setDuplicatingTaskId(task.id);
    try {
      const duplicate = await app.duplicateTask(task.id);
      if (duplicate) selectTask(duplicate);
    } catch (error) {
      app.addToast(error.message || "流程复制失败", "warning");
    } finally {
      setDuplicatingTaskId("");
    }
  };

  const openPublish = async (task) => {
    if (
      selectedTaskIdRef.current !== task?.id
      || !canPublishWorkflowTask(task)
      || isTaskTransitioning(task?.id)
    ) return;
    const runId = ++publishOpenRunRef.current;
    setPublishBusy("loading");
    setPublishError("");
    try {
      const creation = await app.loadTaskCreation(task);
      if (!creation) return;
      if (runId !== publishOpenRunRef.current) return;
      if (selectedTaskIdRef.current !== task.id) return;
      const latestTask = tasksRef.current.find((item) => item.id === task.id);
      if (!canPublishWorkflowTask(latestTask) || isTaskTransitioning(latestTask?.id)) {
        app.addToast("任务已不在待发布阶段", "warning");
        return;
      }
      setPublishingTaskId(task.id);
      setPublishDraft(buildWorkflowPublishDraft(creation, latestTask));
    } catch (error) {
      if (runId === publishOpenRunRef.current) {
        app.addToast(error.message || "发布内容读取失败", "warning");
      }
    } finally {
      if (runId === publishOpenRunRef.current) setPublishBusy("");
    }
  };

  const closePublish = () => {
    if (publishInFlightRef.current) return;
    publishOpenRunRef.current += 1;
    setPublishDraft(null);
    setPublishingTaskId("");
    setPublishBusy("");
    setPublishError("");
  };

  const confirmPublish = async () => {
    if (publishInFlightRef.current) return;
    if (!publishDraft || publishBusy || isWorkflowPublishActive(publishState?.status)) return;
    const latestTask = tasksRef.current.find((task) => task.id === publishingTaskId);
    if (
      !canPublishWorkflowTask(latestTask)
      || isTaskTransitioning(latestTask?.id)
      || latestTask.creationId !== publishDraft.creationId
    ) {
      setPublishError("任务已不在待发布阶段，请关闭后刷新流程");
      return;
    }
    if (!platformSupported) {
      setPublishError("当前平台暂不支持自动发布");
      return;
    }
    if (!deviceConfigured) {
      setPublishError("请先配置当前平台的发布设备 ID");
      return;
    }

    publishInFlightRef.current = true;
    setPublishBusy("publishing");
    setPublishError("");
    try {
      const retry = ["failed", "cancelled"].includes(publishState?.status);
      const payload = buildWorkflowPublishPayload({ ...publishDraft, retry });
      await app.publishCreation(publishDraft.creationId, payload);
    } catch (error) {
      setPublishError(error.message || "发布失败，请稍后重试");
      // 发布服务可能已在返回错误前记录失败状态；同步后才能正确提交 retry=true。
      await app.loadTaskCreation?.(latestTask).catch(() => null);
    } finally {
      publishInFlightRef.current = false;
      setPublishBusy("");
    }
  };

  const uploadPublishVideo = async (file) => {
    if (!publishDraft?.creationId || publishDraft.type !== "video" || publishBusy) return;
    setPublishBusy("uploading");
    setPublishError("");
    try {
      const uploaded = await app.uploadPublishVideo(
        publishDraft.creationId,
        publishDraft.taskId,
        file,
      );
      const candidate = {
        url: uploaded.url,
        kind: "video",
        label: uploaded.filename || file.name,
        workflowTaskId: uploaded.taskId,
        uploadRef: uploaded,
      };
      setPublishDraft((current) => current ? {
        ...current,
        mediaCandidates: [candidate],
        selectedMediaUrls: [uploaded.url],
      } : current);
    } catch (uploadError) {
      setPublishError(uploadError.message || "视频上传失败，请重试");
    } finally {
      setPublishBusy("");
    }
  };

  const uploadPublishImages = async (files) => {
    if (!publishDraft?.creationId || publishDraft.type !== "image" || publishBusy || !files?.length) return;
    setPublishBusy("uploading");
    setPublishError("");
    try {
      const uploaded = await app.uploadPublishImages(
        publishDraft.creationId,
        publishDraft.taskId,
        files,
      );
      const candidates = uploaded.map((item, index) => ({
        url: item.url,
        kind: "image",
        label: item.filename || files[index]?.name || `本地图片 ${index + 1}`,
        workflowTaskId: item.taskId,
        uploadRef: item,
      }));
      const uploadedUrls = candidates.map((candidate) => candidate.url);
      setPublishDraft((current) => current ? {
        ...current,
        mediaCandidates: [...(current.mediaCandidates || []), ...candidates],
        selectedMediaUrls: [...new Set([...(current.selectedMediaUrls || []), ...uploadedUrls])],
      } : current);
    } catch (uploadError) {
      setPublishError(uploadError.message || "图片上传失败，请检查格式和大小后重试");
    } finally {
      setPublishBusy("");
    }
  };

  return (
    <div className="workflow-page">
      <header className="workflow-header">
        <div>
          <h2>流程管理 · <span className="hl">{app.currentAccount?.name}</span></h2>
          <p>在一个矩阵中查看创作、拍摄、审核与发布进度</p>
        </div>
        <button className="btn btn-primary" onClick={() => app.startBlankCreation?.()}>＋ 新建任务</button>
      </header>

      <section className="workflow-stats" aria-label="流程统计">
        <div><i className="cyan" /><span>进行中</span><strong>{stats.active}</strong></div>
        <div><i className="yellow" /><span>待发布</span><strong>{stats.pendingPublish}</strong></div>
        <div><i className="red" /><span>已逾期</span><strong>{stats.overdue}</strong></div>
        <div><i className="green" /><span>已完成</span><strong>{stats.completed}</strong></div>
      </section>

      <section className="workflow-filters" aria-label="筛选流程任务">
        <input
          value={searchKeyword}
          onChange={(event) => {
            setSearchKeyword(event.target.value);
            setTaskPage(1);
          }}
          placeholder="搜索任务标题或关键词"
        />
        <select value={assigneeFilter} onChange={(event) => {
          setAssigneeFilter(event.target.value);
          setTaskPage(1);
        }}>
          <option value="all">全部负责人</option>
          {assignees.map((assignee) => <option key={assignee} value={assignee}>{assignee}</option>)}
        </select>
        <select value={stageFilter} onChange={(event) => {
          setStageFilter(event.target.value);
          setTaskPage(1);
        }}>
          <option value="all">全部阶段</option>
          {WORKFLOW_STAGES.map((stage) => <option key={stage.key} value={stage.key}>{stage.label}</option>)}
        </select>
        <select value={platformFilter} onChange={(event) => {
          setPlatformFilter(event.target.value);
          setTaskPage(1);
        }}>
          <option value="all">全部平台</option>
          {platforms.map((platform) => <option key={platform} value={platform}>{platform}</option>)}
        </select>
      </section>

      <div className="workflow-legend" aria-label="阶段图例">
        <span><i className="done" />已完成</span>
        <span><i className="active" />当前阶段</span>
        <span><i className="pending" />待推进</span>
      </div>

      <WorkflowMatrix
        tasks={pagedTasks}
        stages={WORKFLOW_STAGES}
        selectedTaskId={selectedTaskId}
        onSelectTask={selectTask}
        currentPage={currentPage}
        totalPages={totalPages}
        onPageChange={setTaskPage}
      />

      <WorkflowDetailDrawer
        task={selectedTask}
        stages={WORKFLOW_STAGES}
        canPublish={canPublishWorkflowTask(selectedTask) && !isTaskTransitioning(selectedTask?.id)}
        transitioning={isTaskTransitioning(selectedTask?.id)}
        duplicating={duplicatingTaskId === selectedTask?.id}
        suspended={Boolean(publishDraft)}
        onClose={closeTaskDetails}
        onAdvance={advanceTask}
        onRetreat={retreatTask}
        onMove={moveTask}
        onDelete={deleteTask}
        onDuplicate={duplicateTask}
        onOpen={(task) => app.openTaskCreation?.(task)}
        onPublish={openPublish}
      />

      {publishBusy === "loading" ? (
        <div className="workflow-loading-toast" role="status">正在读取发布内容…</div>
      ) : null}

      {publishDraft ? (
        <WorkflowPublishModal
          draft={publishDraft}
          publishState={publishState}
          deviceConfigured={deviceConfigured}
          platformSupported={platformSupported}
          busy={Boolean(publishBusy)}
          uploading={publishBusy === "uploading"}
          suspended={Boolean(app.showAddAccountModal)}
          error={publishError}
          onChange={(patch) => setPublishDraft((current) => current ? { ...current, ...patch } : current)}
          onUploadImages={uploadPublishImages}
          onUploadVideo={uploadPublishVideo}
          onConfirm={confirmPublish}
          onRefresh={() => app.refreshPublishStatus?.(publishDraft.creationId)}
          onConfigureDevice={() => app.openAccountModal?.(app.currentAccount)}
          onClose={closePublish}
        />
      ) : null}
    </div>
  );
}
