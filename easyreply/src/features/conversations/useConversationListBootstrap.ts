import { useEffect, useState } from 'react';

import { waitForAuthBootstrap } from '@/core/auth-flow';
import {
  ensureClaimedConversationsHydrated,
  getClaimedConversationsSnapshot,
  refreshClaimedConversations,
} from '@/lib/claimed-conversations-store';

/**
 * 会话列表首屏：先 hydrate 本地 claimed 缓存并展示，claimed/list 在后台同步。
 * - blockingLoading：仅无本地缓存时挡列表
 * - initialSyncing：首次 claimed/list 同步中（刷新按钮可转圈，不挡列表）
 */
export function useConversationListBootstrap() {
  const [blockingLoading, setBlockingLoading] = useState(
    () => getClaimedConversationsSnapshot().length === 0,
  );
  const [initialSyncing, setInitialSyncing] = useState(true);

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        if (!(await waitForAuthBootstrap())) {
          if (alive) {
            setBlockingLoading(false);
            setInitialSyncing(false);
          }
          return;
        }
        await ensureClaimedConversationsHydrated();
        if (!alive) return;
        if (getClaimedConversationsSnapshot().length > 0) {
          setBlockingLoading(false);
        }
        await refreshClaimedConversations();
      } catch {
        // 保留本地缓存
      } finally {
        if (alive) {
          setBlockingLoading(false);
          setInitialSyncing(false);
        }
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  return { blockingLoading, initialSyncing };
}
