import { memo, useCallback, useEffect, useRef, useState } from 'react';
import { Animated, Easing, Platform, Pressable, ScrollView, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { Image as ExpoImage } from 'expo-image';
import { EmojiText } from '@/chatMessage/components/EmojiText';
import { CachedImage } from '@/chatMessage/components/CachedImage';
import {
  CaretRightFilled,
  EnvironmentOutlined,
  FileTextOutlined,
  ReloadOutlined,
  SmileOutlined,
  SoundOutlined,
} from '@/ui/antd-icons';
import { computeChatImageDisplaySize, readImageLoadDimensions } from '@/chatMessage/message/chat-image-size';
import { playVoiceUrl, stopVoicePlayback } from '@/chatMessage/message/voice-player';
import { formatFileSize } from '@/core/im/file-message';
import { formatVideoDurationLabel } from '@/core/im/video-message';
import { openChatLocation } from '@/chatMessage/message/open-location';
import { appAlert } from '@/lib/app-alert';
import { formatTaskTriggerTime, formatTaskTriggerTimeFull } from '@/lib/task-session-list';
import type { DisplayMessage } from '@/chatMessage/message/chat-message-model';
import { useDelayedSendingIndicator } from '@/chatMessage/message/useDelayedSendingIndicator';
import { InAppModal } from '@/components/UI/InAppModal';
import { quoteHoverBody } from '@/core/im/quote-message';
import { formatLocationCoordLabel } from '@/core/im/location-message';
import { ChatType } from '@/design/chat-type';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

const QUOTE_POP_GAP = 8;
const QUOTE_CARET = 6;
const QUOTE_POP_MAX_W = 280;
const QUOTE_POP_MAX_H = 220;
const QUOTE_POP_MIN_SIDE = 160;

type QuotePopSide = 'left' | 'right' | 'top' | 'bottom';

function computeQuotePopLayout(opts: {
  anchor: { x: number; y: number; width: number; height: number };
  winW: number;
  winH: number;
  insets: { top: number; bottom: number };
  popH: number;
  mine: boolean;
}): {
  side: QuotePopSide;
  left: number;
  top: number;
  popW: number;
  maxHeight: number;
  caretTop: number;
  caretLeft: number;
} {
  const a = opts.anchor;
  const padL = QUOTE_POP_GAP;
  const padR = opts.winW - QUOTE_POP_GAP;
  const padT = opts.insets.top + QUOTE_POP_GAP;
  const padB = opts.winH - opts.insets.bottom - QUOTE_POP_GAP;
  const innerW = Math.max(80, padR - padL);

  const spaceLeft = a.x - padL - QUOTE_POP_GAP - QUOTE_CARET;
  const spaceRight = padR - (a.x + a.width) - QUOTE_POP_GAP - QUOTE_CARET;
  const spaceTop = a.y - padT - QUOTE_POP_GAP - QUOTE_CARET;
  const spaceBottom = padB - (a.y + a.height) - QUOTE_POP_GAP - QUOTE_CARET;
  const fullW = Math.min(QUOTE_POP_MAX_W, innerW);

  const preferred: QuotePopSide = opts.mine ? 'left' : 'right';
  const preferredSpace = preferred === 'left' ? spaceLeft : spaceRight;
  let side: QuotePopSide = preferred;
  if (preferredSpace < QUOTE_POP_MIN_SIDE) {
    const ranked: { side: QuotePopSide; score: number }[] = [
      { side: 'left', score: spaceLeft >= 80 ? spaceLeft : -1 },
      { side: 'right', score: spaceRight >= 80 ? spaceRight : -1 },
      { side: 'top', score: spaceTop >= 80 ? fullW : -1 },
      { side: 'bottom', score: spaceBottom >= 80 ? fullW : -1 },
    ];
    ranked.sort((x, y) => y.score - x.score);
    side = ranked[0].score > 0 ? ranked[0].side : spaceBottom >= spaceTop ? 'bottom' : 'top';
  }

  const maxHCap = Math.min(QUOTE_POP_MAX_H, Math.max(96, Math.floor((padB - padT) * 0.6)));

  if (side === 'left' || side === 'right') {
    const avail = side === 'left' ? Math.max(80, spaceLeft) : Math.max(80, spaceRight);
    const popW = Math.min(QUOTE_POP_MAX_W, avail);
    const left =
      side === 'left'
        ? Math.max(padL, a.x - QUOTE_POP_GAP - QUOTE_CARET - popW)
        : Math.min(a.x + a.width + QUOTE_POP_GAP + QUOTE_CARET, padR - popW);
    const maxHeight = maxHCap;
    const h = Math.min(opts.popH || 40, maxHeight);
    let top = a.y + a.height / 2 - h / 2;
    top = Math.min(Math.max(top, padT), Math.max(padT, padB - h));
    const caretTop = Math.min(
      Math.max(a.y + a.height / 2 - top - QUOTE_CARET, 8),
      Math.max(8, h - 8 - QUOTE_CARET * 2),
    );
    return { side, left, top, popW, maxHeight, caretTop, caretLeft: 0 };
  }

  const popW = fullW;
  let left = a.x + a.width / 2 - popW / 2;
  left = Math.min(Math.max(left, padL), padR - popW);
  const availH = Math.max(80, side === 'top' ? spaceTop : spaceBottom);
  const maxHeight = Math.min(maxHCap, availH);
  const h = Math.min(opts.popH || 40, maxHeight);
  const top =
    side === 'top'
      ? Math.max(padT, a.y - QUOTE_POP_GAP - QUOTE_CARET - h)
      : Math.min(a.y + a.height + QUOTE_POP_GAP + QUOTE_CARET, padB - h);
  const caretLeft = Math.min(
    Math.max(a.x + a.width / 2 - left - QUOTE_CARET, 12),
    popW - 12 - QUOTE_CARET * 2,
  );
  return { side, left, top, popW, maxHeight, caretTop: 0, caretLeft };
}

function QuoteSnippet({ text, mine }: { text: string; mine: boolean }) {
  const quoteRef = useRef<View>(null);
  const { width: winW, height: winH } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const [open, setOpen] = useState(false);
  const [anchor, setAnchor] = useState<{ x: number; y: number; width: number; height: number } | null>(null);
  const [popH, setPopH] = useState(0);
  const body = quoteHoverBody(text);

  const close = useCallback(() => setOpen(false), []);

  const handlePress = useCallback(() => {
    quoteRef.current?.measureInWindow((x, y, width, height) => {
      setAnchor({ x, y, width, height });
      setPopH(0);
      setOpen(true);
    });
  }, []);

  const layout = anchor
    ? computeQuotePopLayout({ anchor, winW, winH, insets, popH, mine })
    : null;

  return (
    <>
      <Pressable
        ref={quoteRef}
        onPress={handlePress}
        hitSlop={6}
        accessibilityRole="button"
        accessibilityLabel={`查看引用 ${text}`}
        style={[r.quoteBox, mine ? r.quoteBoxMine : r.quoteBoxPeer]}
      >
        <Text style={r.quoteText} numberOfLines={2}>
          {text}
        </Text>
      </Pressable>
      <InAppModal visible={open} transparent animationType="fade" statusBarTranslucent onRequestClose={close}>
        <View style={r.quoteOverlay} pointerEvents="box-none">
          <Pressable style={StyleSheet.absoluteFill} onPress={close} accessibilityRole="button" accessibilityLabel="关闭引用" />
          {layout ? (
            <View
              style={[
                r.quotePopWrap,
                layout.side === 'top' || layout.side === 'bottom' ? r.quotePopWrapVert : r.quotePopWrapHori,
                {
                  left: layout.side === 'right' ? layout.left - QUOTE_CARET : layout.left,
                  top: layout.side === 'bottom' ? layout.top - QUOTE_CARET : layout.top,
                  width:
                    layout.side === 'left' || layout.side === 'right'
                      ? layout.popW + QUOTE_CARET
                      : layout.popW,
                },
              ]}
            >
              {layout.side === 'right' ? <View style={[r.quoteCaretLeft, { marginTop: layout.caretTop }]} /> : null}
              {layout.side === 'bottom' ? <View style={[r.quoteCaretUp, { marginLeft: layout.caretLeft }]} /> : null}
              <View
                style={[r.quotePop, { width: layout.popW, maxHeight: layout.maxHeight }]}
                onLayout={(e) => {
                  const h = Math.round(e.nativeEvent.layout.height);
                  if (h > 0 && h !== popH) setPopH(h);
                }}
              >
                <ScrollView
                  bounces={false}
                  nestedScrollEnabled
                  showsVerticalScrollIndicator
                  style={{ maxHeight: Math.max(64, layout.maxHeight - 16) }}
                  contentContainerStyle={{ width: Math.max(0, layout.popW - 24) }}
                >
                  <EmojiText text={body} color={ChatType.color.text} textStyle={r.quotePopText} />
                </ScrollView>
              </View>
              {layout.side === 'left' ? <View style={[r.quoteCaretRight, { marginTop: layout.caretTop }]} /> : null}
              {layout.side === 'top' ? <View style={[r.quoteCaretDown, { marginLeft: layout.caretLeft }]} /> : null}
            </View>
          ) : null}
        </View>
      </InAppModal>
    </>
  );
}
function BubbleTail({ side, color }: { side: 'left' | 'right'; color: string }) {
  return (
    <View
      style={[
        r.tail,
        side === 'left' ? r.tailLeft : r.tailRight,
        side === 'left' ? { borderRightColor: color } : { borderLeftColor: color },
      ]}
    />
  );
}

function MessageAvatar({
  url,
  fallbackColor,
  fallbackText,
  onPress,
}: {
  url?: string;
  fallbackColor: string;
  /** 无头像图时展示的文字（取 nickname 首字） */
  fallbackText?: string;
  onPress?: () => void;
}) {
  const [failed, setFailed] = useState(false);
  const avatarUrl = url?.trim();
  const showImage = !!avatarUrl && !failed;
  const letter = (fallbackText ?? '').trim().charAt(0);

  const content = (
    <View style={[r.avatar, { backgroundColor: fallbackColor, overflow: 'hidden' }]}>
      {showImage ? (
        <CachedImage
          source={{ uri: avatarUrl }}
          style={r.avatarImage}
          contentFit="cover"
          onError={() => setFailed(true)}
        />
      ) : letter ? (
        <View style={r.avatarFallback}>
          <Text style={r.avatarFallbackText}>{letter}</Text>
        </View>
      ) : null}
    </View>
  );

  if (!onPress) return content;
  return (
    <Pressable onPress={onPress} hitSlop={4} accessibilityRole="button" accessibilityLabel="查看资料">
      {content}
    </Pressable>
  );
}

function SendingSpinner() {
  const spin = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(spin, {
          toValue: 1,
          duration: 800,
          easing: Easing.linear,
          useNativeDriver: true,
        }),
        Animated.timing(spin, { toValue: 0, duration: 0, useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => {
      loop.stop();
      spin.setValue(0);
    };
  }, [spin]);

  return (
    <Animated.View
      accessibilityRole="progressbar"
      accessibilityLabel="发送中"
      style={{
        transform: [{ rotate: spin.interpolate({ inputRange: [0, 1], outputRange: ['0deg', '360deg'] }) }],
      }}
    >
      <ReloadOutlined size={12} color={ChatType.color.timestamp} />
    </Animated.View>
  );
}

function SendingStatusIndicator({
  status,
  sendTime,
}: {
  status?: DisplayMessage['status'];
  sendTime: number;
}) {
  const show = useDelayedSendingIndicator(status, sendTime);
  if (status !== 'sending' || !show) return null;
  return (
    <View style={r.sendStatus}>
      <SendingSpinner />
    </View>
  );
}

export function ChatTimeCell({ time }: { time: number }) {
  const [full, setFull] = useState(false);
  const label = full
    ? formatTaskTriggerTimeFull(time)
    : formatTaskTriggerTime(time, { withClockForOlder: true });
  if (!label) return null;
  return (
    <Pressable
      onPress={() => setFull((v) => !v)}
      hitSlop={8}
      accessibilityRole="button"
      accessibilityLabel={full ? '收起时间' : '显示完整时间'}
      style={r.timeCell}
    >
      <Text style={r.timeCellText}>{label}</Text>
    </Pressable>
  );
}

function ChatImageBubble({
  uri,
  presetWidth,
  presetHeight,
  isEmojiSticker = false,
  mine = false,
  onPress,
  onLongPress,
  onContextMenu,
}: {
  uri: string;
  /** 消息元数据宽高，仅作加载前占位；最终以 loadAsync / onLoad 实测为准 */
  presetWidth?: number;
  presetHeight?: number;
  isEmojiSticker?: boolean;
  mine?: boolean;
  onPress: () => void;
  onLongPress?: () => void;
  onContextMenu?: (e: {
    preventDefault?: () => void;
    nativeEvent?: { clientX?: number; clientY?: number; preventDefault?: () => void };
  }) => void;
}) {
  const sizeVariant = isEmojiSticker ? 'emoji' : 'image';
  const [displaySize, setDisplaySize] = useState(() =>
    computeChatImageDisplaySize(presetWidth, presetHeight, sizeVariant),
  );

  useEffect(() => {
    setDisplaySize(computeChatImageDisplaySize(presetWidth, presetHeight, sizeVariant));

    const hasPreset =
      typeof presetWidth === 'number' &&
      presetWidth > 0 &&
      typeof presetHeight === 'number' &&
      presetHeight > 0;
    // 已有元数据尺寸时不再 loadAsync / onLoad 改高：避免加载更多时气泡撑开导致滚动抖动
    if (hasPreset) return;

    let alive = true;
    ExpoImage.loadAsync(uri)
      .then((ref) => {
        if (alive) setDisplaySize(computeChatImageDisplaySize(ref.width, ref.height, sizeVariant));
      })
      .catch(() => {
        if (alive) setDisplaySize(computeChatImageDisplaySize(presetWidth, presetHeight, sizeVariant));
      });
    return () => {
      alive = false;
    };
  }, [uri, presetWidth, presetHeight, sizeVariant]);

  const hasPresetSize =
    typeof presetWidth === 'number' &&
    presetWidth > 0 &&
    typeof presetHeight === 'number' &&
    presetHeight > 0;

  const handleImageLoad = useCallback(
    (e: unknown) => {
      if (hasPresetSize) return;
      const { width: w, height: h } = readImageLoadDimensions(e);
      if (w && h) {
        setDisplaySize(computeChatImageDisplaySize(w, h, sizeVariant));
      }
    },
    [hasPresetSize, sizeVariant],
  );

  const imageNode = (
    <Pressable
      onPress={onPress}
      onLongPress={onLongPress}
      delayLongPress={300}
      hitSlop={4}
      // @ts-expect-error RN Web 右键菜单
      onContextMenu={Platform.OS === 'web' ? onContextMenu : undefined}
    >
      <CachedImage
        source={{ uri }}
        style={[
          r.chatImage,
          isEmojiSticker && r.chatImageEmoji,
          { width: displaySize.width, height: displaySize.height },
        ]}
        contentFit="cover"
        recyclingKey={uri}
        onLoad={handleImageLoad}
      />
    </Pressable>
  );

  if (!isEmojiSticker) return imageNode;

  const badge = (
    <View style={r.emojiStickerBadge} pointerEvents="none">
      <SmileOutlined size={12} color="#5A626C" />
    </View>
  );

  return (
    <View style={r.emojiStickerWrap}>
      {mine ? (
        <>
          {badge}
          {imageNode}
        </>
      ) : (
        <>
          {imageNode}
          {badge}
        </>
      )}
    </View>
  );
}

function ChatVoiceBubble({
  duration,
  voiceUrl,
  mine,
}: {
  duration: number;
  voiceUrl: string;
  mine: boolean;
}) {
  const [playing, setPlaying] = useState(false);
  const stopRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    return () => {
      stopRef.current?.();
      stopRef.current = null;
    };
  }, []);

  const width = Math.min(168, Math.max(72, 56 + duration * 8));
  const label = `${Math.max(1, Math.round(duration))}"`;
  const iconColor = mine ? ChatType.color.onPrimary : ChatType.color.text;
  const textColor = mine ? ChatType.color.onPrimary : ChatType.color.text;

  const handlePress = useCallback(() => {
    if (!voiceUrl) return;
    if (playing) {
      stopRef.current?.();
      stopRef.current = null;
      stopVoicePlayback();
      setPlaying(false);
      return;
    }
    setPlaying(true);
    const handle = playVoiceUrl(voiceUrl, () => {
      stopRef.current = null;
      setPlaying(false);
    });
    stopRef.current = handle.stop;
  }, [playing, voiceUrl]);

  return (
    <Pressable
      onPress={handlePress}
      style={[r.voiceInner, { width, flexDirection: mine ? 'row-reverse' : 'row' }]}
      accessibilityRole="button"
      accessibilityLabel={`语音消息 ${label}`}
    >
      <SoundOutlined size={20} color={iconColor} />
      <Text style={[r.voiceDuration, { color: textColor }]}>{label}</Text>
    </Pressable>
  );
}

function ChatFileBubble({
  fileName,
  fileSize,
  mine,
  sending = false,
  onPress,
}: {
  fileName: string;
  fileSize: number;
  mine: boolean;
  sending?: boolean;
  onPress: () => void;
}) {
  const textColor = mine ? ChatType.color.onPrimary : ChatType.color.text;
  const subColor = mine ? 'rgba(255,255,255,0.72)' : ChatType.color.subLabel;
  const iconColor = mine ? ChatType.color.onPrimary : ChatType.color.text;
  const sizeLabel = formatFileSize(fileSize);

  return (
    <Pressable
      onPress={sending ? undefined : onPress}
      disabled={sending}
      style={({ pressed }) => [r.fileInner, !sending && pressed && { opacity: 0.75 }]}
      accessibilityRole="button"
      accessibilityLabel={`打开文件 ${fileName}`}
    >
      <View style={[r.fileIconWrap, mine ? r.fileIconMine : r.fileIconPeer]}>
        <FileTextOutlined size={22} color={iconColor} />
      </View>
      <View style={r.fileTextWrap}>
        <Text style={[r.fileName, { color: textColor }]} numberOfLines={2}>
          {fileName || '文件'}
        </Text>
        {sizeLabel ? <Text style={[r.fileSize, { color: subColor }]}>{sizeLabel}</Text> : null}
      </View>
    </Pressable>
  );
}

function ChatLocationBubble({
  description,
  latitude,
  longitude,
  mine,
}: {
  description: string;
  latitude: number;
  longitude: number;
  mine: boolean;
}) {
  const textColor = mine ? ChatType.color.onPrimary : ChatType.color.text;
  const subColor = mine ? 'rgba(255,255,255,0.72)' : ChatType.color.subLabel;
  const iconColor = mine ? ChatType.color.onPrimary : ChatType.color.text;
  const title = description.trim() || '位置';
  const coordLabel = formatLocationCoordLabel(latitude, longitude);

  return (
    <Pressable
      onPress={() => {
        void openChatLocation({ latitude, longitude, description: title }).catch((e) => {
          appAlert('无法打开地图', e instanceof Error ? e.message : '请稍后重试');
        });
      }}
      style={({ pressed }) => [r.fileInner, pressed && { opacity: 0.75 }]}
      accessibilityRole="button"
      accessibilityLabel={`查看位置 ${title}`}
    >
      <View style={[r.fileIconWrap, mine ? r.fileIconMine : r.fileIconPeer]}>
        <EnvironmentOutlined size={22} color={iconColor} />
      </View>
      <View style={r.fileTextWrap}>
        <Text style={[r.fileName, { color: textColor }]} numberOfLines={2}>
          {title}
        </Text>
        {coordLabel ? <Text style={[r.fileSize, { color: subColor }]}>{coordLabel}</Text> : null}
      </View>
    </Pressable>
  );
}

function ChatVideoBubble({
  snapshotUrl,
  duration,
  snapshotWidth,
  snapshotHeight,
  onPress,
}: {
  snapshotUrl: string;
  duration: number;
  snapshotWidth?: number;
  snapshotHeight?: number;
  onPress: () => void;
}) {
  const [displaySize, setDisplaySize] = useState(() =>
    computeChatImageDisplaySize(snapshotWidth, snapshotHeight, 'image'),
  );

  useEffect(() => {
    setDisplaySize(computeChatImageDisplaySize(snapshotWidth, snapshotHeight, 'image'));
    const uri = (snapshotUrl || '').trim();
    const hasPreset =
      typeof snapshotWidth === 'number' &&
      snapshotWidth > 0 &&
      typeof snapshotHeight === 'number' &&
      snapshotHeight > 0;
    if (!uri || hasPreset) return;

    let alive = true;
    ExpoImage.loadAsync(uri)
      .then((ref) => {
        if (alive && ref.width > 0 && ref.height > 0) {
          setDisplaySize(computeChatImageDisplaySize(ref.width, ref.height, 'image'));
        }
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [snapshotUrl, snapshotWidth, snapshotHeight]);

  const hasPresetSize =
    typeof snapshotWidth === 'number' &&
    snapshotWidth > 0 &&
    typeof snapshotHeight === 'number' &&
    snapshotHeight > 0;

  const handleSnapshotLoad = useCallback((e: unknown) => {
    if (hasPresetSize) return;
    const { width: w, height: h } = readImageLoadDimensions(e);
    if (w && h) {
      setDisplaySize(computeChatImageDisplaySize(w, h, 'image'));
    }
  }, [hasPresetSize]);

  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [r.videoWrap, pressed && { opacity: 0.85 }]}
      accessibilityRole="button"
      accessibilityLabel="播放视频"
    >
      {snapshotUrl ? (
        <CachedImage
          source={{ uri: snapshotUrl }}
          style={[r.chatImage, { width: displaySize.width, height: displaySize.height }]}
          contentFit="cover"
          onLoad={handleSnapshotLoad}
        />
      ) : (
        <View style={[r.videoPlaceholder, { width: displaySize.width, height: displaySize.height }]} />
      )}
      <View style={r.videoPlayOverlay} pointerEvents="none">
        <View style={r.videoPlayBtn}>
          <CaretRightFilled size={22} color="#FFF" />
        </View>
      </View>
      <View style={r.videoDurationBadge} pointerEvents="none">
        <Text style={r.videoDurationText}>{formatVideoDurationLabel(duration)}</Text>
      </View>
    </Pressable>
  );
}

export const ChatRow = memo(function ChatRow({
  item,
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
}: {
  item: DisplayMessage;
  onOpenImage: (uri: string) => void;
  onOpenVideo: (params: { uri: string; fileName?: string }) => void;
  onOpenFile: (params: { uri: string; fileName: string }) => void;
  onOpenActionMenu?: (
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
  /** 点击对方头像 → 资料页 */
  onPressAudienceAvatar?: () => void;
  actorAvatarUrl?: string;
  audienceAvatarUrl?: string;
  /** 与会话列表同一套 audience 默认头像底色 */
  audienceAvatarColor?: string;
  actorNickname?: string;
  audienceNickname?: string;
}) {
  const mine = item.mine;
  const avatarUrl = mine ? actorAvatarUrl : audienceAvatarUrl;
  const fallbackText = mine ? actorNickname : audienceNickname;
  const fallbackColor = mine ? '#07C160' : (audienceAvatarColor?.trim() || '#E8A598');
  const bubbleRef = useRef<View>(null);
  const canOpenMenu =
    !!onOpenActionMenu &&
    ((item.kind === 'text' && !!item.text) || (item.kind === 'image' && !!item.imageUrl));
  const isMediaBubble = item.kind === 'image' || item.kind === 'video';
  const bubbleColor = mine ? ChatType.color.bubbleMine : ChatType.color.bubblePeer;
  const showTail = !isMediaBubble;

  const resolveMenuKind = useCallback((): 'text' | 'image' | 'sticker' => {
    if (item.kind === 'image' && item.isEmojiSticker) return 'sticker';
    if (item.kind === 'image') return 'image';
    return 'text';
  }, [item]);

  const openMenuAtBubble = useCallback(
    (cursor?: { x: number; y: number }) => {
      if (!canOpenMenu || !onOpenActionMenu) return;
      const kind = resolveMenuKind();
      const content = item.kind === 'image' ? item.imageUrl : item.text;
      if (!content) return;
      bubbleRef.current?.measureInWindow((x, y, width, height) => {
        onOpenActionMenu(kind, content, { x, y, width, height }, {
          ...(cursor ? { cursorX: cursor.x, cursorY: cursor.y } : null),
          ...(item.kind === 'image'
            ? { imageWidth: item.imageWidth, imageHeight: item.imageHeight }
            : null),
        });
      });
    },
    [canOpenMenu, item, onOpenActionMenu, resolveMenuKind],
  );

  const handleContextMenu = useCallback(
    (e: { preventDefault?: () => void; nativeEvent?: { clientX?: number; clientY?: number; preventDefault?: () => void } }) => {
      if (!canOpenMenu) return;
      e?.preventDefault?.();
      e?.nativeEvent?.preventDefault?.();
      const cx = e?.nativeEvent?.clientX;
      const cy = e?.nativeEvent?.clientY;
      openMenuAtBubble(
        typeof cx === 'number' && typeof cy === 'number' ? { x: cx, y: cy } : undefined,
      );
    },
    [canOpenMenu, openMenuAtBubble],
  );

  return (
    <View style={[r.msgRow, mine ? r.userWrap : r.agentWrap]}>
      {!mine ? (
        <MessageAvatar
          url={avatarUrl}
          fallbackColor={fallbackColor}
          fallbackText={fallbackText}
          onPress={onPressAudienceAvatar}
        />
      ) : null}
      <View style={r.bubbleCol}>
        <View style={[r.bubbleWrap, mine ? r.bubbleWrapSelf : r.bubbleWrapPeer]}>
          {mine ? <SendingStatusIndicator status={item.status} sendTime={item.time} /> : null}
          {mine && item.status === 'failed' ? (
            <View style={r.sendStatus}>
              <Text style={[r.metaText, { color: '#D4565F' }]}>发送失败</Text>
            </View>
          ) : null}
          {showTail && !mine ? <BubbleTail side="left" color={bubbleColor} /> : null}
          <View style={[r.bubbleStack, mine ? r.bubbleStackMine : r.bubbleStackPeer]}>
            <Pressable
              ref={bubbleRef}
              onLongPress={canOpenMenu ? () => openMenuAtBubble() : undefined}
              delayLongPress={300}
              // @ts-expect-error RN Web 右键菜单
              onContextMenu={Platform.OS === 'web' && canOpenMenu ? handleContextMenu : undefined}
              style={[
                r.bubble,
                mine ? r.userBubble : r.agentBubble,
                isMediaBubble && r.imageBubble,
                item.kind === 'voice' && r.voiceBubble,
                (item.kind === 'file' || item.kind === 'location') && r.fileBubble,
              ]}
            >
            {item.kind === 'image' ? (
              item.imageUrl ? (
                <ChatImageBubble
                  uri={item.imageUrl}
                  presetWidth={item.imageWidth}
                  presetHeight={item.imageHeight}
                  isEmojiSticker={item.isEmojiSticker}
                  mine={mine}
                  onPress={() => onOpenImage(item.imageUrl)}
                  onLongPress={canOpenMenu ? () => openMenuAtBubble() : undefined}
                  onContextMenu={canOpenMenu ? handleContextMenu : undefined}
                />
              ) : (
                <Text style={[r.bubbleText, { color: mine ? ChatType.color.onPrimary : ChatType.color.text }]}>[图片]</Text>
              )
            ) : item.kind === 'video' ? (
              item.videoUrl || item.snapshotUrl ? (
                <ChatVideoBubble
                  snapshotUrl={item.snapshotUrl}
                  duration={item.duration}
                  snapshotWidth={item.snapshotWidth}
                  snapshotHeight={item.snapshotHeight}
                  onPress={() => onOpenVideo({ uri: item.videoUrl, fileName: undefined })}
                />
              ) : (
                <Text style={[r.bubbleText, { color: mine ? ChatType.color.onPrimary : ChatType.color.text }]}>[视频]</Text>
              )
            ) : item.kind === 'voice' ? (
              item.voiceUrl ? (
                <ChatVoiceBubble duration={item.duration} voiceUrl={item.voiceUrl} mine={mine} />
              ) : (
                <Text style={[r.bubbleText, { color: mine ? ChatType.color.onPrimary : ChatType.color.text }]}>[语音]</Text>
              )
            ) : item.kind === 'file' ? (
              item.fileUrl || item.fileName ? (
                <ChatFileBubble
                  fileName={item.fileName}
                  fileSize={item.fileSize}
                  mine={mine}
                  sending={item.status === 'sending'}
                  onPress={() => onOpenFile({ uri: item.fileUrl, fileName: item.fileName })}
                />
              ) : (
                <Text style={[r.bubbleText, { color: mine ? ChatType.color.onPrimary : ChatType.color.text }]}>[文件]</Text>
              )
            ) : item.kind === 'location' ? (
              Number.isFinite(item.latitude) && Number.isFinite(item.longitude) ? (
                <ChatLocationBubble
                  description={item.description}
                  latitude={item.latitude}
                  longitude={item.longitude}
                  mine={mine}
                />
              ) : (
                <Text style={[r.bubbleText, { color: mine ? ChatType.color.onPrimary : ChatType.color.text }]}>[位置]</Text>
              )
            ) : (
              <EmojiText
                text={item.text}
                color={mine ? ChatType.color.onPrimary : ChatType.color.text}
                textStyle={r.bubbleText}
              />
            )}
            </Pressable>
            {item.quote?.text ? <QuoteSnippet text={item.quote.text} mine={mine} /> : null}
          </View>
          {showTail && mine ? <BubbleTail side="right" color={bubbleColor} /> : null}
        </View>
      </View>
      {mine ? (
        <MessageAvatar url={avatarUrl} fallbackColor={fallbackColor} fallbackText={fallbackText} />
      ) : null}
    </View>
  );
});

const r = StyleSheet.create({
  timeCell: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 10,
  },
  timeCellText: {
    fontSize: ChatType.size.timestamp,
    lineHeight: ChatType.lineHeight.timestamp,
    fontWeight: ChatType.weight.regular,
    color: ChatType.color.timestamp,
  },
  msgRow: { flexDirection: 'row', alignItems: 'flex-start', marginVertical: 6, gap: 8 },
  agentWrap: { justifyContent: 'flex-start' },
  userWrap: { justifyContent: 'flex-end' },
  avatar: {
    width: 36,
    height: 36,
    borderRadius: 6,
    flexShrink: 0,
    marginTop: 2,
  },
  avatarImage: {
    width: '100%',
    height: '100%',
  },
  avatarFallback: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarFallbackText: {
    color: '#FFF',
    fontSize: 16,
    fontWeight: '600',
  },
  bubbleCol: {
    maxWidth: '72%',
    flexShrink: 1,
  },
  bubbleWrap: {
    flexDirection: 'row',
    alignItems: 'flex-start',
  },
  bubbleWrapSelf: {
    justifyContent: 'flex-end',
  },
  bubbleWrapPeer: {
    justifyContent: 'flex-start',
  },
  bubbleStack: {
    flexShrink: 1,
    maxWidth: '100%',
    gap: 4,
  },
  bubbleStackMine: {
    alignItems: 'flex-end',
  },
  bubbleStackPeer: {
    alignItems: 'flex-start',
  },
  quoteBox: {
    maxWidth: '100%',
    paddingVertical: 2,
  },
  quoteBoxPeer: {
    paddingLeft: 8,
    borderLeftWidth: 2,
    borderLeftColor: ChatType.color.subLabel,
  },
  quoteBoxMine: {
    paddingRight: 8,
    borderRightWidth: 2,
    borderRightColor: ChatType.color.subLabel,
  },
  quoteText: {
    fontSize: ChatType.size.hint,
    lineHeight: ChatType.lineHeight.subLabel,
    fontWeight: ChatType.weight.regular,
    color: ChatType.color.subLabel,
  },
  quoteOverlay: {
    ...StyleSheet.absoluteFillObject,
  },
  quotePopWrap: {
    position: 'absolute',
  },
  quotePopWrapHori: {
    flexDirection: 'row',
    alignItems: 'flex-start',
  },
  quotePopWrapVert: {
    flexDirection: 'column',
    alignItems: 'flex-start',
  },
  quotePop: {
    backgroundColor: ChatType.color.bubblePeer,
    borderRadius: ChatType.radius.bubble,
    paddingHorizontal: 12,
    paddingVertical: 8,
    overflow: 'hidden',
    shadowColor: '#2C2F35',
    shadowOpacity: 0.14,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 4 },
    elevation: 6,
  },
  quotePopText: {
    fontSize: ChatType.size.bubble,
    lineHeight: ChatType.lineHeight.bubble,
    fontWeight: ChatType.weight.regular,
  },
  quoteCaretLeft: {
    width: 0,
    height: 0,
    borderTopWidth: QUOTE_CARET,
    borderBottomWidth: QUOTE_CARET,
    borderTopColor: 'transparent',
    borderBottomColor: 'transparent',
    borderRightWidth: QUOTE_CARET,
    borderRightColor: ChatType.color.bubblePeer,
  },
  quoteCaretRight: {
    width: 0,
    height: 0,
    borderTopWidth: QUOTE_CARET,
    borderBottomWidth: QUOTE_CARET,
    borderTopColor: 'transparent',
    borderBottomColor: 'transparent',
    borderLeftWidth: QUOTE_CARET,
    borderLeftColor: ChatType.color.bubblePeer,
  },
  quoteCaretUp: {
    width: 0,
    height: 0,
    borderLeftWidth: QUOTE_CARET,
    borderRightWidth: QUOTE_CARET,
    borderLeftColor: 'transparent',
    borderRightColor: 'transparent',
    borderBottomWidth: QUOTE_CARET,
    borderBottomColor: ChatType.color.bubblePeer,
  },
  quoteCaretDown: {
    width: 0,
    height: 0,
    borderLeftWidth: QUOTE_CARET,
    borderRightWidth: QUOTE_CARET,
    borderLeftColor: 'transparent',
    borderRightColor: 'transparent',
    borderTopWidth: QUOTE_CARET,
    borderTopColor: ChatType.color.bubblePeer,
  },
  tail: {
    width: 0,
    height: 0,
    marginTop: 10,
    borderTopWidth: 5,
    borderBottomWidth: 5,
    borderTopColor: 'transparent',
    borderBottomColor: 'transparent',
  },
  tailLeft: {
    borderRightWidth: 6,
    marginRight: -1,
  },
  tailRight: {
    borderLeftWidth: 6,
    marginLeft: -1,
  },
  bubble: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: ChatType.radius.bubble,
    flexShrink: 1,
  },
  imageBubble: {
    paddingHorizontal: 0,
    paddingVertical: 0,
    overflow: 'hidden',
    backgroundColor: 'transparent',
  },
  voiceBubble: {
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  voiceInner: {
    alignItems: 'center',
    gap: 8,
    minHeight: 22,
  },
  voiceDuration: {
    fontSize: ChatType.size.bubble,
    lineHeight: ChatType.lineHeight.bubble,
    fontWeight: ChatType.weight.regular,
  },
  fileBubble: {
    paddingHorizontal: 12,
    paddingVertical: 10,
    minWidth: 160,
  },
  fileInner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  fileIconWrap: {
    width: 36,
    height: 36,
    borderRadius: 4,
    alignItems: 'center',
    justifyContent: 'center',
  },
  fileIconMine: {
    backgroundColor: 'rgba(0,0,0,0.08)',
  },
  fileIconPeer: {
    backgroundColor: 'rgba(7,193,96,0.12)',
  },
  fileTextWrap: {
    flexShrink: 1,
    gap: 2,
  },
  fileName: {
    fontSize: ChatType.size.bubble,
    lineHeight: ChatType.lineHeight.bubble,
    fontWeight: ChatType.weight.medium,
  },
  fileSize: {
    fontSize: ChatType.size.hint,
    lineHeight: ChatType.lineHeight.subLabel,
    fontWeight: ChatType.weight.regular,
  },
  videoWrap: {
    position: 'relative',
    overflow: 'hidden',
    borderRadius: ChatType.radius.media,
  },
  videoPlaceholder: {
    backgroundColor: 'rgba(0,0,0,0.35)',
    borderRadius: ChatType.radius.media,
  },
  videoPlayOverlay: {
    ...StyleSheet.absoluteFillObject,
    alignItems: 'center',
    justifyContent: 'center',
  },
  videoPlayBtn: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: 'rgba(0,0,0,0.45)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  videoDurationBadge: {
    position: 'absolute',
    right: 8,
    bottom: 8,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
    backgroundColor: 'rgba(0,0,0,0.55)',
  },
  videoDurationText: {
    color: '#FFF',
    fontSize: 11,
    lineHeight: 14,
    fontWeight: '500',
  },
  agentBubble: { backgroundColor: ChatType.color.bubblePeer },
  userBubble: { backgroundColor: ChatType.color.bubbleMine },
  bubbleText: {
    fontSize: ChatType.size.bubble,
    lineHeight: ChatType.lineHeight.bubble,
    fontWeight: ChatType.weight.regular,
  },
  chatImage: { borderRadius: ChatType.radius.media, backgroundColor: 'rgba(0,0,0,0.06)' },
  chatImageEmoji: { borderRadius: ChatType.radius.media },
  emojiStickerWrap: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    alignSelf: 'flex-start',
    gap: 5,
  },
  emojiStickerBadge: {
    width: 16,
    height: 16,
    alignItems: 'center',
    justifyContent: 'center',
  },
  sendStatus: {
    alignSelf: 'flex-end',
    marginRight: 4,
    marginBottom: 4,
  },
  metaText: {
    fontSize: ChatType.size.timestamp,
    fontWeight: ChatType.weight.regular,
    color: ChatType.color.timestamp,
  },
});
