// ============================================================
// 推送 Token 上报 API
// ============================================================
import { post } from '@/lib/http';

export interface RegisterPushTokenParams {
  registrationId: string;
  platform: 'ios' | 'android';
}

export interface RegisterPushTokenResult {
  success?: boolean;
}

/** 将极光 RegistrationID 绑定到当前登录用户 */
export async function registerPushToken(
  params: RegisterPushTokenParams,
): Promise<RegisterPushTokenResult> {
  try {
    return await post<RegisterPushTokenResult>('/api/v1/push/register', params);
  } catch (e) {
    if (__DEV__) {
      console.warn('[Push API] register skipped (backend not ready)', e);
      return { success: false };
    }
    throw e;
  }
}
