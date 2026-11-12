import { useEffect, useState } from 'react';
import { getUserInfo, subscribeUserInfo } from '@/core/auth';

/** 会话列表上限：来自 /api/app/auth/me 的 max_active_cap */
export function readMaxActiveCap(): number | null {
  const cap = getUserInfo()?.max_active_cap;
  return typeof cap === 'number' && Number.isFinite(cap) && cap >= 0 ? Math.floor(cap) : null;
}

/** 会话列表副标题：当前持有数 / me.max_active_cap */
export function formatConversationCountLabel(
  claimedCount: number,
  maxActiveCap: number | null = readMaxActiveCap(),
): string {
  if (maxActiveCap == null) return `会话数量 ${claimedCount}`;
  return `会话数量 ${claimedCount}/${maxActiveCap}`;
}

/** me 刷新后同步会话上限，避免列表副标题停留在登录缓存 */
export function useMaxActiveCap(): number | null {
  const [cap, setCap] = useState(readMaxActiveCap);
  useEffect(() => subscribeUserInfo(() => setCap(readMaxActiveCap())), []);
  return cap;
}
