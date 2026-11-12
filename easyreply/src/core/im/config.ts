// ============================================================
// IM WebSocket 连接配置（v2 网关）
// 连接地址：ws://<host>:10008/ws/events?token=xxx&agent_id=xxx&tenant_id=xxx
// ============================================================

import { getImWsBaseUrl } from '@/lib/api-host';
import { generateSessionId, imLog } from './utils';
const DEFAULT_AGENT_ID = (process.env.EXPO_PUBLIC_IM_AGENT_ID as string) || '';
const DEFAULT_TENANT_ID = (process.env.EXPO_PUBLIC_IM_TENANT_ID as string) || '';

let _overrideWsUrl: string | null = null;
let _agentId = DEFAULT_AGENT_ID;
let _tenantId = DEFAULT_TENANT_ID;
let _sessionId: string | null = null;

export function getImWsUrl(): string {
  if (_overrideWsUrl !== null) return _overrideWsUrl.trim();
  return getImWsBaseUrl().trim();
}

export function setImWsUrl(url: string): void { _overrideWsUrl = url.trim(); }
export function clearImWsUrlOverride(): void { _overrideWsUrl = null; }
export function isImWsUrlConfigured(): boolean { return getImWsUrl().length > 0; }

// ---------- 连接标识（v2：agent_id 必传，tenant_id 必传） ----------

/** 当前 agent_id（登录后由 applyLoginSession 写入） */
export function getAgentId(): string { return _agentId; }
export function setAgentId(agentId: string): void { _agentId = agentId.trim(); }

/** 租户标识（文档：取值 agent_id） */
export function getTenantId(): string { return _tenantId; }
export function setTenantId(tenantId: string): void { _tenantId = tenantId.trim(); }

/** 退出登录时重置连接标识 */
export function resetAgentIdentity(): void {
  _agentId = DEFAULT_AGENT_ID;
  _tenantId = DEFAULT_TENANT_ID;
}

/**
 * @deprecated v2 网关不再使用 session_id（建连返回 agent_id/connection_id，断线恢复走 REST 重拉）。
 * 仅为兼容旧引用保留。
 */
export function getSessionId(): string {
  if (!_sessionId) _sessionId = generateSessionId();
  return _sessionId;
}
export function setSessionId(sessionId: string): void { _sessionId = sessionId.trim() || null; }

/**
 * 构造 v2 网关连接地址：token + agent_id + tenant_id 查询参数鉴权。
 */
export function buildImWsUrl(token?: string | null): string {
  const base = getImWsUrl();
  if (!base) return '';
  const sep = base.includes('?') ? '&' : '?';
  const params = new URLSearchParams();
  if (token) params.set('token', token);
  params.set('agent_id', getAgentId());
  params.set('tenant_id', getTenantId());
  const url = `${base}${sep}${params.toString()}`;
  imLog('配置层', '已构造 WebSocket 连接地址', {
    agent_id: getAgentId(),
    tenant_id: getTenantId(),
    has_token: Boolean(token),
  });
  return url;
}

export default {
  getImWsUrl, setImWsUrl, clearImWsUrlOverride, isImWsUrlConfigured, buildImWsUrl,
  getAgentId, setAgentId, getTenantId, setTenantId, resetAgentIdentity, getSessionId, setSessionId,
};
