// ============================================================
// AI 自动回复窗口：对方发来消息后先留给 AI 应答（90s 提示，不锁输入）
// ============================================================

import type { DisplayMessage } from '@/chatMessage/message/chat-message-model';

/** 对方消息进来后留给 AI 自动回复的时长 */
export const AI_REPLY_WINDOW_MS = 90 * 1000;

/**
 * 末条消息由对方发出时返回其发送时间（ms），否则返回 null。
 * AI 代发的回复同样是我方消息（direction=1），因此 AI 一回复窗口即结束。
 */
export function lastAudienceMessageTime(messages: DisplayMessage[]): number | null {
  const last = messages[messages.length - 1];
  if (!last || last.mine) return null;
  if (!Number.isFinite(last.time) || last.time <= 0) return null;
  return last.time;
}

/**
 * 由末条对方消息时间推导窗口截止时间（ms）；已过窗口返回 null。
 * 服务端 sendTime 超前本地时钟时也最多只等一个完整窗口。
 */
export function aiReplyWindowEndAt(
  lastAudienceTime: number | null,
  now = Date.now(),
): number | null {
  if (lastAudienceTime == null) return null;
  const endAt = Math.min(lastAudienceTime + AI_REPLY_WINDOW_MS, now + AI_REPLY_WINDOW_MS);
  return endAt > now ? endAt : null;
}

// ---- 人工复审释放的窗口水位 ----
// 复审「确定 / 已处理」后本轮窗口立即结束；记下被释放的对方消息时间，
// 退出重进会话时同一条消息不再重新开窗（更晚的新消息仍会正常开窗）。
// 只需进程内存活：窗口本身仅 90s，冷启动后旧消息早已过窗。
const releasedAudienceTimeByTask = new Map<string, number>();
const RELEASE_KEEP_MS = 10 * 60 * 1000;

export function releaseAiReplyWindow(taskID: string, lastAudienceTime?: number | null): void {
  const key = taskID?.trim();
  if (!key) return;
  const now = Date.now();
  for (const [k, v] of releasedAudienceTimeByTask) {
    if (now - v > RELEASE_KEEP_MS) releasedAudienceTimeByTask.delete(k);
  }
  const watermark = lastAudienceTime != null && lastAudienceTime > 0 ? lastAudienceTime : now;
  const prev = releasedAudienceTimeByTask.get(key);
  releasedAudienceTimeByTask.set(key, prev != null ? Math.max(prev, watermark) : watermark);
}

/** 该条对方消息是否已被人工复审释放（不再开窗） */
export function isAiReplyWindowReleased(taskID: string, lastAudienceTime: number): boolean {
  const released = releasedAudienceTimeByTask.get(taskID?.trim() || '');
  return released != null && lastAudienceTime <= released;
}

/** 剩余时间文案，形如 `2:05` */
export function formatAiReplyRemaining(endAt: number, now = Date.now()): string {
  const totalSec = Math.max(0, Math.ceil((endAt - now) / 1000));
  const min = Math.floor(totalSec / 60);
  const sec = totalSec % 60;
  return `${min}:${String(sec).padStart(2, '0')}`;
}

/** 剩余秒数文案，形如 `90s`（倒计时写在「约Ns」上） */
export function formatAiReplyRemainingSeconds(endAt: number, now = Date.now()): string {
  const totalSec = Math.max(0, Math.ceil((endAt - now) / 1000));
  return `${totalSec}s`;
}
