import { hasConversationProactiveHint, type MockConversation } from '@/mock/data';

export type ConversationActor = {
  actorPlatformID: string;
  nickname: string;
  faceURL?: string;
  /** 该 Actor 下是否有未置灰且带红点的会话 */
  hasRedDot?: boolean;
  /** 该 Actor 下是否有未置灰且带黄点（主动触达）的会话 */
  hasProactiveHint?: boolean;
  /** 该 Actor 下是否存在置灰历史会话（右键「删除历史会话」） */
  hasInactive?: boolean;
  /** 该 Actor 下全部会话均为置灰历史（Actor 栏置灰） */
  allInactive?: boolean;
};

type ActorIdSource = Pick<
  MockConversation,
  'actorPlatformID' | 'imConversationID' | 'audiencePlatformID'
>;

/** imConversationID 渠道前缀：si_wecom_{actor}_{audience} 反推时会把 wecom_ 带进 Actor ID */
const ACTOR_CHANNEL_PREFIX_RE = /^(wecom|wechat|weixin|douyin)_/i;

/**
 * 分组用 Actor ID：去掉渠道前缀，避免缓存历史（wecom_xxxx）与活跃会话（xxxx）拆成两条。
 */
export function canonicalActorPlatformId(id: string): string {
  const raw = id.trim();
  if (!raw) return '';
  return raw.replace(ACTOR_CHANNEL_PREFIX_RE, '').trim() || raw;
}

function inferActorIdFromConversation(conv: ActorIdSource): string {
  const im = (conv.imConversationID ?? '').trim();
  const audience = (conv.audiencePlatformID ?? '').trim();
  if (!im || !audience) return '';
  const rest = im.startsWith('si_') ? im.slice(3) : im;
  const suffix = `_${audience}`;
  if (!rest.endsWith(suffix)) return '';
  return rest.slice(0, rest.length - suffix.length).trim();
}

export function conversationActorId(conv: ActorIdSource | null | undefined): string {
  if (!conv) return '';
  const raw = (conv.actorPlatformID ?? '').trim() || inferActorIdFromConversation(conv);
  return canonicalActorPlatformId(raw);
}

function actorDisplayNickname(conv: MockConversation, canonicalId: string): string {
  const nickname = conv.actorPlatformNickname?.trim() || conv.from?.trim() || '';
  if (!nickname) return canonicalId;
  if (canonicalActorPlatformId(nickname) === canonicalId) return canonicalId;
  return nickname;
}

function isRawActorIdLabel(nickname: string, canonicalId: string): boolean {
  const n = nickname.trim();
  if (!n) return true;
  return canonicalActorPlatformId(n) === canonicalId;
}

export function conversationAudienceLabel(conv: MockConversation): string {
  return conv.audiencePlatformNickname?.trim() || conv.to?.trim() || '';
}

export function conversationActorLabel(conv: MockConversation): string {
  return conv.actorPlatformNickname?.trim() || conv.from?.trim() || '';
}

/** 手机端会话列表标题：ActorName → audienceName */
export function conversationPairLabel(conv: MockConversation): string {
  const actor = conversationActorLabel(conv);
  const audience = conversationAudienceLabel(conv);
  if (actor && audience) return `${actor} → ${audience}`;
  return audience || actor || '';
}

/** 从会话列表按 actorPlatformID 去重，顺序跟随会话列表首次出现 */
export function extractConversationActors(
  conversations: MockConversation[],
): ConversationActor[] {
  const seen = new Map<string, ConversationActor>();
  const actors: ConversationActor[] = [];
  for (const c of conversations) {
    const id = conversationActorId(c);
    if (!id) continue;
    const red = !c.inactive && !!c.hasRedDot;
    const yellow = !c.inactive && hasConversationProactiveHint(c);
    const inactive = !!c.inactive;
    const existing = seen.get(id);
    if (existing) {
      if (red) existing.hasRedDot = true;
      if (yellow) existing.hasProactiveHint = true;
      if (inactive) existing.hasInactive = true;
      else existing.allInactive = false;
      const faceURL = c.actorPlatformFaceURL?.trim() || undefined;
      if (faceURL && !existing.faceURL) existing.faceURL = faceURL;
      const nickname = actorDisplayNickname(c, id);
      if (!isRawActorIdLabel(nickname, id) && isRawActorIdLabel(existing.nickname, id)) {
        existing.nickname = nickname;
      }
      continue;
    }
    const nickname = actorDisplayNickname(c, id);
    const faceURL = c.actorPlatformFaceURL?.trim() || undefined;
    const actor: ConversationActor = {
      actorPlatformID: id,
      nickname,
      faceURL,
      hasRedDot: red,
      hasProactiveHint: yellow,
      hasInactive: inactive,
      allInactive: inactive,
    };
    seen.set(id, actor);
    actors.push(actor);
  }
  return actors;
}

export function matchesSelectedActor(
  conv: MockConversation,
  selectedActorPlatformID: string | null,
): boolean {
  if (!selectedActorPlatformID) return true;
  const actorId = conversationActorId(conv);
  if (actorId) return actorId === canonicalActorPlatformId(selectedActorPlatformID);
  // 本地置灰会话可能还没有 actorPlatformID，避免被筛掉
  return !!conv.inactive;
}
