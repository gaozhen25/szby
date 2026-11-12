// ============================================================
// 聊天页输入区门禁状态（单一真相）
// 优先级：supervisor_browse > unavailable > locked / ai_mode / ready
// ai_reply_cooldown 只在 labor 技能组的 ready 之上按消息时间派生，不写入会话状态
// ============================================================
import type { TaskMode } from '@/core/im/types';

/** 劳务技能组（task.skillGroup）：等同 AI 托管，且不允许人工切换 */
export const LABOR_SKILL_GROUP = 'labor';

export function isLaborSkillGroup(skillGroup: string | null | undefined): boolean {
  return skillGroup === LABOR_SKILL_GROUP;
}

/** 派生门禁所需的任务模式信息 */
export type ChatTaskModeContext = {
  taskMode?: TaskMode | null;
  /** task.skillGroup（labor 等同 AI 托管） */
  skillGroup?: string | null;
};

/** 输入区统一门禁，避免 canSend / lockHint / sessionUnavailable 多状态打架 */
export type ChatInputGate =
  /** 可人工发送 */
  | { phase: 'ready' }
  /** AI 托管：上方「当前为AI模式」，占位同文案，不可发送；可叠复审条 */
  | { phase: 'ai_mode' }
  /**
   * AI 自动回复窗口内（仅 labor 技能组）：可发送，仅展示提示 + 倒计时，
   * 到期自动回到 ready（不锁定输入）
   */
  | { phase: 'ai_reply_cooldown'; endAt: number }
  /** 主管旁观：仅「主管查看模式，仅可浏览」，占位「当前不可发送」 */
  | { phase: 'supervisor_browse' }
  /** 任务回收 / 非本人：无任何上方提示，占位「当前会话不可用」，隐藏「...」 */
  | { phase: 'unavailable' }
  /** 其它业务锁定（转交、结束等）；hideMoreMenu=true 时隐藏右上角「...」 */
  | { phase: 'locked'; reason: string; hideMoreMenu?: boolean };

/** ready 与 AI 自动回复提示窗口内均可人工发送 */
export function isChatInputOpen(gate: ChatInputGate): boolean {
  return gate.phase === 'ready' || gate.phase === 'ai_reply_cooldown';
}

/** 是否允许切换到 AI/人工模式门禁（旁观、不可用、主管接管锁定保持不动） */
export function canApplyTaskModeGate(gate: ChatInputGate): boolean {
  if (gate.phase === 'supervisor_browse' || gate.phase === 'unavailable') return false;
  // 被主管接管等：隐藏菜单的 locked 不应被 taskMode 结果冲掉
  if (gate.phase === 'locked' && gate.hideMoreMenu) return false;
  return true;
}

/**
 * 归属自己且活跃时的门禁。
 * labor 技能组虽等同 AI 托管，但不进常驻 ai_mode：窗口期仅提示倒计时、不锁输入
 * （见 useAiReplyCooldown），窗口结束或复审处理完提示消失。
 */
export function gateForOwnedActive(ctx: ChatTaskModeContext): ChatInputGate {
  if (isLaborSkillGroup(ctx.skillGroup)) return { phase: 'ready' };
  return ctx.taskMode === 'ai_assisted' ? { phase: 'ai_mode' } : { phase: 'ready' };
}

export function gateAfterTaskMode(gate: ChatInputGate, ctx: ChatTaskModeContext): ChatInputGate {
  if (!canApplyTaskModeGate(gate)) return gate;
  return gateForOwnedActive(ctx);
}

/** 会话缓存中与「归属/置灰」相关的标记（MockConversation 的结构子集） */
export type ConversationGateFlags = {
  inactive?: boolean;
  returnedToAgent?: boolean;
  supervisorTakeover?: boolean;
};

/** 归属自己且活跃：未置灰且无归还 / 被接管标记 */
export function isConversationOwnedAndActive<T extends ConversationGateFlags>(
  conv: T | null | undefined,
): conv is T {
  return !!conv && !conv.inactive && !conv.returnedToAgent && !conv.supervisorTakeover;
}

/** 置灰会话的锁定原因 → 门禁（归还 / 被接管 / 普通置灰历史） */
export function inactiveConversationGate(conv: ConversationGateFlags): ChatInputGate {
  if (conv.returnedToAgent) {
    return { phase: 'locked', reason: '已归还给原客服', hideMoreMenu: true };
  }
  if (conv.supervisorTakeover) {
    return { phase: 'locked', reason: '会话已被主管接管，暂不可发送', hideMoreMenu: true };
  }
  // 置灰历史会话：不可操作，隐藏「...」
  return { phase: 'unavailable' };
}

/**
 * 仅凭本地会话缓存派生门禁（不调 tasks/detail）。
 * 返回 null 表示「归属自己且活跃」，需由调用方走 detail 校准。
 * clearHints=true 的分支需同时清空复审上下文 / 主动提示。
 */
export function gateFromConversation(
  conv: ConversationGateFlags | null | undefined,
  opts: { isSupervisorView: boolean },
): { gate: ChatInputGate; clearHints: boolean } | null {
  if (opts.isSupervisorView) {
    return { gate: { phase: 'supervisor_browse' }, clearHints: false };
  }
  if (!conv) return { gate: { phase: 'unavailable' }, clearHints: false };
  if (conv.inactive) return { gate: inactiveConversationGate(conv), clearHints: false };
  if (conv.returnedToAgent || conv.supervisorTakeover) {
    return { gate: inactiveConversationGate(conv), clearHints: true };
  }
  return null;
}

export type ChatInputUi = {
  inputEnabled: boolean;
  inputPlaceholder: string;
  bannerHint: string | null;
  /** 非空时提示条在 bannerHint 之后追加一个每秒自刷新的倒计时 */
  bannerCountdownEndAt: number | null;
  showMoreMenu: boolean;
  allowAdoptionReview: boolean;
};

/**
 * labor 技能组等同 AI 托管：ready / 倒计时状态下同样允许展示复审条，
 * 否则窗口内点不到「去处理」，复审也就无从提交。
 */
export function deriveChatInputUi(
  gate: ChatInputGate,
  opts: { laborSkillGroup?: boolean } = {},
): ChatInputUi {
  const ui = chatInputUiForGate(gate);
  if (
    opts.laborSkillGroup &&
    !ui.allowAdoptionReview &&
    (gate.phase === 'ready' || gate.phase === 'ai_reply_cooldown')
  ) {
    return { ...ui, allowAdoptionReview: true };
  }
  return ui;
}

function chatInputUiForGate(gate: ChatInputGate): ChatInputUi {
  switch (gate.phase) {
    case 'ready':
      return {
        inputEnabled: true,
        inputPlaceholder: '输入消息...',
        bannerHint: null,
        bannerCountdownEndAt: null,
        showMoreMenu: true,
        allowAdoptionReview: false,
      };
    case 'ai_mode':
      return {
        inputEnabled: false,
        inputPlaceholder: '当前为AI模式',
        bannerHint: '当前为AI模式',
        bannerCountdownEndAt: null,
        showMoreMenu: true,
        allowAdoptionReview: true,
      };
    case 'ai_reply_cooldown':
      return {
        inputEnabled: true,
        inputPlaceholder: '输入消息...',
        bannerHint: 'AI自动回复中 ',
        bannerCountdownEndAt: gate.endAt,
        showMoreMenu: true,
        allowAdoptionReview: false,
      };
    case 'supervisor_browse':
      return {
        inputEnabled: false,
        inputPlaceholder: '当前不可发送',
        bannerHint: '主管查看模式，仅可浏览',
        bannerCountdownEndAt: null,
        showMoreMenu: true,
        allowAdoptionReview: false,
      };
    case 'unavailable':
      return {
        inputEnabled: false,
        inputPlaceholder: '当前会话不可用',
        bannerHint: null,
        bannerCountdownEndAt: null,
        showMoreMenu: false,
        allowAdoptionReview: false,
      };
    case 'locked':
      return {
        inputEnabled: false,
        inputPlaceholder: '当前不可发送',
        bannerHint: gate.reason,
        bannerCountdownEndAt: null,
        showMoreMenu: !gate.hideMoreMenu,
        allowAdoptionReview: false,
      };
  }
}
