import { startTransition, useCallback, useEffect, useRef, useState } from 'react';
import { Platform } from 'react-native';
import { useFocusEffect } from 'expo-router';

import type { MockConversation } from '@/mock/data';
import { waitForAuthBootstrap } from '@/core/auth-flow';
import {
  ensureClaimedConversationsHydrated,
  getClaimedConversationsSnapshot,
  getClaimedCountSnapshot,
  subscribeClaimedConversations,
} from '@/lib/claimed-conversations-store';

export type ClaimedConversationsSubscriptionMode = 'focused' | 'mounted';

/**
 * 订阅全局会话列表 Store。
 *
 * - `mounted`：组件挂载期间持续订阅（Web 桌面分栏左侧列表，与右侧聊天同屏时仍实时更新）
 * - `focused`：仅页面/Tab 聚焦时订阅（移动端列表进独立聊天页后暂停重绘）
 */
export function useClaimedConversationsSubscription(
  mode: ClaimedConversationsSubscriptionMode = Platform.OS === 'web' ? 'mounted' : 'focused',
) {
  const [conversations, setConversations] = useState<MockConversation[]>(() =>
    getClaimedConversationsSnapshot(),
  );
  const [claimedCount, setClaimedCount] = useState(() => getClaimedCountSnapshot());

  const firstNotifyRef = useRef(true);
  const hadItemsRef = useRef(getClaimedConversationsSnapshot().length > 0);
  const prevLenRef = useRef(getClaimedConversationsSnapshot().length);

  const attach = useCallback(() => {
    firstNotifyRef.current = true;
    const snapshot = getClaimedConversationsSnapshot();
    hadItemsRef.current = snapshot.length > 0;
    prevLenRef.current = snapshot.length;
    setConversations(snapshot);
    setClaimedCount(getClaimedCountSnapshot());
    return subscribeClaimedConversations((next) => {
      const apply = () => {
        setConversations(next);
        setClaimedCount(getClaimedCountSnapshot());
      };
      const prevLen = prevLenRef.current;
      prevLenRef.current = next.length;
      const wasEmpty = !hadItemsRef.current;
      hadItemsRef.current = next.length > 0;
      // 空→有、或条数变化（如下班后再上班）必须同步提交，否则窗口化会按旧高度切片
      if (firstNotifyRef.current || wasEmpty || prevLen !== next.length) {
        firstNotifyRef.current = false;
        apply();
        return;
      }
      startTransition(apply);
    });
  }, []);

  useEffect(() => {
    void (async () => {
      if (!(await waitForAuthBootstrap())) return;
      await ensureClaimedConversationsHydrated();
    })();
  }, []);

  useEffect(() => {
    if (mode !== 'mounted') return;
    return attach();
  }, [attach, mode]);

  useFocusEffect(
    useCallback(() => {
      if (mode !== 'focused') return;
      return attach();
    }, [attach, mode]),
  );

  return { conversations, claimedCount, setConversations, setClaimedCount };
}
