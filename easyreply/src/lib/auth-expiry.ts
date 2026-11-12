// ============================================================
// 登录失效（token_expired）统一处理
// - 全局 HTTP 拦截到出参 { detail: "token_expired" } 时触发
// - Toast 提示「登录失效，请重新登录」
// - 清理登录态 / IM / 推送监听，并跳转登录页
// - 并发请求只会触发一次（去重），新 token 写入后自动复位
// ============================================================
import { router } from 'expo-router';

import { clearToken } from '@/core/auth';
import { getAgentId, getTenantId } from '@/core/im/config';
import { showToast } from '@/lib/app-toast';
import { beginAuthExpiredHandling, resetAuthExpiredGuard } from '@/lib/auth-expiry-guard';

export { resetAuthExpiredGuard };

/**
 * 检测响应体是否为登录失效。
 */
export function isTokenExpiredBody(body: unknown): boolean {
  if (typeof body !== 'object' || body === null) return false;
  const detail = (body as { detail?: unknown }).detail;
  return typeof detail === 'string' && detail === 'token_expired';
}

/**
 * 触发登录失效流程。重复调用在首次处理后被忽略，直到 resetAuthExpiredGuard。
 */
export function handleAuthExpired(): void {
  if (!beginAuthExpiredHandling()) return;

  showToast('登录失效，请重新登录', { duration: 2000, variant: 'danger' });

  // clearToken 会 resetAgentIdentity，先同步取出再异步做副作用
  const agentId = getAgentId();
  const tenantId = getTenantId();
  void import('@/lib/auth-expiry-side-effects')
    .then((m) => m.runAuthExpiredSideEffects({ agentId, tenantId }))
    .catch(() => {});

  clearToken();

  // 略延后跳转，让 Toast 先渲染
  setTimeout(() => {
    try {
      router.replace('/login');
    } catch (e) {
      console.warn('[AuthExpired] 跳转登录页失败', e);
    }
  }, 300);
}
