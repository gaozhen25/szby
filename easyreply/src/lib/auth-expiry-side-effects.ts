// ============================================================
// 登录失效副作用（动态侧调用，避免与 http/im/push 形成静态循环依赖）
// ============================================================

export type AuthExpiredSideEffectParams = {
  agentId: string;
  tenantId: string;
};

/** token 失效后：下班通知、停 IM、拆推送监听。失败不抛出。 */
export async function runAuthExpiredSideEffects(
  params: AuthExpiredSideEffectParams,
): Promise<void> {
  try {
    const [{ dutyOff }, { saveDutyState }] = await Promise.all([
      import('@/api/tasks'),
      import('@/core/duty'),
    ]);
    void dutyOff(params.agentId, params.tenantId).catch(() => {});
    void saveDutyState(params.agentId, false).catch(() => {});
  } catch {
    // ignore
  }

  try {
    const { stopIM } = await import('@/core/im/init');
    stopIM();
  } catch {
    // ignore
  }

  try {
    const { teardownPushListeners } = await import('@/core/push');
    teardownPushListeners();
  } catch {
    // ignore
  }
}
