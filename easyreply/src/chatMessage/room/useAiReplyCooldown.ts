import { useCallback, useEffect, useRef, useState } from 'react';
import {
  aiReplyWindowEndAt,
  isAiReplyWindowReleased,
  lastAudienceMessageTime,
  releaseAiReplyWindow,
} from '@/chatMessage/message/ai-reply-window';
import type { DisplayMessage } from '@/chatMessage/message/chat-message-model';

/**
 * 进房 / 收到新消息时按末条消息推导 AI 自动回复窗口（仅 labor 技能组开启）：
 * 末条来自对方且未满 90s 则返回窗口截止时间（ms），期间展示提示倒计时（不锁输入）；
 * 窗口结束、AI 已回复（末条变成我方消息）、或人工复审已处理则返回 null。
 *
 * 返回值只在窗口开始 / 结束时变化，秒级刷新由提示条上的倒计时组件自己做，
 * 避免整个聊天页每秒重渲染消息列表。
 */
export function useAiReplyCooldown(opts: {
  taskID: string;
  messages: DisplayMessage[];
  enabled: boolean;
}): { endAt: number | null; release: () => void } {
  const { taskID, messages, enabled } = opts;
  const audienceTime = enabled ? lastAudienceMessageTime(messages) : null;
  // 已被复审释放的消息不再开窗，退出重进也不会又锁 90s
  const lastAudienceTime =
    audienceTime != null && isAiReplyWindowReleased(taskID, audienceTime) ? null : audienceTime;
  const [endAt, setEndAt] = useState<number | null>(null);

  const audienceTimeRef = useRef(audienceTime);
  audienceTimeRef.current = audienceTime;

  useEffect(() => {
    const target = aiReplyWindowEndAt(lastAudienceTime);
    setEndAt(target);
    if (target == null) return;
    const timer = setTimeout(() => setEndAt(null), Math.max(0, target - Date.now()));
    return () => clearTimeout(timer);
  }, [lastAudienceTime]);

  /** 复审「确定 / 已处理」后立即结束本轮窗口 */
  const release = useCallback(() => {
    releaseAiReplyWindow(taskID, audienceTimeRef.current);
    setEndAt(null);
  }, [taskID]);

  return { endAt, release };
}
