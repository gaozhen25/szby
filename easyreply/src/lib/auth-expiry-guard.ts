// ============================================================
// 登录失效去重标记（无业务依赖，打断 auth ↔ auth-expiry 循环）
// ============================================================

const GLOBAL_KEY = '__qinghui_auth_expired_handled__';

function isHandled(): boolean {
  const g = globalThis as typeof globalThis & { [GLOBAL_KEY]?: boolean };
  return !!g[GLOBAL_KEY];
}

function setHandled(v: boolean): void {
  const g = globalThis as typeof globalThis & { [GLOBAL_KEY]?: boolean };
  g[GLOBAL_KEY] = v;
}

/** 复位去重标记。新 token 写入（登录 / 切号）时调用，允许后续再次触发。 */
export function resetAuthExpiredGuard(): void {
  setHandled(false);
}

/** 若尚未处理则占用处理权并返回 true；已处理过则返回 false。 */
export function beginAuthExpiredHandling(): boolean {
  if (isHandled()) return false;
  setHandled(true);
  return true;
}
