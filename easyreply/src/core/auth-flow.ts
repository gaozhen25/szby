import { router } from 'expo-router';
import { fetchMe } from '@/api/auth';
import {
  applyLoginSession,
  clearToken,
  getRole,
  hydrateAuthFromStorage,
  isLoggedIn,
  persistAuthSession,
  setUserInfo,
} from '@/core/auth';
import { saveLoginCredentials } from '@/core/auth-persist';
import { bindPushRegistrationId } from '@/core/push';
import type { LoginResult } from '@/api/auth';
import { dutyOn, dutyStatus } from '@/api/tasks';
import { ApiError } from '@/lib/http';

/** 登录成功 / 冷启动恢复后：拉用户详情、主管上班态、IM/推送 */
async function afterSessionReady(): Promise<void> {
  try {
    const me = await fetchMe();
    if (me?.info) {
      setUserInfo(me.info);
      await persistAuthSession();
    }
  } catch (e) {
    // fetchMe 失败时保留登录接口 / 本地缓存的基础信息；401 视为会话失效
    if (e instanceof ApiError && e.status === 401) throw e;
  }

  // 主管账号默认“永久上班”：如服务端状态为下班，则补一次上班
  if (getRole() === 'supervisor') {
    try {
      const st = await dutyStatus().catch(() => null);
      if (st?.ok && st.on_duty === false) {
        await dutyOn().catch(() => {});
      }
    } catch {
      // 不阻断登录流程
    }
  }

  void bindPushRegistrationId();
  void import('@/core/im').then(({ startIM }) => startIM());
}

/**
 * 应用启动时恢复本地会话（不负责路由）。
 * 多次调用共享同一 Promise，避免 Web 刷新时路由先于 hydrate 误判未登录。
 * @returns true = 已恢复登录态
 */
let authBootstrapPromise: Promise<boolean> | null = null;

async function runAuthBootstrap(): Promise<boolean> {
  const ok = await hydrateAuthFromStorage();
  if (!ok || !isLoggedIn()) {
    clearToken();
    return false;
  }

  // 先恢复本地会话缓存，刷新后 claimed/list 返回前即可展示历史列表
  await import('@/lib/claimed-conversations-store').then(({ ensureClaimedConversationsHydrated }) =>
    ensureClaimedConversationsHydrated(),
  );
  void afterSessionReady().catch((e) => {
    if (e instanceof ApiError && e.status === 401) {
      clearToken();
      authBootstrapPromise = Promise.resolve(false);
      try {
        router.replace('/login');
      } catch (err) {
        console.warn('[Auth] 跳转登录页失败', err);
      }
      return;
    }
    void bindPushRegistrationId();
    void import('@/core/im').then(({ startIM }) => startIM());
  });
  return true;
}

export function waitForAuthBootstrap(): Promise<boolean> {
  if (!authBootstrapPromise) {
    authBootstrapPromise = runAuthBootstrap();
  }
  return authBootstrapPromise;
}

export function bootstrapAuthOnLaunch(): Promise<boolean> {
  return waitForAuthBootstrap();
}

/** 登录/注册页：刷新后即使会话无效也不再跳转 */
export function isAuthPublicPath(pathname: string | null | undefined): boolean {
  const p = pathname ?? '';
  return p.includes('/login') || p.includes('/register');
}

/**
 * 启动或浏览器刷新后：token / agent_id 任一缺失则清会话并跳转登录页。
 * 已在登录/注册页时只清会话，不重复 replace。
 */
export async function ensureAuthIdentityOrLogin(
  pathname?: string | null,
): Promise<boolean> {
  await waitForAuthBootstrap();
  if (isLoggedIn()) return true;

  clearToken();
  if (isAuthPublicPath(pathname)) return false;

  console.warn('[Auth] token 或 agent_id 缺失，退出到登录页');
  try {
    router.replace('/login');
  } catch (e) {
    console.warn('[Auth] 跳转登录页失败', e);
  }
  return false;
}

/** 登录成功后：写入 token/agent_id、拉取用户详情、启动 IM、进入主页 */
export async function completeAuthFlow(
  res: LoginResult,
  agent_accout?: string,
  password?: string,
): Promise<void> {
  const token = res.token?.trim() ?? '';
  const agentId = res.agent_id?.trim() ?? '';
  if (!token || !agentId) {
    clearToken();
    authBootstrapPromise = Promise.resolve(false);
    throw new Error('登录响应缺少 token 或 agent_id');
  }

  applyLoginSession({
    token,
    agent_id: agentId,
    role: res.role,
    agent_accout,
  });
  authBootstrapPromise = Promise.resolve(true);
  await persistAuthSession();

  // 记住账号密码，供退出登录后自动填充
  if (agent_accout && password) {
    await saveLoginCredentials(agent_accout, password);
  }

  try {
    await afterSessionReady();
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) {
      clearToken();
      authBootstrapPromise = Promise.resolve(false);
      throw e;
    }
  }

  router.replace('/(tabs)/chat');
}

/** 刷新当前用户详情（我的页进入时调用） */
export async function refreshUserInfo(): Promise<void> {
  const me = await fetchMe();
  if (me?.info) {
    setUserInfo(me.info);
    await persistAuthSession();
  }
}
