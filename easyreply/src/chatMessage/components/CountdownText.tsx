import { useEffect, useState } from 'react';
import { Text, type StyleProp, type TextStyle } from 'react-native';
import {
  formatAiReplyRemaining,
  formatAiReplyRemainingSeconds,
} from '@/chatMessage/message/ai-reply-window';

/** 每 500ms 重算一次，文案不变时 React 自动跳过重渲染 */
const TICK_MS = 500;

export type CountdownFormat = 'mmss' | 'seconds';

function formatLabel(endAt: number, format: CountdownFormat): string {
  return format === 'seconds'
    ? formatAiReplyRemainingSeconds(endAt)
    : formatAiReplyRemaining(endAt);
}

/** 倒计时文案；自带定时器，避免把秒级刷新扩散到整个聊天页 */
export function CountdownText({
  endAt,
  style,
  format = 'mmss',
}: {
  endAt: number;
  style?: StyleProp<TextStyle>;
  /** mmss → `2:05`；seconds → `90s`（接在「约」后面） */
  format?: CountdownFormat;
}) {
  const [label, setLabel] = useState(() => formatLabel(endAt, format));

  useEffect(() => {
    setLabel(formatLabel(endAt, format));
    const timer = setInterval(() => setLabel(formatLabel(endAt, format)), TICK_MS);
    return () => clearInterval(timer);
  }, [endAt, format]);

  return <Text style={style}>{label}</Text>;
}
