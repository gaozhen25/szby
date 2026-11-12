import { getChatApiBaseUrl } from '@/lib/api-host';

/** 后台通知 / 原生模块用的绝对头像地址 */
export function resolvePushAvatarUrl(url?: string): string | undefined {
  const raw = url?.trim();
  if (!raw) return undefined;
  if (/^(https?:|data:|file:)/i.test(raw)) return raw;
  try {
    return new URL(raw, getChatApiBaseUrl()).href;
  } catch {
    return raw.startsWith('/') ? `${getChatApiBaseUrl()}${raw}` : raw;
  }
}
