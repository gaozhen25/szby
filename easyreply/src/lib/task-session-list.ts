// ============================================================
// 任务会话列表：排序、时间格式化、行数据映射（客服 / 主管共用）
// ============================================================
import type { ChatPlatform, MockConversation } from '@/mock/data';
import { detectChatPlatform, getTaskLastMessage, getTaskSessionInfo, normalizeSendTimeMs } from '@/core/im';
import type { IMTask } from '@/core/im/types';

export const TASK_AVATAR_PALETTE = ['#7FB0D8', '#E8A598', '#B8A8E8', '#E8A0B0', '#E8D4A0'];

export interface TaskSessionRow {
  id: string;
  from: string;
  to: string;
  platform: ChatPlatform;
  time: string;
  avatarColor: string;
  /** 学员/对方头像 */
  audiencePlatformFaceURL?: string;
  /** 学员/对方平台昵称（头像兜底首字） */
  audiencePlatformNickname?: string;
}

function pad2(n: number): string {
  return n.toString().padStart(2, '0');
}

function startOfLocalDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

const WEEKDAY_LABELS = ['星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六'] as const;

/** 当天/昨天/前天带 HH:mm；三天前及更早仅显示日期或星期（会话列表） */
export function formatTaskTriggerTime(
  ts?: number,
  opts?: { /** 聊天页：3～7 天 / 更早日期后追加 HH:mm */ withClockForOlder?: boolean },
): string {
  if (ts == null || ts === 0 || !Number.isFinite(ts)) return '';
  const d = new Date(normalizeSendTimeMs(ts));
  if (Number.isNaN(d.getTime())) return '';

  const hhmm = `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
  const withClock = !!opts?.withClockForOlder;
  const dayMs = 24 * 60 * 60 * 1000;
  const now = new Date();
  const diffDays = Math.floor((startOfLocalDay(now) - startOfLocalDay(d)) / dayMs);

  if (diffDays <= 0) return hhmm;
  if (diffDays === 1) return `昨天 ${hhmm}`;
  if (diffDays === 2) return `前天 ${hhmm}`;
  if (diffDays >= 3 && diffDays <= 7) {
    const weekday = WEEKDAY_LABELS[d.getDay()];
    return withClock ? `${weekday} ${hhmm}` : weekday;
  }

  const dateLabel =
    d.getFullYear() !== now.getFullYear()
      ? `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`
      : `${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
  return withClock ? `${dateLabel} ${hhmm}` : dateLabel;
}

/** 完整时间：YYYY-MM-DD HH:mm:ss */
export function formatTaskTriggerTimeFull(ts?: number): string {
  if (ts == null || ts === 0 || !Number.isFinite(ts)) return '';
  const d = new Date(normalizeSendTimeMs(ts));
  if (Number.isNaN(d.getTime())) return '';
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} ${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
}

function getSortableTriggerTime(task: IMTask): number | null {
  const t = getTaskLastMessage(task)?.sendTime;
  if (t == null || t === 0 || !Number.isFinite(t)) return null;
  const ms = normalizeSendTimeMs(t);
  return ms > 0 ? ms : null;
}

/** 按最后一条消息时间倒序；值为 0 或无效的排在最后 */
export function sortTasksByLastTriggerMsgTime(tasks: IMTask[]): IMTask[] {
  return [...tasks].sort((a, b) => {
    const ta = getSortableTriggerTime(a);
    const tb = getSortableTriggerTime(b);
    if (ta == null && tb == null) return 0;
    if (ta == null) return 1;
    if (tb == null) return -1;
    return tb - ta;
  });
}

export function taskToSessionRow(task: IMTask, idx: number): TaskSessionRow {
  const info = getTaskSessionInfo(task);
  const platform: ChatPlatform = detectChatPlatform(info.imConversationID, info.audiencePlatformID);
  return {
    id: (task.taskID ?? '').trim(),
    from: info.actorName,
    to: info.audienceName,
    platform,
    time: formatTaskTriggerTime(info.lastMessageTime),
    avatarColor: TASK_AVATAR_PALETTE[idx % TASK_AVATAR_PALETTE.length],
    audiencePlatformFaceURL: info.audienceAvatar?.trim() || undefined,
    audiencePlatformNickname: task.session?.audiencePlatformNickname?.trim() || info.audienceName || '',
  };
}

/**
 * 依据 claimed/list 的 messages 判断红点（无本地水位时）：
 * 取 messages 末条，direction=0（学员进）→ 有红点；direction=1（我方出）→ 无红点。
 * 合并进本地缓存时须结合 redDotAckServerMsgID，见 resolveConversationHasRedDot。
 */
export function hasRedDotFromTaskMessages(task: IMTask): boolean {
  const last = getTaskLastMessage(task);
  return last?.direction === 0;
}

/** 归一化 list/detail 的 taskMode（兼容历史值 ai → ai_assisted） */
export function normalizeTaskMode(mode: unknown): 'human' | 'ai_assisted' | undefined {
  if (mode === 'human') return 'human';
  if (mode === 'ai_assisted' || mode === 'ai') return 'ai_assisted';
  return undefined;
}

/** 可选扩展：主管接管写入时附带被接管客服信息 */
export type ConversationMapMeta = {
  fromAgentId?: string;
  fromAgentAccount?: string;
};

/** IMTask → MockConversation（会话列表数据源映射，客服 / 主管共用） */
export function taskToConversation(
  task: IMTask,
  idx: number,
  meta?: ConversationMapMeta,
): MockConversation {
  const row = taskToSessionRow(task, idx);
  const info = getTaskSessionInfo(task);
  const lastMessage = getTaskLastMessage(task);
  const actorNickname = task.session?.actorPlatformNickname?.trim() || '';
  const audienceNickname = task.session?.audiencePlatformNickname?.trim() || '';
  const adoption =
    task.adoptionContext &&
    Array.isArray(task.adoptionContext.candidates) &&
    task.adoptionContext.candidates.length > 0
      ? task.adoptionContext
      : undefined;
  const base: MockConversation = {
    ...row,
    preview: info.lastMessagePreview,
    unread: 0,
    categoryId: task.skillGroupID || 'all',
    imConversationID: info.imConversationID,
    lastMessage,
    inactive: false,
    hasRedDot: hasRedDotFromTaskMessages(task),
    actorPlatformID: info.actorPlatformID?.trim() || undefined,
    actorPlatformNickname: actorNickname,
    actorPlatformFaceURL: info.actorAvatar?.trim() || undefined,
    audiencePlatformNickname: audienceNickname,
    audiencePlatformFaceURL: info.audienceAvatar?.trim() || undefined,
    audiencePlatformID: info.audiencePlatformID?.trim() || undefined,
    taskMode: normalizeTaskMode(task.taskMode),
    skillGroup: task.skillGroup?.trim() || undefined,
    ...(adoption ? { adoptionContext: adoption } : null),
  };
  if (!meta) return base;
  return {
    ...base,
    fromAgentId: meta.fromAgentId,
    fromAgentAccount: meta.fromAgentAccount,
    returnedToAgent: false,
  };
}
