import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Platform } from 'react-native';
import { buildChatListItems } from '@/chatMessage/message/chat-message-model';
import type { ChatListItem, DisplayMessage } from '@/chatMessage/message/chat-message-model';
import {
  INITIAL_REVEAL_TIMEOUT_MS,
  LIST_PADDING_TOP,
  LOAD_MORE_HEADER_HEIGHT,
  UNLOCK_IDLE_MS,
  UNLOCK_MAX_MS,
} from '@/chatMessage/list/constants';
import type {
  ChatListScrollPort,
  ChatMessageListHandle,
  PrependLock,
} from '@/chatMessage/list/types';

export function useChatListController(opts: {
  isWeb: boolean;
  /** Android 倒序 FlatList：加载更早是 append，不需要钉滚动 */
  inverted: boolean;
  loading: boolean;
  loadingMore: boolean;
  hasMoreBefore: boolean;
  messages: DisplayMessage[];
  onLoadOlder: () => void;
  onDismissComposer?: () => void;
  port: ChatListScrollPort;
}) {
  const {
    isWeb,
    inverted,
    loading,
    loadingMore,
    hasMoreBefore,
    messages,
    onLoadOlder,
    onDismissComposer,
    port,
  } = opts;

  const portRef = useRef(port);
  portRef.current = port;

  const lastScrollYRef = useRef(0);
  const topGateRef = useRef(false);
  const contentHeightRef = useRef(0);
  const itemHeightsRef = useRef(new Map<string, number>());
  const listItemsRef = useRef<ChatListItem[]>([]);
  const showHeaderRef = useRef(false);
  const pendingPrependRef = useRef<PrependLock | null>(null);
  const restoringRef = useRef(false);
  const unlockTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const unlockDeadlineRef = useRef(0);
  const initialScrollPendingRef = useRef(false);
  const pinnedOffsetRef = useRef<number | null>(null);
  const revealTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [scrollLocked, setScrollLocked] = useState(false);
  const [awaitingFirstPaint, setAwaitingFirstPaint] = useState(() => loading);

  const listItems = useMemo(() => buildChatListItems(messages), [messages]);
  listItemsRef.current = listItems;
  showHeaderRef.current = loadingMore || hasMoreBefore;

  const readScrollOffset = useCallback((): number => {
    const node = portRef.current.readNode();
    if (node && Number.isFinite(node.scrollTop)) return node.scrollTop;
    return lastScrollYRef.current;
  }, []);

  const applyScroll = useCallback((offset: number) => {
    const next = Math.max(0, offset);
    const current = readScrollOffset();
    if (restoringRef.current) pinnedOffsetRef.current = next;
    if (Math.abs(next - current) < 0.5) {
      lastScrollYRef.current = next;
      return;
    }
    lastScrollYRef.current = next;
    const node = portRef.current.readNode();
    if (node) node.scrollTop = next;
    portRef.current.scrollToY(next);
  }, [readScrollOffset]);

  const scrollToBottomNow = useCallback(() => {
    const node = portRef.current.readNode();
    if (node) {
      const max = Math.max(0, node.scrollHeight - node.clientHeight);
      node.scrollTop = max;
      lastScrollYRef.current = node.scrollTop;
    }
    portRef.current.scrollToEnd({ animated: false });
  }, []);

  const freezeScroll = useCallback(() => {
    restoringRef.current = true;
    if (pinnedOffsetRef.current == null) pinnedOffsetRef.current = readScrollOffset();
    applyScroll(pinnedOffsetRef.current);
    if (isWeb) setScrollLocked(true);
  }, [applyScroll, isWeb, readScrollOffset]);

  const unfreezeScroll = useCallback(() => {
    if (isWeb) setScrollLocked(false);
  }, [isWeb]);

  const computeAnchorContentY = useCallback((anchorKey: string): number | null => {
    let y = LIST_PADDING_TOP + (showHeaderRef.current ? LOAD_MORE_HEADER_HEIGHT : 0);
    for (const item of listItemsRef.current) {
      if (item.key === anchorKey) return y;
      const h = itemHeightsRef.current.get(item.key);
      if (h == null) return null;
      y += h;
    }
    return null;
  }, []);

  const readAnchorViewportY = useCallback((anchorKey: string): number | null => {
    const measured = portRef.current.measureAnchorViewportY(anchorKey);
    if (measured != null) return measured;
    const contentY = computeAnchorContentY(anchorKey);
    if (contentY == null) return null;
    return contentY - readScrollOffset();
  }, [computeAnchorContentY, readScrollOffset]);

  const pinAnchor = useCallback((): boolean => {
    if (inverted) return true;
    const pending = pendingPrependRef.current;
    if (!pending) return false;
    restoringRef.current = true;

    if (isWeb && portRef.current.scrollAnchorToViewport) {
      portRef.current.scrollAnchorToViewport(pending.anchorKey, pending.viewportY);
      const node = portRef.current.readNode();
      const nextTop = node && Number.isFinite(node.scrollTop) ? node.scrollTop : pending.prevScrollTop;
      lastScrollYRef.current = nextTop;
      pinnedOffsetRef.current = nextTop;
      return true;
    }

    const delta = isWeb
      ? (() => {
          const node = portRef.current.readNode();
          if (!node) return -1;
          return node.scrollHeight - pending.prevScrollHeight;
        })()
      : contentHeightRef.current - pending.prevScrollHeight;

    if (delta < 0.5) return false;

    const nextTop = Math.max(0, pending.prevScrollTop + delta);
    if (isWeb) {
      const node = portRef.current.readNode();
      if (node) node.scrollTop = nextTop;
      lastScrollYRef.current = nextTop;
      pinnedOffsetRef.current = nextTop;
      portRef.current.scrollToY(nextTop);
    } else {
      applyScroll(nextTop);
    }
    return true;
  }, [applyScroll, inverted, isWeb]);

  const clearUnlockTimer = () => {
    if (unlockTimerRef.current) {
      clearTimeout(unlockTimerRef.current);
      unlockTimerRef.current = null;
    }
  };

  const endRestore = useCallback(() => {
    clearUnlockTimer();
    pendingPrependRef.current = null;
    restoringRef.current = false;
    pinnedOffsetRef.current = null;
    unfreezeScroll();
  }, [unfreezeScroll]);

  /** Web：pin 成功后立即解锁，避免 120ms 后再 pin 一次造成闪烁 */
  const completePrependRestore = useCallback(() => {
    if (!pendingPrependRef.current) return false;
    if (!pinAnchor()) return false;
    if (isWeb) {
      endRestore();
      return true;
    }
    scheduleUnlockDelayed();
    return true;
  }, [endRestore, isWeb, pinAnchor]);

  const scheduleUnlockDelayed = useCallback(() => {
    clearUnlockTimer();
    const remain = unlockDeadlineRef.current - Date.now();
    if (remain <= 0) {
      pinAnchor();
      endRestore();
      return;
    }
    unlockTimerRef.current = setTimeout(() => {
      pinAnchor();
      endRestore();
    }, Math.min(UNLOCK_IDLE_MS, remain));
  }, [endRestore, pinAnchor]);

  const reportItemHeight = useCallback((key: string, height: number) => {
    if (height <= 0) return;
    itemHeightsRef.current.set(key, height);
  }, []);

  const finishInitialScroll = useCallback(() => {
    if (!initialScrollPendingRef.current) return;
    scrollToBottomNow();
    requestAnimationFrame(() => {
      scrollToBottomNow();
      initialScrollPendingRef.current = false;
      if (revealTimerRef.current) {
        clearTimeout(revealTimerRef.current);
        revealTimerRef.current = null;
      }
      setAwaitingFirstPaint(false);
    });
  }, [scrollToBottomNow]);

  useLayoutEffect(() => {
    // 仅 Web 可在绘制前钉住；Android 倒序列表不走这条路径
    if (inverted || !pendingPrependRef.current || !isWeb) return;
    if (completePrependRestore()) return;
    let frames = 0;
    let id = 0;
    const retry = () => {
      if (!pendingPrependRef.current) return;
      if (completePrependRestore()) return;
      if (frames++ < 8) id = requestAnimationFrame(retry);
      else scheduleUnlockDelayed();
    };
    id = requestAnimationFrame(retry);
    return () => cancelAnimationFrame(id);
  }, [inverted, isWeb, listItems, hasMoreBefore, completePrependRestore, scheduleUnlockDelayed]);

  useLayoutEffect(() => {
    return () => {
      if (unlockTimerRef.current) clearTimeout(unlockTimerRef.current);
      if (revealTimerRef.current) clearTimeout(revealTimerRef.current);
    };
  }, []);

  useEffect(() => {
    if (loading) {
      setAwaitingFirstPaint(true);
      return;
    }
    if (!initialScrollPendingRef.current) {
      if (revealTimerRef.current) {
        clearTimeout(revealTimerRef.current);
        revealTimerRef.current = null;
      }
      setAwaitingFirstPaint(false);
    }
  }, [loading]);

  useLayoutEffect(() => {
    if (loading || !initialScrollPendingRef.current) return;
    if (!listItems.length) {
      initialScrollPendingRef.current = false;
      setAwaitingFirstPaint(false);
      return;
    }
    if (inverted) {
      initialScrollPendingRef.current = false;
      if (revealTimerRef.current) {
        clearTimeout(revealTimerRef.current);
        revealTimerRef.current = null;
      }
      setAwaitingFirstPaint(false);
      return;
    }
    scrollToBottomNow();
  }, [inverted, loading, listItems, scrollToBottomNow]);

  const tryLoadOlder = useCallback(() => {
    if (awaitingFirstPaint || restoringRef.current || loadingMore || !hasMoreBefore) return;
    if (topGateRef.current) return;
    topGateRef.current = true;
    onLoadOlder();
  }, [awaitingFirstPaint, hasMoreBefore, loadingMore, onLoadOlder]);

  useEffect(() => {
    if (!loadingMore) topGateRef.current = false;
  }, [loadingMore]);

  const handleListScroll = useCallback(
    (e: {
      nativeEvent?: {
        contentOffset?: { y?: number };
        contentSize?: { height?: number };
        layoutMeasurement?: { height?: number };
      };
    }) => {
      const y: number = e?.nativeEvent?.contentOffset?.y ?? 0;
      if (restoringRef.current) {
        const hold = pinnedOffsetRef.current;
        if (hold != null && Math.abs(y - hold) > 0.5) applyScroll(hold);
        return;
      }
      const prevY = lastScrollYRef.current;
      lastScrollYRef.current = y;

      if (inverted) {
        const contentH = e?.nativeEvent?.contentSize?.height ?? 0;
        const viewH = e?.nativeEvent?.layoutMeasurement?.height ?? 0;
        const remaining = contentH - y - viewH;
        if (remaining > 80) topGateRef.current = false;
        const scrollingToOlder = y > prevY + 2;
        if (remaining > 48 || !scrollingToOlder) return;
        tryLoadOlder();
        return;
      }

      if (y > 80) topGateRef.current = false;

      const nearTop = y <= 20;
      const scrollingUp = y < prevY - 2;
      if (!nearTop || !scrollingUp) return;
      tryLoadOlder();
    },
    [applyScroll, inverted, tryLoadOlder],
  );

  const handleWheel = useCallback(
    (e: { deltaY?: number; nativeEvent?: { deltaY?: number } }) => {
      if (Platform.OS !== 'web' || restoringRef.current) return;
      const dy = typeof e.deltaY === 'number' ? e.deltaY : (e.nativeEvent?.deltaY ?? 0);
      if (readScrollOffset() <= 1 && dy < 0) tryLoadOlder();
    },
    [readScrollOffset, tryLoadOlder],
  );

  const dismissKeyboard = useCallback(() => {
    if (Platform.OS === 'web') return;
    onDismissComposer?.();
  }, [onDismissComposer]);

  const handleContentSizeChange = useCallback(
    (_w: number, h: number) => {
      contentHeightRef.current = h;
      if (inverted) {
        if (initialScrollPendingRef.current && h > 0) {
          initialScrollPendingRef.current = false;
          if (revealTimerRef.current) {
            clearTimeout(revealTimerRef.current);
            revealTimerRef.current = null;
          }
          setAwaitingFirstPaint(false);
        }
        return;
      }
      if (initialScrollPendingRef.current && h > 0) {
        finishInitialScroll();
        return;
      }
      if (!pendingPrependRef.current) return;

      const tryPin = () => {
        if (!pendingPrependRef.current) return;
        completePrependRestore();
      };

      tryPin();
      if (!isWeb) requestAnimationFrame(tryPin);
    },
    [completePrependRestore, finishInitialScroll, inverted, isWeb],
  );

  const handle: ChatMessageListHandle = useMemo(
    () => ({
      scrollToEnd: (opts) => portRef.current.scrollToEnd(opts),
      prepareForPrepend: () => {
        if (inverted) return;
        const items = listItemsRef.current;
        const firstMsg = items.find((it) => it.type === 'message');
        const anchorKey = firstMsg?.key ?? items[0]?.key;
        if (!anchorKey) return;

        freezeScroll();

        const node = portRef.current.readNode();
        const measured = readAnchorViewportY(anchorKey);
        const contentY = computeAnchorContentY(anchorKey);
        const scrollY = node && Number.isFinite(node.scrollTop) ? node.scrollTop : readScrollOffset();
        const viewportY =
          measured ??
          (contentY != null ? contentY - scrollY : LIST_PADDING_TOP + (showHeaderRef.current ? LOAD_MORE_HEADER_HEIGHT : 0) - scrollY);

        clearUnlockTimer();
        restoringRef.current = true;
        unlockDeadlineRef.current = Date.now() + UNLOCK_MAX_MS;
        pendingPrependRef.current = {
          anchorKey,
          viewportY,
          prevScrollHeight: node?.scrollHeight ?? contentHeightRef.current,
          prevScrollTop: scrollY,
        };
      },
      lockScrollForPrepend: () => {
        if (inverted) return;
        freezeScroll();
      },
      releasePrependLock: () => {
        endRestore();
      },
      markInitialScrollPending: () => {
        initialScrollPendingRef.current = true;
        setAwaitingFirstPaint(true);
        if (revealTimerRef.current) clearTimeout(revealTimerRef.current);
        revealTimerRef.current = setTimeout(() => {
          initialScrollPendingRef.current = false;
          setAwaitingFirstPaint(false);
        }, INITIAL_REVEAL_TIMEOUT_MS);
      },
      revealFromCache: () => {
        initialScrollPendingRef.current = false;
        if (revealTimerRef.current) {
          clearTimeout(revealTimerRef.current);
          revealTimerRef.current = null;
        }
        setAwaitingFirstPaint(false);
        // prepend 锚点恢复中：只去遮罩，不抢滚动位置
        if (pendingPrependRef.current) return;
        if (inverted) {
          scrollToBottomNow();
        } else {
          requestAnimationFrame(() => scrollToBottomNow());
        }
      },
    }),
    [computeAnchorContentY, endRestore, freezeScroll, inverted, readAnchorViewportY, readScrollOffset, scrollToBottomNow],
  );

  return {
    listItems,
    scrollLocked,
    awaitingFirstPaint,
    showCover: loading || awaitingFirstPaint,
    tryLoadOlder,
    handleListScroll,
    handleWheel,
    handleContentSizeChange,
    reportItemHeight,
    dismissKeyboard,
    handle,
  };
}
