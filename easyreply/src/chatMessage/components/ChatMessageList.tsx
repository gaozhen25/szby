import { forwardRef, memo, useCallback, useEffect, useImperativeHandle, useMemo, useRef } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
  type ViewStyle,
} from 'react-native';
import { useTheme } from '@/design/theme-context';
import { ChatType } from '@/design/chat-type';
import { ChatRow, ChatTimeCell } from '@/chatMessage/components/ChatBubbleRow';
import type { ChatListItem, DisplayMessage } from '@/chatMessage/message/chat-message-model';
import {
  LIST_PADDING_TOP,
  LOAD_MORE_HEADER_HEIGHT,
  asRectNode,
  getScrollNode,
  useChatListController,
  type ChatMessageListHandle,
} from '@/chatMessage/list';

export type { ChatMessageListHandle };

export const ChatMessageList = memo(forwardRef<
  ChatMessageListHandle,
  {
    loading: boolean;
    messages: DisplayMessage[];
    loadingMore: boolean;
    hasMoreBefore: boolean;
    onLoadOlder: () => void;
    /** 滑动消息区时收起键盘（需 blur WebView composer） */
    onDismissComposer?: () => void;
    onOpenImage: (uri: string) => void;
    onOpenVideo: (params: { uri: string; fileName?: string }) => void;
    onOpenFile: (params: { uri: string; fileName: string }) => void;
    onOpenActionMenu: (
      kind: 'text' | 'image' | 'sticker',
      content: string,
      rect: { x: number; y: number; width: number; height: number },
      opts?: {
        cursorX?: number;
        cursorY?: number;
        imageWidth?: number;
        imageHeight?: number;
      },
    ) => void;
    onPressAudienceAvatar: () => void;
    actorAvatarUrl?: string;
    audienceAvatarUrl?: string;
    audienceAvatarColor?: string;
    actorNickname?: string;
    audienceNickname?: string;
  }
>(function ChatMessageList(
  {
    loading,
    messages,
    loadingMore,
    hasMoreBefore,
    onLoadOlder,
    onDismissComposer,
    onOpenImage,
    onOpenVideo,
    onOpenFile,
    onOpenActionMenu,
    onPressAudienceAvatar,
    actorAvatarUrl,
    audienceAvatarUrl,
    audienceAvatarColor,
    actorNickname,
    audienceNickname,
  },
  ref,
) {
  const theme = useTheme();
  const flatListRef = useRef<FlatList<ChatListItem>>(null);
  const scrollViewRef = useRef<ScrollView>(null);
  const rowRefs = useRef(new Map<string, unknown>());
  const cachedScrollElRef = useRef<HTMLElement | null>(null);
  const isWeb = Platform.OS === 'web';
  /** Android：倒序 FlatList，加载历史是往数据尾部追加，系统不会把当前画面顶走 */
  const inverted = Platform.OS === 'android';
  const endReachedArmedRef = useRef(false);

  const readNode = useCallback((): HTMLElement | null => {
    if (!isWeb) return null;
    const cached = cachedScrollElRef.current;
    if (cached?.isConnected) return cached;
    const node = getScrollNode(scrollViewRef.current);
    if (node) {
      node.style.overflowAnchor = 'none';
      cachedScrollElRef.current = node;
    }
    return node;
  }, [isWeb]);

  const measureAnchorViewportY = useCallback((anchorKey: string): number | null => {
    if (Platform.OS !== 'web') return null;
    const row = asRectNode(rowRefs.current.get(anchorKey));
    const list = asRectNode(readNode());
    if (row && list) {
      return row.getBoundingClientRect().top - list.getBoundingClientRect().top;
    }
    return null;
  }, [readNode]);

  const port = {
    readNode,
    scrollToEnd: (opts: { animated: boolean }) => {
      if (isWeb) scrollViewRef.current?.scrollToEnd(opts);
      else if (inverted) flatListRef.current?.scrollToOffset({ offset: 0, animated: opts.animated });
      else flatListRef.current?.scrollToEnd(opts);
    },
    scrollToY: (y: number) => {
      if (isWeb) scrollViewRef.current?.scrollTo({ y, animated: false });
      else flatListRef.current?.scrollToOffset({ offset: y, animated: false });
    },
    measureAnchorViewportY,
  };

  const list = useChatListController({
    isWeb,
    inverted,
    loading,
    loadingMore,
    hasMoreBefore,
    messages,
    onLoadOlder,
    onDismissComposer,
    port,
  });

  useImperativeHandle(ref, () => list.handle, [list.handle]);

  useEffect(() => {
    if (!inverted) return;
    if (loading || list.awaitingFirstPaint) {
      endReachedArmedRef.current = false;
      return;
    }
    const t = setTimeout(() => {
      endReachedArmedRef.current = true;
    }, 400);
    return () => clearTimeout(t);
  }, [inverted, loading, list.awaitingFirstPaint]);

  const handleEndReached = useCallback(() => {
    if (!inverted || !endReachedArmedRef.current) return;
    list.tryLoadOlder();
  }, [inverted, list.tryLoadOlder]);

  const bindRowRef = useCallback((key: string, node: unknown) => {
    if (node) rowRefs.current.set(key, node);
    else rowRefs.current.delete(key);
  }, []);

  const loadMoreHeader =
    loadingMore || hasMoreBefore ? (
      <View style={styles.loadMoreWrap}>
        {loadingMore ? (
          <>
            <ActivityIndicator size="small" color={theme.primary} />
            <Text style={styles.loadMoreText}>加载更早消息…</Text>
          </>
        ) : (
          <Pressable onPress={list.tryLoadOlder} hitSlop={12} style={styles.loadMorePress}>
            <Text style={styles.loadMoreText}>点击或上滑加载更早消息</Text>
          </Pressable>
        )}
      </View>
    ) : null;

  const renderRow = (item: ChatListItem) => (
    <View
      key={item.key}
      collapsable={false}
      ref={(node) => bindRowRef(item.key, node)}
      onLayout={(e) => list.reportItemHeight(item.key, e.nativeEvent.layout.height)}
    >
      {item.type === 'time' ? (
        <ChatTimeCell time={item.time} />
      ) : (
        <ChatRow
          item={item.message}
          onOpenImage={onOpenImage}
          onOpenVideo={onOpenVideo}
          onOpenFile={onOpenFile}
          onOpenActionMenu={onOpenActionMenu}
          onPressAudienceAvatar={onPressAudienceAvatar}
          actorAvatarUrl={actorAvatarUrl}
          audienceAvatarUrl={audienceAvatarUrl}
          audienceAvatarColor={audienceAvatarColor}
          actorNickname={actorNickname}
          audienceNickname={audienceNickname}
        />
      )}
    </View>
  );

  const dataItems = useMemo(
    () => (inverted ? [...list.listItems].reverse() : list.listItems),
    [inverted, list.listItems],
  );

  const canScroll = !list.scrollLocked && !list.awaitingFirstPaint;
  const scrollProps = {
    showsVerticalScrollIndicator: false,
    keyboardShouldPersistTaps: 'handled' as const,
    onScroll: list.handleListScroll,
    onContentSizeChange: list.handleContentSizeChange,
    scrollEventThrottle: 16,
    scrollEnabled: canScroll,
  };

  return (
    <View
      style={styles.flex}
      {...(Platform.OS === 'web' ? { onWheel: list.handleWheel } : null)}
    >
      {!loading && isWeb ? (
        <ScrollView
          ref={scrollViewRef}
          style={[styles.flex, webScrollStyle, list.awaitingFirstPaint ? styles.hiddenList : null]}
          contentContainerStyle={styles.listContent}
          {...scrollProps}
        >
          {loadMoreHeader}
          {list.listItems.map(renderRow)}
        </ScrollView>
      ) : null}
      {!loading && !isWeb ? (
        <FlatList<ChatListItem>
          ref={flatListRef}
          style={[styles.flex, list.awaitingFirstPaint ? styles.hiddenList : null]}
          data={dataItems}
          inverted={inverted}
          extraData={`${loadingMore}:${hasMoreBefore}`}
          keyExtractor={(item) => item.key}
          renderItem={({ item }) => renderRow(item)}
          keyboardDismissMode={Platform.OS === 'ios' ? 'interactive' : 'on-drag'}
          onScrollBeginDrag={list.dismissKeyboard}
          maintainVisibleContentPosition={
            inverted ? undefined : { minIndexForVisible: 0, autoscrollToTopThreshold: 16 }
          }
          removeClippedSubviews={false}
          initialNumToRender={16}
          maxToRenderPerBatch={8}
          windowSize={7}
          bounces={canScroll}
          alwaysBounceVertical={canScroll}
          overScrollMode="never"
          onEndReached={inverted ? handleEndReached : undefined}
          onEndReachedThreshold={0.15}
          ListHeaderComponent={inverted ? null : loadMoreHeader}
          ListFooterComponent={inverted ? loadMoreHeader : null}
          contentContainerStyle={inverted ? styles.invertedListContent : styles.listContent}
          {...scrollProps}
        />
      ) : null}
      {list.showCover ? (
        <View style={[styles.cover, { backgroundColor: theme.bg }]} pointerEvents="auto">
          <ActivityIndicator color={theme.primary} />
        </View>
      ) : null}
    </View>
  );
}));

const webScrollStyle: ViewStyle = { overflowAnchor: 'none' } as ViewStyle;

const styles = StyleSheet.create({
  flex: { flex: 1, minHeight: 0 },
  hiddenList: { opacity: 0 },
  cover: {
    ...StyleSheet.absoluteFillObject,
    justifyContent: 'center',
    alignItems: 'center',
    zIndex: 2,
  },
  listContent: { paddingHorizontal: 12, paddingVertical: LIST_PADDING_TOP, flexGrow: 1 },
  /** inverted 时 flex-end = 视觉顶部；内容不满一屏时消息从顶部排布 */
  invertedListContent: {
    paddingHorizontal: 12,
    paddingVertical: LIST_PADDING_TOP,
    flexGrow: 1,
    justifyContent: 'flex-end',
  },
  loadMoreWrap: { height: LOAD_MORE_HEADER_HEIGHT, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6 },
  loadMorePress: { flex: 1, height: '100%', alignItems: 'center', justifyContent: 'center' },
  loadMoreText: {
    fontSize: ChatType.size.hint,
    lineHeight: ChatType.lineHeight.subLabel,
    fontWeight: ChatType.weight.regular,
    color: ChatType.color.hint,
  },
});
