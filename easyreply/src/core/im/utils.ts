import type { IMTask, IMServerMessage } from './types';

export function generateClientMsgId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}
export function generateRequestId(): string { return `req-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`; }
export function calcBackoffDelay(attempt: number, base: number, max: number): number {
  return Math.min(base * Math.pow(2, attempt), max) * (0.8 + Math.random() * 0.4);
}
export function getMessagePreview(message: { type: string; content: any }): string {
  if (message.type === 'text') return (message.content as any)?.text?.slice(0, 100) ?? '';
  if (message.type === 'image') return '[图片]';
  if (message.type === 'audio') return '[语音]';
  if (message.type === 'video') return '[视频]';
  if (message.type === 'file') return '[文件]';
  if (message.type === 'location') return '[位置]';
  return '[消息]';
}

/**
 * 解析接口返回的 message.content。
 * 后端可能返回 JSON 字符串，例如 "{\"content\":\"你好\"}"，需二次解析取展示文本。
 *
 * 只认 JSON 对象：数组形态没有可取的展示字段，反而会把 [666]、[] 这类
 * 恰好是合法 JSON 的微信表情 token / 普通文本解析掉，String() 后丢失方括号。
 */
export function parseApiMessageContent(raw: unknown): string {
  if (raw == null) return '';
  if (typeof raw === 'string') {
    const trimmed = raw.trim();
    if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
      try {
        return parseApiMessageContent(JSON.parse(trimmed));
      } catch {
        return raw;
      }
    }
    return raw;
  }
  if (typeof raw === 'object') {
    const o = raw as Record<string, unknown>;
    if (typeof o.content === 'string') return parseApiMessageContent(o.content);
    if (typeof o.text === 'string') return o.text;
    if (typeof o.echo === 'string') return o.echo;
  }
  return String(raw);
}

/**
 * 将 sendTime 统一为毫秒。
 * 后端可能返回毫秒（13 位，如 1782725982959）或微秒（16 位，如 1782726449000000）。
 */
export function normalizeSendTimeMs(sendTime: number): number {
  if (!sendTime || !Number.isFinite(sendTime)) return Date.now();
  if (sendTime >= 1e14) return Math.floor(sendTime / 1000);
  if (sendTime < 1e11) return sendTime * 1000;
  return sendTime;
}

/** 规范化单条服务端消息（解析 content 为可展示文本，sendTime 转毫秒） */
export function normalizeServerMessage(msg: IMServerMessage): IMServerMessage {
  // contentType=101 为文本；102 等非文本（图片/表情等）content 往往是 JSON 字符串，需要保留原始字符串给 UI 再解析
  const normalizedContent =
    msg.contentType == null || msg.contentType === 101
      ? parseApiMessageContent(msg.content)
      : msg.content;
  return {
    ...msg,
    content: normalizedContent,
    sendTime: normalizeSendTimeMs(msg.sendTime),
  };
}

/** 批量规范化服务端消息 */
export function normalizeServerMessages(msgs: IMServerMessage[]): IMServerMessage[] {
  return msgs.map(normalizeServerMessage);
}

/** 消息是否为我方发出（direction=1；兼容旧 senderPlatformID 字段） */
export function isOutgoingServerMessage(
  msg: IMServerMessage,
  actorPlatformID?: string,
): boolean {
  if (typeof msg.direction === 'number') return msg.direction === 1;
  if (msg.senderPlatformID && actorPlatformID) return msg.senderPlatformID === actorPlatformID;
  return msg.senderPlatformID === 'agent';
}

/** 会话列表的预览文案格式化（图片/表情 JSON → [图片]，语音 → [语音]，视频 → [视频]，文件 → [文件]） */
export function formatLastMessagePreview(raw?: string): string {
  const s = (raw ?? '').trim();
  if (!s) return '';

  // 文件：优先于通用 sourceUrl（语音也有 sourceUrl）
  if (
    s.includes('edge/file/')
    || (s.includes('"fileName"') && s.includes('"fileSize"'))
  ) {
    return '[文件]';
  }

  // 视频：优先于 snapshotUrl / edge/image 封面图
  if (
    s.includes('"videoUrl"')
    || s.includes('edge/video/')
    || s.includes('"videoType"')
  ) {
    return '[视频]';
  }

  // 明确是图片/表情 JSON（即使被截断也能识别）
  if (s.includes('"bigPicture"') || s.includes('"snapshotPicture"') || s.includes('edge/image/') || s.includes('edge/emoji/')) {
    if (s.includes('"sourceUrl"') || s.includes('edge/voice/')) {
      return '[语音]';
    }
    return '[图片]';
  }
  if (
    s.includes('"sourceUrl"')
    || s.includes('edge/voice/')
    || s.includes('"dataSize"') && s.includes('"duration"') && s.includes('"uuid"')
  ) {
    return '[语音]';
  }

  // 兼容完整 JSON：{"content":"xxx"} 之类。同 parseApiMessageContent，只认对象，
  // 否则表情 token [666] 会被当成 JSON 数组解析掉
  if (s.startsWith('{') && s.endsWith('}')) {
    try {
      const parsed = JSON.parse(s);
      if (parsed && typeof parsed === 'object') {
        if ('fileName' in parsed && ('fileSize' in parsed || 'sourceUrl' in parsed)) {
          return '[文件]';
        }
        if ('videoUrl' in parsed || 'videoType' in parsed) {
          return '[视频]';
        }
        if ('sourceUrl' in parsed || 'dataSize' in parsed) {
          return '[语音]';
        }
        if ('bigPicture' in parsed || 'snapshotPicture' in parsed || 'sourcePicture' in parsed) {
          return '[图片]';
        }
        if (
          'latitude' in parsed &&
          'longitude' in parsed &&
          Number.isFinite(Number((parsed as { latitude?: unknown }).latitude)) &&
          Number.isFinite(Number((parsed as { longitude?: unknown }).longitude))
        ) {
          return '[位置]';
        }
      }
      return parseApiMessageContent(parsed);
    } catch {
      // fallthrough
    }
  }

  return parseApiMessageContent(s);
}

/** 缓存/列表用：保留接口原始消息全部字段（不解析 content） */
export function preserveServerMessageForCache(msg: IMServerMessage): IMServerMessage {
  return { ...msg };
}

/** 把 task.messages 规范化并派生 lastMessage（取末位；保留原始 message 字段） */
export function withTaskLastMessage(task: IMTask): IMTask {
  const messages = (task.messages ?? []).map(preserveServerMessageForCache);
  return {
    ...task,
    messages,
    lastMessage: messages.length > 0 ? messages[messages.length - 1] : undefined,
  };
}

/** 取任务的最后一条消息：优先 lastMessage，其次 messages 数组末位 */
export function getTaskLastMessage(task: IMTask): IMServerMessage | undefined {
  if (task.lastMessage) return task.lastMessage;
  const list = task.messages;
  if (Array.isArray(list) && list.length > 0) return list[list.length - 1];
  return undefined;
}

/** 从服务端消息生成会话列表预览文案（图片走 [图片]，语音走 [语音]，视频走 [视频]，文件走 [文件]，文本解析 content） */
export function previewFromServerMessage(msg: IMServerMessage): string {
  if (msg.contentType === 102) return '[图片]';
  if (msg.contentType === 103) return '[语音]';
  if (msg.contentType === 104) return '[视频]';
  if (msg.contentType === 105) return '[文件]';
  if (msg.contentType === 109) return '[位置]';
  return formatLastMessagePreview(msg.content) || '[消息]';
}

/** 从任务实体提取展示用会话信息（优先 session 嵌套字段） */
export function getTaskSessionInfo(task: IMTask) {
  const s = task.session;
  const imConversationID = s?.imConversationID || task.imConversationID || '';
  const audiencePlatformID = s?.audiencePlatformID || task.audiencePlatformID || '';
  // 最后一条消息取自 lastMessage / messages
  const lastMessage = getTaskLastMessage(task);
  const lastMessagePreview = lastMessage ? previewFromServerMessage(lastMessage) : '';
  const lastMessageTime = lastMessage ? normalizeSendTimeMs(lastMessage.sendTime) : undefined;
  return {
    imConversationID,
    actorPlatformID: s?.actorPlatformID || task.actorPlatformID || '',
    audiencePlatformID,
    actorName: s?.actorPlatformNickname || task.actorPlatformID || '教练',
    audienceName: s?.audiencePlatformNickname || task.audiencePlatformID || '学员',
    actorAvatar: s?.actorPlatformFaceURL,
    audienceAvatar: s?.audiencePlatformFaceURL,
    lastMessagePreview,
    lastMessageTime,
  };
}

/** 根据 imConversationID 推断平台 */
export function detectChatPlatform(imConversationID: string, audiencePlatformID = ''): '微信' | '抖音' {
  const id = `${imConversationID}${audiencePlatformID}`.toLowerCase();
  if (id.includes('douyin')) return '抖音';
  return '微信';
}

/**
 * 解析 Audience 备注接口所需的 platform 字段。
 * 优先用服务端原始 platform；否则从 imConversationID / audiencePlatformID 推断。
 */
export function resolveAudienceApiPlatform(opts: {
  platform?: string;
  imConversationID?: string;
  audiencePlatformID?: string;
}): string {
  const raw = (opts.platform ?? '').trim().toLowerCase();
  if (raw === 'wecom' || raw === 'wechat' || raw === 'douyin') return raw;
  if (raw === 'weixin' || raw === '微信') return 'wechat';
  if (raw === '抖音') return 'douyin';
  if (raw.includes('wecom')) return 'wecom';
  if (raw.includes('douyin')) return 'douyin';
  if (raw.includes('wechat') || raw.includes('weixin')) return 'wechat';

  const id = `${opts.imConversationID ?? ''}${opts.audiencePlatformID ?? ''}`.toLowerCase();
  if (id.includes('wecom')) return 'wecom';
  if (id.includes('douyin')) return 'douyin';
  if (id.includes('wechat') || id.includes('weixin')) return 'wechat';
  return 'wechat';
}

// ============================================================
// 联调日志：每个节点统一打印「中文描述 + socket 原始参数」
// scope 用于区分节点所在层（传输层 / 连接层 / 会话层等）
// ============================================================
function safeStringify(raw: unknown): string {
  if (typeof raw === 'string') return raw;
  try { return JSON.stringify(raw); } catch { return String(raw); }
}

export function imLog(scope: string, description: string, raw?: unknown): void {
  const tag = `[IM][${scope}] ${description}`;
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { logWs } = require('@/core/logging') as typeof import('@/core/logging');
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { safeJson } = require('@/core/logging/format') as typeof import('@/core/logging/format');
    // 控制台与落盘都走摘要，避免 base64 / 长 URL 刷屏
    if (raw === undefined) console.log(tag);
    else console.log(`${tag} | ${safeJson(raw)}`);
    logWs(scope, description, raw);
  } catch {
    if (raw === undefined) console.log(tag);
    else console.log(`${tag} | socket原始参数: ${safeStringify(raw)}`);
  }
  console.log('\n\n');
}

export function imWarn(scope: string, description: string, raw?: unknown): void {
  const tag = `[IM][${scope}] ${description}`;
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { logWs } = require('@/core/logging') as typeof import('@/core/logging');
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { safeJson } = require('@/core/logging/format') as typeof import('@/core/logging/format');
    if (raw === undefined) console.warn(tag);
    else console.warn(`${tag} | ${safeJson(raw)}`);
    logWs(scope, `WARN ${description}`, raw);
  } catch {
    if (raw === undefined) console.warn(tag);
    else console.warn(`${tag} | socket原始参数: ${safeStringify(raw)}`);
  }
}

/**
 * IM 异常上报 Sentry（同时打 imWarn）。
 * 仅用于真正异常，不要用在正常断线重连路径上。
 */
export function imCaptureError(
  scope: string,
  event: string,
  error: unknown,
  extra?: Record<string, unknown>,
): void {
  imWarn(scope, event, extra ?? { error: String(error) });
  // 延迟 require，避免 im ↔ sentry 启动期循环依赖
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { captureWsError } = require('@/core/sentry') as typeof import('@/core/sentry');
    captureWsError(error, {
      scope,
      event,
      code: typeof extra?.code === 'string' || typeof extra?.code === 'number' ? extra.code : undefined,
      extra,
    });
  } catch {
    /* Sentry 模块不可用时忽略 */
  }
}

/** 生成会话 ID（联调阶段随意填写，建议复用以支持断线恢复） */
export function generateSessionId(): string {
  return `sess-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}
