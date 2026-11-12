// ============================================================
// v2 网关 REST 接口（access 服务）
// 文档：app_integration_for_agent_app v2
// - 任务查询/领取、按会话拉历史
// - 客服动作（释放 / 上报转接）
// - 主管动作（进入 / 退出 / 接管 / 归还）
// - 会话结束 / 系统强制接管
// 动作类接口为「入队模型」：HTTP 仅表示已接收，最终结果走 WS 下行 *_result
// ============================================================
import { post } from '@/lib/http';
import { getAgentId, getTenantId } from '@/core/im/config';
import { normalizeServerMessages, withTaskLastMessage } from '@/core/im/utils';
import type { IMServerMessage, IMTask, TaskMode } from '@/core/im/types';

// ---------- 通用返回 ----------

/** 动作类接口的入队回执（HTTP 同步返回，仅表示已接收） */
export interface ActionEnqueueAck {
  agent_id: string;       // 发起方 agent_id
  received: boolean;      // 是否已接收并入队
  queue_length: number;   // 当前入队长度
}

// ---------- 4.1 任务查询类 ----------

export interface PendingListParams {
  skillGroupID?: string;
  actorPlatformID?: string;
  pageNumber?: number;
  showNumber?: number;
}
export interface PendingListResult {
  ok: boolean;
  tasks: IMTask[];
  total: number;
  pendingCount: number;
  pageNumber: number;
  showNumber: number;
}

/** 拉取当前待领取任务列表 */
export function fetchPendingTasks(params: PendingListParams = {}): Promise<PendingListResult> {
  return post<PendingListResult>('/api/app/tasks/pending/list', {
    // skillGroupID: params.skillGroupID ?? 'default',
    actorPlatformID: params.actorPlatformID ?? '',
    pageNumber: params.pageNumber ?? 1,
    showNumber: params.showNumber ?? 20,
  });
}

export interface ClaimItem { annotatorID: string; taskIDs: string[] }
export interface ClaimResult {
  ok: boolean;
  results: { annotatorID: string; taskID: string; ok: boolean; error: string; task?: IMTask }[];
  claimedCount: number;
}

/** 批量领取任务 */
export function claimTasks(
  claims: ClaimItem[],
  opts: { claimTTLSeconds?: number; messageLimit?: number } = {},
): Promise<ClaimResult> {
  return post<ClaimResult>('/api/app/tasks/claim', {
    claims,
    claimTTLSeconds: opts.claimTTLSeconds ?? 1800,
    messageLimit: opts.messageLimit ?? 20,
  });
}

export interface ClaimedListResult { ok: boolean; tasks: IMTask[]; claimedCount: number }

/** 查询某个接待人已领取的任务（“我的会话列表”数据源） */
export function fetchClaimedTasks(params: {
  annotatorID?: string;
  skillGroupID?: string;
  limit?: number;
  messageLimit?: number;
} = {}): Promise<ClaimedListResult> {
  return post<ClaimedListResult>('/api/app/tasks/claimed/list', {
    annotatorID: params.annotatorID ?? getAgentId(),
    // skillGroupID: params.skillGroupID ?? 'default',
    limit: params.limit ?? 1000,
    messageLimit: params.messageLimit ?? 1,
  }).then((res) => ({
    ...res,
    tasks: (res.tasks ?? []).map((task) =>
      withTaskLastMessage({
        ...task,
        // claimed/list 是 taskMode 的权威来源；兼容历史 ai 值并统一为 ai_assisted
        taskMode:
          task.taskMode === 'ai_assisted' || (task.taskMode as string) === 'ai'
            ? 'ai_assisted'
            : task.taskMode === 'human'
              ? 'human'
              : undefined,
      }),
    ),
  }));
}

export interface TaskDetailResult { ok: boolean; task: IMTask; messages: IMServerMessage[] }

/** 查询单个任务详情（messageLimit=1 时可取最新一条消息作锚点） */
export function fetchTaskDetail(taskID: string, opts: { annotatorID?: string; messageLimit?: number } = {}): Promise<TaskDetailResult> {
  return post<TaskDetailResult>('/api/app/tasks/detail', {
    taskID,
    annotatorID: opts.annotatorID ?? getAgentId(),
    messageLimit: opts.messageLimit ?? 20,
  }).then((res) => ({
    ...res,
    messages: normalizeServerMessages(res.messages ?? []),
  }));
}

/** 锚点方向：1=查更早消息，2=查更晚消息 */
export type AnchorDirection = 1 | 2;

export interface MessagesByConversationParams {
  conversationID: string;
  annotatorID?: string;
  pageNumber?: number;
  showNumber?: number;
  /** 锚点消息 id（与 pageNumber 二选一，优先锚点分页） */
  anchorServerMsgID?: string;
  anchorDirection?: AnchorDirection;
  /** 是否包含锚点本身，默认 false 避免重复渲染 */
  includeAnchor?: boolean;
}

export interface MessagesByConversationResult {
  ok: boolean;
  session: {
    sessionID: string;
    actorPlatformID: string;
    audiencePlatformID: string;
    imConversationID: string;
    skillGroupID: string;
  };
  total: number;
  /** 当前结果前面是否还有更早消息 */
  hasMoreBefore?: boolean;
  /** 当前结果后面是否还有更晚消息 */
  hasMoreAfter?: boolean;
  messages: IMServerMessage[];
}

/** 按会话拉取历史消息（支持普通分页与锚点分页，优先锚点） */
export function fetchMessagesByConversation(params: MessagesByConversationParams): Promise<MessagesByConversationResult> {
  const body: Record<string, unknown> = {
    conversationID: params.conversationID,
    annotatorID: params.annotatorID ?? getAgentId(),
    showNumber: params.showNumber ?? 20,
  };

  if (params.anchorServerMsgID) {
    body.anchorServerMsgID = params.anchorServerMsgID;
    body.anchorDirection = params.anchorDirection ?? 1;
    body.includeAnchor = params.includeAnchor ?? false;
  } else {
    body.pageNumber = params.pageNumber ?? 1;
  }

  return post<MessagesByConversationResult>('/api/app/messages/by_conversation', body).then((res) => ({
    ...res,
    messages: normalizeServerMessages(res.messages ?? []),
  }));
}

// ---------- 4.2 客服主动动作 ----------

/** 上班登记返回 */
export interface DutyOnResult {
  ok: boolean;            // 是否成功
  agent_id: string;       // 客服id
  tenant_id: string;      // 租户id
  on_duty: boolean;       // 当前是否在岗
  ttl_seconds?: number;   // 在岗状态自动过期秒数（WS ping 心跳会自动续期）
}

/** 下班登记返回 */
export interface DutyOffResult {
  ok: boolean;                // 是否成功
  agent_id: string;           // 客服id
  tenant_id: string;          // 租户id
  on_duty: boolean;           // 当前是否在岗
  reclaimedTaskCount?: number; // 下班回收的任务数
}

export interface DutyProfile {
  role?: string;
  supervisor_id?: string;
  domains?: string[];
  subordinate_agent_ids?: string[];
  max_active_cap?: number;
  valid?: boolean;
  is_fallback?: boolean;
  collected_actor_ids?: string[];
  /** 已收藏终端用户 Audience platform id 列表 */
  collected_audience_ids?: string[];
  /** 主管指派的独占 Actor platform id 列表 */
  exclusive_actor_ids?: string[];
  updated_at?: number;
}

/** 查询客服当前上下班状态及 duty profile */
export interface DutyStatusResult {
  ok: boolean;
  agent_id: string;
  tenant_id: string;
  on_duty: boolean;
  profile?: DutyProfile | null;
}

/** 客服登记上班（仅在岗才会被自动分配任务） */
export function dutyOn(agentId = getAgentId(), tenantId = getTenantId()): Promise<DutyOnResult> {
  return post<DutyOnResult>('/api/app/agents/duty/on', { agent_id: agentId, tenant_id: tenantId });
}

/** 客服登记下班（下班后不再参与自动领取） */
export function dutyOff(agentId = getAgentId(), tenantId = getTenantId()): Promise<DutyOffResult> {
  return post<DutyOffResult>('/api/app/agents/duty/off', { agent_id: agentId, tenant_id: tenantId });
}

/** 查询上下班状态（服务端缓存为准） */
export function dutyStatus(agentId = getAgentId(), tenantId = getTenantId()): Promise<DutyStatusResult> {
  return post<DutyStatusResult>('/api/app/agents/duty/status', { agent_id: agentId, tenant_id: tenantId });
}

/** 接待新任务开关状态 */
export interface IntakeStatusResult {
  ok: boolean;
  agent_id: string;
  tenant_id: string;
  intake_paused: boolean;
  reason: string;
  updated_at: number;
}

export interface IntakeSetParams {
  agent_id?: string;
  tenant_id?: string;
  paused: boolean;
  reason?: string;
}

/** 查询当前接待新任务开关状态 */
export function intakeStatus(
  agentId = getAgentId(),
  tenantId = getTenantId(),
): Promise<IntakeStatusResult> {
  return post<IntakeStatusResult>('/api/app/agents/intake/status', {
    agent_id: agentId,
    tenant_id: tenantId,
  });
}

/** 开关接待新任务（paused=true 暂停接收新分配；不影响已有任务与 on_duty） */
export function intakeSet(params: IntakeSetParams): Promise<IntakeStatusResult> {
  const agentId = (params.agent_id ?? getAgentId()).trim();
  const tenantId = (params.tenant_id ?? getTenantId()).trim();
  const body: Record<string, unknown> = {
    agent_id: agentId,
    tenant_id: tenantId,
    paused: params.paused,
  };
  if (params.paused && params.reason?.trim()) {
    body.reason = params.reason.trim();
  }
  return post<IntakeStatusResult>('/api/app/agents/intake/set', body);
}

/** 释放任务回池（≠结束会话）。结果走 WS release_task_result */
export function releaseTask(taskID: string, agentId = getAgentId()): Promise<ActionEnqueueAck> {
  return post<ActionEnqueueAck>('/api/app/tasks/release', { agent_id: agentId, taskID });
}

/** 客服把当前持有任务转派给另一客服。结果走 WS transfer_task_result + 新持有人 ownership_changed */
export function transferTasks(
  taskIDs: string[],
  toAnnotatorID: string,
  opts: { reason?: string; agentId?: string } = {},
): Promise<ActionEnqueueAck> {
  const ids = taskIDs.map((id) => id.trim()).filter(Boolean);
  if (!ids.length) {
    return Promise.reject(new Error('taskIDs is required'));
  }
  const body: Record<string, unknown> = {
    agent_id: opts.agentId ?? getAgentId(),
    taskIDs: ids,
    toAnnotatorID,
  };
  const reason = opts.reason?.trim();
  if (reason) body.reason = reason;
  return post<ActionEnqueueAck>('/api/app/tasks/transfer', body);
}

export function transferTask(
  taskID: string,
  toAnnotatorID: string,
  opts: { reason?: string; agentId?: string } = {},
): Promise<ActionEnqueueAck> {
  return transferTasks([taskID], toAnnotatorID, opts);
}

/** 客服上报转接给主管（可带 reason）。结果走 WS report_transfer_result */
export function reportTransfer(
  taskID: string,
  opts: { reason?: string; agentId?: string } = {},
): Promise<ActionEnqueueAck> {
  console.log('reportTransfer------taskID', taskID, 'opts', opts);
  return post<ActionEnqueueAck>('/api/app/actions/report_transfer', {
    agent_id: opts.agentId ?? getAgentId(),
    payload: { taskID, reason: opts.reason },
  });
}

/** 客服显式确认「已处理」：暂停待处理超时倒计时。结果走 WS ack_pending_result */
export function ackTaskPending(
  taskID: string,
  agentId = getAgentId(),
): Promise<ActionEnqueueAck> {
  return post<ActionEnqueueAck>('/api/app/actions/task_ack_pending', {
    agent_id: agentId,
    payload: { taskID },
  });
}

/** 按消息确认已看/已处理。AI 复审确定/已处理后调用。结果走 WS（若有） */
export function ackTaskMessage(
  taskID: string,
  serverMsgID: string,
  agentId = getAgentId(),
): Promise<ActionEnqueueAck> {
  return post<ActionEnqueueAck>('/api/app/actions/ack_task_message', {
    agent_id: agentId,
    payload: { taskID, serverMsgID },
  });
}

// ---------- 4.3 主管流程动作（入队） ----------

function supervisorAction(path: string, taskID: string, agentId: string): Promise<ActionEnqueueAck> {
  return post<ActionEnqueueAck>(path, { agent_id: agentId, payload: { taskID } });
}

/** 主管进入监听线程（只读监看）。结果走 supervisor_enter_thread_result */
export function supervisorEnterThread(taskID: string, supervisorId = getAgentId()): Promise<ActionEnqueueAck> {
  return supervisorAction('/api/app/actions/supervisor/enter_thread', taskID, supervisorId);
}

/** 主管退出监听线程。结果走 supervisor_exit_thread_result */
export function supervisorExitThread(taskID: string, supervisorId = getAgentId()): Promise<ActionEnqueueAck> {
  return supervisorAction('/api/app/actions/supervisor/exit_thread', taskID, supervisorId);
}

/** 主管接管当前任务。结果走 supervisor_takeover_result + ownership_changed */
export function supervisorTakeover(taskID: string, supervisorId = getAgentId()): Promise<ActionEnqueueAck> {
  return supervisorAction('/api/app/actions/supervisor/takeover', taskID, supervisorId);
}

/** 主管把任务归还给原客服。结果走 supervisor_return_to_agent_result + ownership_changed */
export function supervisorReturnToAgent(taskID: string, supervisorId = getAgentId()): Promise<ActionEnqueueAck> {
  return supervisorAction('/api/app/actions/supervisor/return_to_agent', taskID, supervisorId);
}

// ---------- 4.4 会话结束 / 系统强制 ----------

/** @deprecated 已弃用，请改用 completeTask。结果原走 end_conversation_result */
export function endConversation(taskID: string, agentId = getAgentId()): Promise<ActionEnqueueAck> {
  return post<ActionEnqueueAck>('/api/app/actions/end_conversation', {
    agent_id: agentId,
    payload: { taskID },
  });
}

/** 标记任务完成（CompleteTask）。结果走 WS complete_task_result */
export function completeTask(
  taskID: string,
  reason: string,
  agentId = getAgentId(),
): Promise<ActionEnqueueAck> {
  return post<ActionEnqueueAck>('/api/app/actions/complete_task', {
    agent_id: agentId,
    payload: { taskID, reason },
  });
}

/** 切换任务处理模式 human/ai_assisted。结果走 WS set_task_mode_result */
export function setTaskMode(
  taskID: string,
  taskMode: TaskMode,
  agentId = getAgentId(),
): Promise<ActionEnqueueAck> {
  return post<ActionEnqueueAck>('/api/app/actions/set_task_mode', {
    agent_id: agentId,
    payload: { taskID, taskMode },
  });
}

/** 系统强制切换归属到指定主管。结果走 system_force_takeover_result */
export function systemForceTakeover(taskID: string, targetSupervisorID: string): Promise<ActionEnqueueAck> {
  return post<ActionEnqueueAck>('/api/app/actions/system_force_takeover', {
    agent_id: 'system',
    payload: { taskID, targetSupervisorID },
  });
}
