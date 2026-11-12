// ============================================================
// 主管侧 API
// ============================================================
import { post, ApiError } from '@/lib/http';
import { getAgentId, getTenantId } from '@/core/im/config';
import type { DutyProfile } from '@/api/tasks';
import type { IMTaskContext } from '@/core/im/types';

export interface SupervisorAgentTask {
  taskID: string;
  task_context?: IMTaskContext;
}

export interface SupervisorAgentOverview {
  agent_id: string;
  /** 客服登录账号（后端字段名 agent_accout） */
  agent_accout?: string;
  tenant_id: string;
  ws_online: boolean;
  on_duty: boolean;
  intake_paused?: boolean;
  connection_id?: string;
  last_ack_seq?: number;
  last_cursor?: string;
  profile?: DutyProfile | null;
  task_count?: number;
  tasks?: SupervisorAgentTask[];
  /** 主管备注（若 overview 返回） */
  additional_info?: string;
}

export interface SupervisorAgentsOverviewResult {
  ok: boolean;
  supervisor_id: string;
  tenant_id: string;
  agent_count: number;
  agents: SupervisorAgentOverview[];
}

export interface SupervisorSetValidResult {
  ok: boolean;
  supervisor_id: string;
  agent_id: string;
  valid: boolean;
  forced_offline?: boolean;
  reclaimedTaskCount?: number;
}

/** 主管强制下属下班（不停用账号、不断 WS） */
export interface SupervisorForceDutyOffResult {
  ok: boolean;
  supervisor_id: string;
  agent_id: string;
  on_duty: boolean;
  reclaimedTaskCount?: number;
}

export interface ExclusiveActorsParams {
  agent_id: string;
  actor_platform_id: string;
  supervisor_id?: string;
}

export interface ExclusiveActorsResult {
  ok: boolean;
  agent_id: string;
  exclusive_actor_ids: string[];
}

/** 主管查询手下客服列表、WS 在线状态、上班状态及当前持有任务 */
export function fetchSupervisorAgentsOverview(
  supervisorId = getAgentId(),
  tenantId = getTenantId(),
): Promise<SupervisorAgentsOverviewResult> {
  return post<SupervisorAgentsOverviewResult>('/api/app/supervisor/agents/overview', {
    supervisor_id: supervisorId,
    tenant_id: tenantId,
  });
}

/** 主管启用/停用手下客服账号（直接修改组织关系表 valid 字段） */
export function supervisorSetAgentValid(
  agentId: string,
  valid: boolean,
  supervisorId = getAgentId(),
): Promise<SupervisorSetValidResult> {
  return post<SupervisorSetValidResult>('/api/app/supervisor/agents/set_valid', {
    supervisor_id: supervisorId,
    agent_id: agentId,
    valid,
  });
}

/** 主管强制下属客服下班：回收其持有任务，不停用账号，不断开 WS */
export function supervisorForceAgentDutyOff(
  agentId: string,
  supervisorId = getAgentId(),
): Promise<SupervisorForceDutyOffResult> {
  return post<SupervisorForceDutyOffResult>('/api/app/supervisor/agents/duty/force_off', {
    supervisor_id: supervisorId,
    agent_id: agentId,
  });
}

/** 主管为下属客服指派独占 Actor */
export function grantExclusiveActor(
  params: ExclusiveActorsParams,
): Promise<ExclusiveActorsResult> {
  return post<ExclusiveActorsResult>('/api/app/supervisor/agents/exclusive_actors/grant', {
    supervisor_id: params.supervisor_id ?? getAgentId(),
    agent_id: params.agent_id.trim(),
    actor_platform_id: params.actor_platform_id.trim(),
  });
}

/** 主管撤销下属客服的某个独占 Actor 指派 */
export function revokeExclusiveActor(
  params: ExclusiveActorsParams,
): Promise<ExclusiveActorsResult> {
  return post<ExclusiveActorsResult>('/api/app/supervisor/agents/exclusive_actors/revoke', {
    supervisor_id: params.supervisor_id ?? getAgentId(),
    agent_id: params.agent_id.trim(),
    actor_platform_id: params.actor_platform_id.trim(),
  });
}

/** 主管查询已为某个下属客服指派的独占 Actor 列表（直接查库） */
export function listExclusiveActors(
  agentId: string,
  supervisorId = getAgentId(),
): Promise<ExclusiveActorsResult> {
  return post<ExclusiveActorsResult>('/api/app/supervisor/agents/exclusive_actors/list', {
    supervisor_id: supervisorId,
    agent_id: agentId.trim(),
  });
}

const SUPERVISOR_API_ERROR_MAP: Record<string, string> = {
  actor_already_exclusive_to_other_agent: '该客户已被其他客服独占',
  not_supervisor: '无权限操作',
  agent_not_found: '客服不存在',
  pg_store_not_configured: '服务暂不可用，请稍后重试',
};

function supervisorApiErrorCode(e: ApiError): string {
  const body = e.body as { detail?: string; message?: string; code?: string; error?: string } | null;
  return (
    (typeof body?.detail === 'string' && body.detail) ||
    (typeof body?.code === 'string' && body.code) ||
    (typeof body?.error === 'string' && body.error) ||
    (typeof body?.message === 'string' && body.message) ||
    e.message ||
    ''
  );
}

/** 解析主管侧接口错误文案（set_valid / force_off / exclusive_actors 等） */
export function formatSupervisorApiError(
  e: unknown,
  fallback = '操作失败，请稍后重试',
): string {
  if (!(e instanceof ApiError)) {
    return e instanceof Error ? e.message || fallback : fallback;
  }
  const code = supervisorApiErrorCode(e);
  if (code && SUPERVISOR_API_ERROR_MAP[code]) return SUPERVISOR_API_ERROR_MAP[code];
  if (e.message && SUPERVISOR_API_ERROR_MAP[e.message]) return SUPERVISOR_API_ERROR_MAP[e.message];
  if (code) return code;
  return e.message || fallback;
}

/** 解析独占 Actor 接口错误文案 */
export function formatExclusiveActorError(
  e: unknown,
  fallback = '操作失败，请稍后重试',
): string {
  return formatSupervisorApiError(e, fallback);
}
