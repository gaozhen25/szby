// ============================================================
// Admin API
// GET /api/admin/agents/{agent_id}
// PATCH /api/admin/agents/{agent_id}
// GET /api/admin/tasks/{task_id}
// App API（Auth：10007 / /tms）
// GET    /api/app/agents/{agent_id}/collected_audiences
// POST   /api/app/agents/{agent_id}/collected_audiences/{audience_platform_id}
// DELETE /api/app/agents/{agent_id}/collected_audiences/{audience_platform_id}
// App API（聊天：10008 / /tagmanager）
// POST   /api/app/agents/list
// ============================================================
import { get, patch, post, del, ApiError } from '@/lib/http';
import { getAuthApiBaseUrl } from '@/lib/api-host';
import type { AgentInfo } from '@/api/auth';
import type { IMTask } from '@/core/im/types';
import { withTaskLastMessage } from '@/core/im/utils';
import { getAgentId, getTenantId } from '@/core/im/config';

/** GET /api/admin/agents/{agent_id} 响应 */
export interface AdminAgentResult {
  ok: boolean;
  item: AgentInfo;
}

/** PATCH /api/admin/agents/{agent_id} 入参（按需传字段；改备注仅传 additional_info） */
export interface PatchAdminAgentParams {
  /** 已收藏教练 actor id 列表 */
  collected_actor_ids?: string[];
  additional_info?: string;
}

/** PATCH /api/admin/agents/{agent_id} 响应 */
export interface PatchAdminAgentResult {
  ok: boolean;
  item?: AgentInfo;
}

/** 查询单个 agent 详情（管理端接口） */
export function fetchAdminAgent(agentId: string): Promise<AdminAgentResult> {
  const id = agentId.trim();
  return get<AdminAgentResult>(`/api/admin/agents/${encodeURIComponent(id)}`, undefined, {
    baseURL: getAuthApiBaseUrl(),
  });
}

/** 主管修改标注员资料（备注等） */
export function patchAdminAgent(
  agentId: string,
  params: PatchAdminAgentParams,
): Promise<PatchAdminAgentResult> {
  const id = agentId.trim();
  const body: Record<string, unknown> = {};
  if (params.collected_actor_ids !== undefined) {
    body.collected_actor_ids = params.collected_actor_ids;
  }
  if (params.additional_info !== undefined) {
    body.additional_info = params.additional_info;
  }
  return patch<PatchAdminAgentResult>(
    `/api/admin/agents/${encodeURIComponent(id)}`,
    body,
    { baseURL: getAuthApiBaseUrl() },
  );
}

/** GET /api/admin/tasks/{task_id} 响应 */
export interface AdminTaskResult {
  ok: boolean;
  item: IMTask;
}

/** 查询单个任务详情（管理端接口） */
export function fetchAdminTask(taskID: string): Promise<AdminTaskResult> {
  const id = taskID.trim();
  return get<AdminTaskResult>(`/api/admin/tasks/${encodeURIComponent(id)}`, undefined, {
    baseURL: getAuthApiBaseUrl(),
  }).then((res) => ({
    ...res,
    item: withTaskLastMessage(res.item),
  }));
}

/** 客服收藏 Audience 入参 */
export interface CollectedAudienceParams {
  agent_id?: string;
  audience_platform_id: string;
}

/** 客服收藏 Audience 响应 */
export interface CollectedAudienceResult {
  ok: boolean;
  collected_audience_ids: string[];
}

function collectedAudiencePath(agentId: string, audiencePlatformId?: string): string {
  const base = `/api/app/agents/${encodeURIComponent(agentId.trim())}/collected_audiences`;
  if (!audiencePlatformId?.trim()) return base;
  return `${base}/${encodeURIComponent(audiencePlatformId.trim())}`;
}

/** 客服查询自己已收藏的 Audience 列表 */
export function listCollectedAudiences(
  agentId = getAgentId(),
): Promise<CollectedAudienceResult> {
  return get<CollectedAudienceResult>(collectedAudiencePath(agentId), undefined, {
    baseURL: getAuthApiBaseUrl(),
  });
}

/** 客服自助收藏一个终端用户（Audience，幂等） */
export function addCollectedAudience(
  params: CollectedAudienceParams,
): Promise<CollectedAudienceResult> {
  const agentId = (params.agent_id ?? getAgentId()).trim();
  return post<CollectedAudienceResult>(
    collectedAudiencePath(agentId, params.audience_platform_id),
    undefined,
    { baseURL: getAuthApiBaseUrl() },
  );
}

/** 客服取消收藏一个 Audience（幂等） */
export function removeCollectedAudience(
  params: CollectedAudienceParams,
): Promise<CollectedAudienceResult> {
  const agentId = (params.agent_id ?? getAgentId()).trim();
  return del<CollectedAudienceResult>(
    collectedAudiencePath(agentId, params.audience_platform_id),
    undefined,
    { baseURL: getAuthApiBaseUrl() },
  );
}

const COLLECTED_AUDIENCE_ERROR_MAP: Record<string, string> = {
  collected_audience_limit_reached: '收藏已达上限',
  agent_not_found: '客服不存在',
  not_self: '只能操作自己的收藏',
  pg_store_not_configured: '服务暂不可用，请稍后重试',
};

/** 解析收藏 Audience 接口错误文案 */
export function formatCollectedAudienceError(
  e: unknown,
  fallback = '操作失败，请稍后重试',
): string {
  if (!(e instanceof ApiError)) return fallback;
  const body = e.body as { detail?: string; message?: string; error?: string; code?: string } | null;
  const code =
    (typeof body?.detail === 'string' && body.detail) ||
    (typeof body?.code === 'string' && body.code) ||
    (typeof body?.error === 'string' && body.error) ||
    (typeof body?.message === 'string' && body.message) ||
    '';
  if (code && COLLECTED_AUDIENCE_ERROR_MAP[code]) return COLLECTED_AUDIENCE_ERROR_MAP[code];
  if (e.message && COLLECTED_AUDIENCE_ERROR_MAP[e.message]) {
    return COLLECTED_AUDIENCE_ERROR_MAP[e.message];
  }
  if (code) return code;
  return e.message || fallback;
}

/** POST /api/app/agents/list：转派时可选的客服（role=agent，不含主管） */
export type AppAgentListItem = {
  agent_id: string;
  agent_account: string;
  ws_online: boolean;
  on_duty: boolean;
  current_task_count: number;
  max_active_cap: number;
};

export type AppAgentListResult = {
  ok: boolean;
  tenant_id: string;
  agent_count: number;
  agents: AppAgentListItem[];
};

/** 查询全体客服账号、在线/上班状态、当前会话数与上限 */
export function listAppAgents(tenantId = getTenantId()): Promise<AppAgentListResult> {
  return post<AppAgentListResult>('/api/app/agents/list', {
    tenant_id: tenantId,
  });
}
