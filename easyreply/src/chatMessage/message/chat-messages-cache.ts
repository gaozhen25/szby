// ============================================================
// 聊天消息本地缓存（按 tenant + role + agentId + imConversationID 隔离）
// - 主管旁观（supervisor=1）禁止读写本模块
// - 活跃会话：接口结果 upsert；失败/离线可读本地
// - 置灰会话：仅读本地，长期保留
// - 同键缓存 tasks/detail 的 task.session，供置灰会话头像/昵称
// ============================================================
import AsyncStorage from '@react-native-async-storage/async-storage';
import type { IMServerMessage, IMTaskSession } from '@/core/im/types';
import { getAgentId, getTenantId } from '@/core/im';
import { getRole } from '@/core/auth';
import { normalizeSendTimeMs, preserveServerMessageForCache } from '@/core/im/utils';

export type ChatMessagesScope = {
  tenantId: string;
  role: 'agent' | 'supervisor';
  agentId: string;
};

type ChatMessagesCacheV1 = {
  version: 1;
  imConversationID: string;
  updatedAt: number;
  messages: IMServerMessage[];
  /** tasks/detail 的 task.session（头像/昵称）；旧缓存可无此字段 */
  session?: IMTaskSession;
};

const KEY_PREFIX = 'chat_messages_v1:';
const FLUSH_DEBOUNCE_MS = 350;
const DEFAULT_PAGE = 10;

const memoryByKey = new Map<string, IMServerMessage[]>();
const sessionByKey = new Map<string, IMTaskSession>();
const pendingWrites = new Map<string, IMServerMessage[]>();
const flushTimers = new Map<string, ReturnType<typeof setTimeout>>();
const flushChains = new Map<string, Promise<void>>();

export function computeChatMessagesScope(): ChatMessagesScope | null {
  const agentId = getAgentId();
  if (!agentId) return null;
  const role = getRole() === 'supervisor' ? 'supervisor' : 'agent';
  return { tenantId: getTenantId(), role, agentId };
}

function storageKey(scope: ChatMessagesScope, imConversationID: string): string {
  return `${KEY_PREFIX}${scope.tenantId}:${scope.role}:${scope.agentId}:${imConversationID}`;
}

function sortBySendTimeAsc(messages: IMServerMessage[]): IMServerMessage[] {
  return [...messages].sort((a, b) => {
    const ta = normalizeSendTimeMs(a.sendTime);
    const tb = normalizeSendTimeMs(b.sendTime);
    if (ta !== tb) return ta - tb;
    return (a.serverMsgID || '').localeCompare(b.serverMsgID || '');
  });
}

/** 轻量校验 tasks/detail 的 session 实体 */
export function normalizeCachedTaskSession(raw: unknown): IMTaskSession | undefined {
  if (!raw || typeof raw !== 'object') return undefined;
  const o = raw as Record<string, unknown>;
  const imConversationID =
    typeof o.imConversationID === 'string' ? o.imConversationID.trim() : '';
  const sessionID = typeof o.sessionID === 'string' ? o.sessionID.trim() : '';
  const actorPlatformID =
    typeof o.actorPlatformID === 'string' ? o.actorPlatformID.trim() : '';
  const audiencePlatformID =
    typeof o.audiencePlatformID === 'string' ? o.audiencePlatformID.trim() : '';
  // 至少要有会话 id 或头像字段之一，才值得落盘
  const audiencePlatformFaceURL =
    typeof o.audiencePlatformFaceURL === 'string' ? o.audiencePlatformFaceURL.trim() : '';
  const actorPlatformFaceURL =
    typeof o.actorPlatformFaceURL === 'string' ? o.actorPlatformFaceURL.trim() : '';
  if (
    !imConversationID &&
    !sessionID &&
    !audiencePlatformFaceURL &&
    !actorPlatformFaceURL
  ) {
    return undefined;
  }
  return {
    sessionID,
    actorPlatformID,
    audiencePlatformID,
    imConversationID,
    lastMessagePreview:
      typeof o.lastMessagePreview === 'string' ? o.lastMessagePreview : undefined,
    status: typeof o.status === 'number' ? o.status : undefined,
    audiencePlatformNickname:
      typeof o.audiencePlatformNickname === 'string'
        ? o.audiencePlatformNickname.trim()
        : undefined,
    audiencePlatformFaceURL: audiencePlatformFaceURL || undefined,
    actorPlatformNickname:
      typeof o.actorPlatformNickname === 'string'
        ? o.actorPlatformNickname.trim()
        : undefined,
    actorPlatformFaceURL: actorPlatformFaceURL || undefined,
  };
}

/** 按 serverMsgID 合并：同 id 覆盖为新内容 */
export function mergeChatMessagesById(
  existing: IMServerMessage[],
  incoming: IMServerMessage[],
): IMServerMessage[] {
  const map = new Map<string, IMServerMessage>();
  for (const m of existing) {
    const id = m.serverMsgID?.trim();
    if (!id) continue;
    map.set(id, preserveServerMessageForCache(m));
  }
  for (const m of incoming) {
    const id = m.serverMsgID?.trim();
    if (!id) continue;
    map.set(id, preserveServerMessageForCache(m));
  }
  return sortBySendTimeAsc([...map.values()]);
}

async function readFromDisk(
  key: string,
): Promise<{ messages: IMServerMessage[]; session?: IMTaskSession }> {
  try {
    const raw = await AsyncStorage.getItem(key);
    if (!raw) return { messages: [] };
    const parsed = JSON.parse(raw) as Partial<ChatMessagesCacheV1> | null;
    if (!parsed || parsed.version !== 1 || !Array.isArray(parsed.messages)) {
      return { messages: [] };
    }
    return {
      messages: sortBySendTimeAsc(
        parsed.messages
          .filter((m) => !!m?.serverMsgID?.trim())
          .map(preserveServerMessageForCache),
      ),
      session: normalizeCachedTaskSession(parsed.session),
    };
  } catch (e) {
    console.warn('[ChatMessagesCache] 读取失败', { key, error: e });
    return { messages: [] };
  }
}

async function writeToDisk(
  scope: ChatMessagesScope,
  imConversationID: string,
  messages: IMServerMessage[],
): Promise<void> {
  const key = storageKey(scope, imConversationID);
  const payload: ChatMessagesCacheV1 = {
    version: 1,
    imConversationID,
    updatedAt: Date.now(),
    messages,
    session: sessionByKey.get(key),
  };
  try {
    await AsyncStorage.setItem(key, JSON.stringify(payload));
  } catch (e) {
    console.warn('[ChatMessagesCache] 写入失败', { key, error: e });
  }
}

function scheduleFlush(scope: ChatMessagesScope, imConversationID: string): void {
  const key = storageKey(scope, imConversationID);
  if (flushTimers.has(key)) return;
  flushTimers.set(
    key,
    setTimeout(() => {
      flushTimers.delete(key);
      const prev = flushChains.get(key) ?? Promise.resolve();
      const next = prev
        .catch(() => undefined)
        .then(async () => {
          const list = pendingWrites.get(key);
          if (!list) return;
          pendingWrites.delete(key);
          await writeToDisk(scope, imConversationID, list);
        });
      flushChains.set(key, next);
    }, FLUSH_DEBOUNCE_MS),
  );
}

async function ensureMemory(
  scope: ChatMessagesScope,
  imConversationID: string,
): Promise<IMServerMessage[]> {
  const key = storageKey(scope, imConversationID);
  const mem = memoryByKey.get(key);
  if (mem) return mem;
  const disk = await readFromDisk(key);
  memoryByKey.set(key, disk.messages);
  if (disk.session) sessionByKey.set(key, disk.session);
  return disk.messages;
}

export type LoadChatMessagesResult = {
  messages: IMServerMessage[];
  hasMoreBefore: boolean;
  /** 同键缓存的 task.session（可能为空：旧数据或尚未 detail） */
  session?: IMTaskSession;
};

function sliceLatestMessages(
  all: IMServerMessage[],
  limit: number,
  session?: IMTaskSession,
): LoadChatMessagesResult {
  if (!all.length) {
    return { messages: [], hasMoreBefore: false, session };
  }
  const start = Math.max(0, all.length - limit);
  return {
    messages: all.slice(start),
    hasMoreBefore: start > 0,
    session,
  };
}

/** 同步读取内存中的最新消息（二次进房首屏，无磁盘 IO） */
export function peekLatestChatMessagesFromMemory(
  imConversationID: string,
  limit = DEFAULT_PAGE,
): LoadChatMessagesResult {
  const im = imConversationID.trim();
  if (!im) return { messages: [], hasMoreBefore: false };
  const scope = computeChatMessagesScope();
  if (!scope) return { messages: [], hasMoreBefore: false };
  const key = storageKey(scope, im);
  const all = memoryByKey.get(key);
  if (!all?.length) return { messages: [], hasMoreBefore: false, session: sessionByKey.get(key) };
  return sliceLatestMessages(all, limit, sessionByKey.get(key));
}

/** 列表点进聊天前预温消息缓存到内存（不阻塞导航） */
export function prefetchChatMessagesToMemory(imConversationID: string): void {
  const im = imConversationID.trim();
  if (!im) return;
  const scope = computeChatMessagesScope();
  if (!scope) return;
  const key = storageKey(scope, im);
  if (memoryByKey.has(key)) return;
  void readFromDisk(key).then((disk) => {
    if (!memoryByKey.has(key)) memoryByKey.set(key, disk.messages);
    if (disk.session && !sessionByKey.has(key)) sessionByKey.set(key, disk.session);
  });
}

/**
 * 写入/更新本地消息（按 serverMsgID upsert）。
 * 返回合并后的全量列表。
 */
export async function upsertChatMessages(
  imConversationID: string,
  incoming: IMServerMessage[],
): Promise<IMServerMessage[]> {
  const im = imConversationID.trim();
  if (!im || !incoming.length) return [];
  const scope = computeChatMessagesScope();
  if (!scope) return [];

  const key = storageKey(scope, im);
  const existing = await ensureMemory(scope, im);
  const merged = mergeChatMessagesById(existing, incoming);
  memoryByKey.set(key, merged);
  pendingWrites.set(key, merged);
  scheduleFlush(scope, im);
  return merged;
}

/**
 * 缓存 tasks/detail 的 task.session（与消息同键持久化）。
 * 活跃进房时写入，置灰进房时读出用于头像/昵称。
 */
export async function upsertChatTaskSession(
  imConversationID: string,
  session: IMTaskSession | null | undefined,
): Promise<void> {
  const im = imConversationID.trim();
  const normalized = normalizeCachedTaskSession(session);
  if (!im || !normalized) return;
  const scope = computeChatMessagesScope();
  if (!scope) return;

  const key = storageKey(scope, im);
  const messages = await ensureMemory(scope, im);
  sessionByKey.set(key, normalized);
  pendingWrites.set(key, messages);
  scheduleFlush(scope, im);
}

/**
 * 取本地最新 limit 条（时间正序，适合首屏）。
 */
export async function loadLatestChatMessages(
  imConversationID: string,
  limit = DEFAULT_PAGE,
): Promise<LoadChatMessagesResult> {
  const im = imConversationID.trim();
  if (!im) return { messages: [], hasMoreBefore: false };
  const scope = computeChatMessagesScope();
  if (!scope) return { messages: [], hasMoreBefore: false };

  const key = storageKey(scope, im);
  const fromMemory = memoryByKey.has(key);
  const all = await ensureMemory(scope, im);
  const session = sessionByKey.get(key);
  if (!all.length) {
    console.log('[ChatMessagesCache] 读出本地聊天历史', {
      imConversationID: im,
      source: fromMemory ? 'memory' : 'disk',
      total: 0,
      limit,
      messages: [],
      session: session ?? null,
    });
    return { messages: [], hasMoreBefore: false, session };
  }
  const sliced = sliceLatestMessages(all, limit, session);
  console.log('[ChatMessagesCache] 读出本地聊天历史', {
    imConversationID: im,
    source: fromMemory ? 'memory' : 'disk',
    total: all.length,
    limit,
    returned: sliced.messages.length,
    hasMoreBefore: sliced.hasMoreBefore,
    messages: sliced.messages,
    session: session ?? null,
  });
  return sliced;
}

/**
 * 以锚点消息向前加载更早的本地消息（不含锚点）。
 */
export async function loadOlderChatMessages(
  imConversationID: string,
  params: { anchorServerMsgID: string; limit?: number },
): Promise<LoadChatMessagesResult> {
  const im = imConversationID.trim();
  const anchorId = params.anchorServerMsgID.trim();
  const limit = params.limit ?? DEFAULT_PAGE;
  if (!im || !anchorId) return { messages: [], hasMoreBefore: false };

  const scope = computeChatMessagesScope();
  if (!scope) return { messages: [], hasMoreBefore: false };

  const all = await ensureMemory(scope, im);
  const session = sessionByKey.get(storageKey(scope, im));
  const idx = all.findIndex((m) => m.serverMsgID === anchorId);
  if (idx <= 0) return { messages: [], hasMoreBefore: false, session };

  const start = Math.max(0, idx - limit);
  return {
    messages: all.slice(start, idx),
    hasMoreBefore: start > 0,
    session,
  };
}

function clearMemoryForKeys(keys: string[]): void {
  for (const key of keys) {
    memoryByKey.delete(key);
    sessionByKey.delete(key);
    pendingWrites.delete(key);
    const timer = flushTimers.get(key);
    if (timer) {
      clearTimeout(timer);
      flushTimers.delete(key);
    }
    flushChains.delete(key);
  }
}

function clearMemoryForPrefix(prefix: string): void {
  clearMemoryForKeys([...memoryByKey.keys()].filter((k) => k.startsWith(prefix)));
}

/**
 * 按 imConversationID 清除指定会话的聊天消息本地缓存（内存 + AsyncStorage）。
 */
export async function clearChatMessagesCacheForConversations(
  imConversationIDs: string[],
  reason = 'manual_clear',
): Promise<number> {
  const scope = computeChatMessagesScope();
  if (!scope) return 0;

  const ids = [...new Set(imConversationIDs.map((id) => id.trim()).filter(Boolean))];
  if (!ids.length) return 0;

  const keys = ids.map((id) => storageKey(scope, id));
  clearMemoryForKeys(keys);

  try {
    await AsyncStorage.removeMany(keys);
    console.log('[ChatMessagesCache] 按会话清空本地缓存', {
      reason,
      scope,
      count: keys.length,
    });
    return keys.length;
  } catch (e) {
    console.warn('[ChatMessagesCache] 按会话清空本地缓存失败', { reason, error: e });
    throw e;
  }
}

/**
 * 清除当前登录态下所有聊天消息本地缓存（内存 + AsyncStorage）。
 * 未登录时清除全部 chat_messages_v1:* 键。
 */
export async function clearAllChatMessagesCache(reason = 'manual_clear'): Promise<void> {
  const scope = computeChatMessagesScope();
  const prefix = scope
    ? `${KEY_PREFIX}${scope.tenantId}:${scope.role}:${scope.agentId}:`
    : KEY_PREFIX;

  clearMemoryForPrefix(prefix);

  try {
    const allKeys = await AsyncStorage.getAllKeys();
    const toRemove = allKeys.filter((k) => k.startsWith(prefix));
    if (toRemove.length) {
      // AsyncStorage v3：批量删除为 removeMany（不再有 multiRemove）
      await AsyncStorage.removeMany(toRemove);
    }
    console.log('[ChatMessagesCache] 清空本地缓存', {
      reason,
      scope,
      count: toRemove.length,
    });
  } catch (e) {
    console.warn('[ChatMessagesCache] 清空本地缓存失败', { reason, error: e });
    throw e;
  }
}
