// ============================================================
// 认证会话（Token + agent_id + 用户详情）
// 登录成功：setToken + setAgentId + tenant_id=agent_id（WS/业务接口）
// 会话可持久化到本地，杀进程后 hydrate 实现自动登录
// ============================================================

import type { AgentInfo } from '@/api/auth';
import { resetAuthExpiredGuard } from '@/lib/auth-expiry-guard';
import { resetAgentIdentity, setAgentId, setTenantId } from '@/core/im/config';
import { setSentryUser } from '@/core/sentry';
import {
  clearAuthSession,
  loadAuthSession,
  saveAuthSession,
} from '@/core/auth-persist';

let _token: string | null = null;
let _tokenType: string = 'Bearer';
let _agentId: string | null = null;
let _agentAccount: string | null = null;
let _role: string | null = null;
let _userInfo: AgentInfo | null = null;

type UserInfoListener = () => void;
const userInfoListeners = new Set<UserInfoListener>();

function emitUserInfo(): void {
  for (const l of userInfoListeners) {
    try {
      l();
    } catch {
      // ignore
    }
  }
}

/** 订阅用户详情变更（登录 / hydrate / 刷新 me 后广播） */
export function subscribeUserInfo(cb: UserInfoListener): () => void {
  userInfoListeners.add(cb);
  return () => {
    userInfoListeners.delete(cb);
  };
}

export function setToken(token: string, tokenType: string = 'Bearer'): void {
  _token = token;
  _tokenType = tokenType;
  if (token) resetAuthExpiredGuard();
}

export function applyLoginSession(params: {
  token: string;
  agent_id: string;
  role?: string;
  agent_accout?: string;
}): void {
  setToken(params.token);
  _agentId = params.agent_id;
  _role = params.role ?? null;
  _agentAccount = params.agent_accout ?? null;
  setAgentId(params.agent_id);
  // 文档：WS tenant_id 取值 agent_id
  setTenantId(params.agent_id);
  bindSentryUser();
}

export function setUserInfo(info: AgentInfo | null): void {
  _userInfo = info;
  emitUserInfo();
  if (!info) return;
  _agentId = info.agent_id;
  _agentAccount = info.agent_accout;
  _role = info.role;
  setAgentId(info.agent_id);
  setTenantId(info.agent_id);
  bindSentryUser();
}

export function getUserInfo(): AgentInfo | null {
  return _userInfo;
}

/** 将当前内存会话写盘（登录成功 / 刷新 me 后调用） */
export async function persistAuthSession(): Promise<void> {
  if (!_token || !_agentId) return;
  await saveAuthSession({
    token: _token,
    tokenType: _tokenType,
    agentId: _agentId,
    agentAccount: _agentAccount,
    role: _role,
    userInfo: _userInfo,
  });
}

/**
 * 从本地恢复会话到内存。
 * @returns 是否恢复成功（有有效 token）
 */
export async function hydrateAuthFromStorage(): Promise<boolean> {
  const session = await loadAuthSession();
  if (!session?.token?.trim() || !session?.agentId?.trim()) {
    return false;
  }
  applyLoginSession({
    token: session.token,
    agent_id: session.agentId,
    role: session.role ?? undefined,
    agent_accout: session.agentAccount ?? undefined,
  });
  setToken(session.token, session.tokenType);
  if (session.userInfo) setUserInfo(session.userInfo);
  if (!isLoggedIn()) {
    clearToken();
    return false;
  }
  return true;
}

export function clearToken(): void {
  _token = null;
  _tokenType = 'Bearer';
  _agentId = null;
  _agentAccount = null;
  _role = null;
  _userInfo = null;
  emitUserInfo();
  resetAgentIdentity();
  setSentryUser(null);
  // 清除持久化会话；登录凭证（账号密码）保留供登录页填充
  void clearAuthSession();
}

function bindSentryUser(): void {
  if (!_agentId) {
    setSentryUser(null);
    return;
  }
  setSentryUser({
    id: _agentId,
    nickname: _agentAccount || _agentId,
    role: _role,
  });
}

export function getToken(): string | null {
  return _token;
}

export function getAuthHeader(): string {
  if (!_token) return '';
  return `${_tokenType} ${_token}`;
}

export function getAgentIdFromAuth(): string | null {
  return _agentId;
}

export function getAgentAccount(): string | null {
  return _agentAccount;
}

export function getRole(): string | null {
  return _role;
}

export function isLoggedIn(): boolean {
  return !!_token?.trim() && !!_agentId?.trim();
}

export default {
  setToken,
  applyLoginSession,
  setUserInfo,
  getUserInfo,
  persistAuthSession,
  hydrateAuthFromStorage,
  clearToken,
  getToken,
  getAuthHeader,
  getAgentIdFromAuth,
  getAgentAccount,
  getRole,
  isLoggedIn,
};
