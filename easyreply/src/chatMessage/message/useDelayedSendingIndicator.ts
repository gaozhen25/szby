import { useEffect, useState } from 'react';

export const SENDING_INDICATOR_DELAY_MS = 3000;

/** 发送中指示：前 delayMs 不展示，超时仍未成功再显示 */
export function useDelayedSendingIndicator(
  status: 'sending' | 'sent' | 'failed' | undefined,
  sendTimeMs: number,
  delayMs = SENDING_INDICATOR_DELAY_MS,
): boolean {
  const [visible, setVisible] = useState(() => {
    if (status !== 'sending') return false;
    return Date.now() - sendTimeMs >= delayMs;
  });

  useEffect(() => {
    if (status !== 'sending') {
      setVisible(false);
      return;
    }
    const elapsed = Date.now() - sendTimeMs;
    const remaining = delayMs - elapsed;
    if (remaining <= 0) {
      setVisible(true);
      return;
    }
    setVisible(false);
    const timer = setTimeout(() => setVisible(true), remaining);
    return () => clearTimeout(timer);
  }, [status, sendTimeMs, delayMs]);

  return visible;
}
