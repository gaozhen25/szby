import {
  forwardRef,
  memo,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
} from 'react';
import { Avatar, Button, Flex, Image, Listy, Slider, Spin, Tooltip, Typography } from 'antd';
import type { ListyRef } from 'antd';
import { LOAD_MORE_HEADER_HEIGHT, useChatListController, type ChatMessageListHandle } from '@/chatMessage/list';
import { computeChatImageDisplaySize } from '@/chatMessage/message/chat-image-size';
import { buildChatListItems, type ChatListItem, type DisplayMessage } from '@/chatMessage/message/chat-message-model';
import { useDelayedSendingIndicator } from '@/chatMessage/message/useDelayedSendingIndicator';
import type { MessageActionKind } from '@/chatMessage/components/MessageActionMenu.types';
import { formatTaskTriggerTime, formatTaskTriggerTimeFull } from '@/lib/task-session-list';
import { playVoiceUrl } from '@/chatMessage/message/voice-player';
import { formatFileSize } from '@/core/im/file-message';
import { formatVideoDurationLabel } from '@/core/im/video-message';
import {
  CaretRightFilled,
  EnvironmentOutlined,
  FileExcelFilled,
  FileImageFilled,
  FilePdfFilled,
  FilePptFilled,
  FileTextOutlined,
  FileWordFilled,
  FileZipFilled,
  PauseOutlined,
  PlayCircleFilled,
  ReloadOutlined,
} from '@/ui/web/antd-icons';
import { EmojiText } from '@/chatMessage/components/EmojiText';
import { openChatLocation } from '@/chatMessage/message/open-location';
import { appAlert } from '@/lib/app-alert';
import { chromeCssVars } from '@/ui/web/chrome-theme';
import { webColor, webFontSize, webType } from '@/ui/web/theme';
import { quoteHoverBody } from '@/core/im/quote-message';
import { formatLocationCoordLabel } from '@/core/im/location-message';

function findOverflowScroll(root: HTMLElement): HTMLElement {
  const queue: HTMLElement[] = [root];
  while (queue.length) {
    const el = queue.shift()!;
    const overflowY =
      el.style.overflowY || (typeof window !== 'undefined' ? window.getComputedStyle(el).overflowY : '');
    if (overflowY === 'auto' || overflowY === 'scroll') return el;
    for (const child of Array.from(el.children)) {
      if (child instanceof HTMLElement) queue.push(child);
    }
  }
  return root;
}

const LOAD_MORE_KEY = '__load_more__';

type LoadMoreRow = { type: 'load-more'; key: typeof LOAD_MORE_KEY };
type ListyRow = ChatListItem | LoadMoreRow;

function WebChatImage({
  url,
  presetWidth,
  presetHeight,
  isEmojiSticker,
  onClick,
  onContextMenu,
}: {
  url: string;
  presetWidth?: number;
  presetHeight?: number;
  isEmojiSticker?: boolean;
  onClick: () => void;
  onContextMenu: (e: MouseEvent) => void;
}) {
  const size = computeChatImageDisplaySize(
    presetWidth,
    presetHeight,
    isEmojiSticker ? 'emoji' : 'image',
  );
  return (
    <Flex
      style={{
        width: size.width,
        height: size.height,
        overflow: 'hidden',
        borderRadius: 8,
        flexShrink: 0,
        background: webColor.imagePlaceholder,
      }}
    >
      <Image
        src={url}
        width={size.width}
        height={size.height}
        preview={false}
        style={{ width: size.width, height: size.height, objectFit: 'cover' }}
        onClick={onClick}
        onContextMenu={onContextMenu}
      />
    </Flex>
  );
}

function WebQuoteSnippet({ text, mine }: { text: string; mine: boolean }) {
  const hoverBody = quoteHoverBody(text);
  return (
    <Tooltip
      title={
        <div
          className="qh-chat-quote-tooltip-body"
          onWheel={(e) => e.stopPropagation()}
        >
          {hoverBody}
        </div>
      }
      placement={mine ? 'left' : 'right'}
      mouseEnterDelay={0.08}
      mouseLeaveDelay={0.18}
      arrow
      color={chromeCssVars.peerBubbleBg}
      classNames={{ root: 'qh-chat-quote-tooltip' }}
      styles={{
        container: {
          color: webColor.text,
          padding: '8px 6px 8px 12px',
          borderRadius: 10,
          boxShadow: '0 6px 16px rgba(44, 47, 53, 0.14)',
          fontSize: webFontSize.md,
          lineHeight: '20px',
          maxWidth: 280,
        },
      }}
      getPopupContainer={() => document.body}
    >
      <Flex
        className={`qh-chat-quote ${mine ? 'is-mine' : 'is-peer'}`}
        aria-label={`引用 ${text}`}
      >
        <Typography.Text
          ellipsis={{ rows: 2 }}
          style={{
            ...webType.subLabel,
            color: webColor.subLabel,
            fontSize: webFontSize.sm,
            lineHeight: '16px',
            display: 'block',
            maxWidth: '100%',
            cursor: 'default',
          }}
        >
          {text}
        </Typography.Text>
      </Flex>
    </Tooltip>
  );
}

function formatVoiceClock(sec: number): string {
  const s = Math.max(0, Math.round(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

function applyVoiceSeek(audio: HTMLAudioElement | null, time: number): void {
  if (!audio || !Number.isFinite(time) || time < 0) return;
  const seek = () => {
    const dur = Number.isFinite(audio.duration) ? audio.duration : time;
    audio.currentTime = Math.min(time, Math.max(0, dur));
  };
  if (audio.readyState >= 1) seek();
  else audio.addEventListener('loadedmetadata', seek, { once: true });
}

/** 语音气泡宽度（px）：最短、最长、基础宽、每秒加长 */
const VOICE_BUBBLE_MIN_WIDTH = 80;
const VOICE_BUBBLE_MAX_WIDTH = 200;
const VOICE_BUBBLE_BASE_WIDTH = 80;
const VOICE_BUBBLE_PX_PER_SEC = 10;

function WebChatVoice({
  duration,
  voiceUrl,
}: {
  duration: number;
  voiceUrl: string;
  mine: boolean;
}) {
  const [playing, setPlaying] = useState(false);
  const [current, setCurrent] = useState(0);
  const [total, setTotal] = useState(() => Math.max(0, duration));
  const pauseRef = useRef<(() => void) | null>(null);
  const stopRef = useRef<(() => void) | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const currentRef = useRef(0);
  const aliveRef = useRef(true);

  currentRef.current = current;

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
      stopRef.current?.();
      stopRef.current = null;
      pauseRef.current = null;
      audioRef.current = null;
    };
  }, []);

  const max = total > 0 ? total : Math.max(duration, 0.01);
  const bubbleWidth = Math.min(
    VOICE_BUBBLE_MAX_WIDTH,
    Math.max(VOICE_BUBBLE_MIN_WIDTH, VOICE_BUBBLE_BASE_WIDTH + Math.max(1, duration) * VOICE_BUBBLE_PX_PER_SEC),
  );

  const resetIdle = () => {
    if (!aliveRef.current) return;
    setPlaying(false);
    setCurrent(0);
    stopRef.current = null;
    pauseRef.current = null;
    audioRef.current = null;
  };

  const startPlayback = (seekTo?: number) => {
    if (!voiceUrl) return;
    const at = seekTo ?? currentRef.current;
    currentRef.current = at;
    setPlaying(true);
    const handle = playVoiceUrl(
      voiceUrl,
      resetIdle,
      (cur, dur) => {
        if (!aliveRef.current) return;
        setCurrent(cur);
        if (dur > 0) setTotal(dur);
      },
    );
    stopRef.current = handle.stop;
    pauseRef.current = handle.pause;
    audioRef.current = handle.audio;
    applyVoiceSeek(handle.audio, at);
  };

  const handlePlayPause = () => {
    if (!voiceUrl) return;
    if (playing) {
      pauseRef.current?.();
      setPlaying(false);
      return;
    }
    startPlayback();
  };

  const handleSeek = (value: number) => {
    const next = Array.isArray(value) ? value[0] : value;
    setCurrent(next);
    applyVoiceSeek(audioRef.current, next);
  };

  const handleSeekComplete = (value: number) => {
    const next = Array.isArray(value) ? value[0] : value;
    setCurrent(next);
    startPlayback(next);
  };

  return (
    <Flex
      className="qh-voice-player"
      align="center"
      style={{ width: bubbleWidth }}
      onPointerDown={(e) => e.stopPropagation()}
      onClick={(e) => e.stopPropagation()}
    >
      <Button
        type="text"
        shape="circle"
        size="small"
        className="qh-voice-play"
        aria-label={playing ? '暂停语音' : '播放语音'}
        icon={playing ? <PauseOutlined /> : <CaretRightFilled />}
        onClick={handlePlayPause}
      />
      <Slider
        className="qh-voice-slider"
        min={0}
        max={max}
        step={0.05}
        value={Math.min(current, max)}
        tooltip={{ open: false }}
        onChange={handleSeek}
        onChangeComplete={handleSeekComplete}
        styles={{
          handle: { width: 12, height: 12, insetBlockStart: 0 },
          rail: { height: 2, top: '50%', transform: 'translateY(-50%)', background: webColor.voiceRail },
          track: { height: 2, top: '50%', transform: 'translateY(-50%)', background: webColor.voice },
        }}
      />
      <Typography.Text className="qh-voice-time">
        {formatVoiceClock(Math.max(0, max - current))}
      </Typography.Text>
    </Flex>
  );
}

function WebChatVideo({
  snapshotUrl,
  duration,
  snapshotWidth,
  snapshotHeight,
  onClick,
}: {
  snapshotUrl: string;
  duration: number;
  snapshotWidth?: number;
  snapshotHeight?: number;
  onClick: () => void;
}) {
  const size = computeChatImageDisplaySize(snapshotWidth, snapshotHeight, 'image');
  return (
    <Button
      type="text"
      className="qh-chat-video"
      style={{ width: size.width, height: size.height }}
      aria-label={`播放视频 ${formatVideoDurationLabel(duration)}`}
      onClick={onClick}
    >
      {snapshotUrl ? (
        <Image
          className="qh-chat-video-cover"
          src={snapshotUrl}
          alt=""
          preview={false}
          width={size.width}
          height={size.height}
        />
      ) : null}
      <Flex className="qh-chat-video-play" align="center" justify="center">
        <PlayCircleFilled />
      </Flex>
      <Typography.Text className="qh-chat-video-duration">
        {formatVideoDurationLabel(duration)}
      </Typography.Text>
    </Button>
  );
}

function fileIconMeta(fileName: string): {
  kind: 'pdf' | 'word' | 'excel' | 'ppt' | 'zip' | 'image' | 'file';
  Icon: typeof FileTextOutlined;
} {
  const dot = fileName.lastIndexOf('.');
  const ext = dot >= 0 ? fileName.slice(dot + 1).toLowerCase() : '';
  if (ext === 'pdf') return { kind: 'pdf', Icon: FilePdfFilled };
  if (ext === 'doc' || ext === 'docx') return { kind: 'word', Icon: FileWordFilled };
  if (ext === 'xls' || ext === 'xlsx' || ext === 'csv') return { kind: 'excel', Icon: FileExcelFilled };
  if (ext === 'ppt' || ext === 'pptx') return { kind: 'ppt', Icon: FilePptFilled };
  if (ext === 'zip' || ext === 'rar' || ext === '7z') return { kind: 'zip', Icon: FileZipFilled };
  if (ext === 'png' || ext === 'jpg' || ext === 'jpeg' || ext === 'gif' || ext === 'webp' || ext === 'bmp' || ext === 'heic') {
    return { kind: 'image', Icon: FileImageFilled };
  }
  return { kind: 'file', Icon: FileTextOutlined };
}

function WebChatFile({
  fileName,
  fileSize,
  mine,
  sending,
  onClick,
}: {
  fileName: string;
  fileSize: number;
  mine: boolean;
  sending?: boolean;
  onClick: () => void;
}) {
  const sizeLabel = formatFileSize(fileSize);
  const { kind, Icon } = fileIconMeta(fileName);
  return (
    <Button
      type="text"
      className={`qh-chat-file ${mine ? 'is-mine' : 'is-peer'}`}
      aria-label={`打开文件 ${fileName || '文件'}`}
      disabled={sending}
      onClick={onClick}
    >
      <Flex className={`qh-chat-file-icon is-${kind}`} align="center" justify="center">
        <Icon />
      </Flex>
      <Flex vertical className="qh-chat-file-meta">
        <Typography.Text className="qh-chat-file-name">{fileName || '文件'}</Typography.Text>
        {sizeLabel ? <Typography.Text className="qh-chat-file-size">{sizeLabel}</Typography.Text> : null}
      </Flex>
    </Button>
  );
}

function WebChatLocation({
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
  const title = description.trim() || '位置';
  const coordLabel = formatLocationCoordLabel(latitude, longitude);
  return (
    <Button
      type="text"
      className={`qh-chat-file ${mine ? 'is-mine' : 'is-peer'}`}
      aria-label={`查看位置 ${title}`}
      onClick={() => {
        void openChatLocation({ latitude, longitude, description: title }).catch((e) => {
          appAlert('无法打开地图', e instanceof Error ? e.message : '请稍后重试');
        });
      }}
    >
      <Flex className="qh-chat-file-icon is-file" align="center" justify="center">
        <EnvironmentOutlined />
      </Flex>
      <Flex vertical className="qh-chat-file-meta">
        <Typography.Text className="qh-chat-file-name">{title}</Typography.Text>
        {coordLabel ? <Typography.Text className="qh-chat-file-size">{coordLabel}</Typography.Text> : null}
      </Flex>
    </Button>
  );
}

function WebChatTime({ time }: { time: number }) {
  const [full, setFull] = useState(false);
  const label = full
    ? formatTaskTriggerTimeFull(time)
    : formatTaskTriggerTime(time, { withClockForOlder: true });
  if (!label) return null;
  return (
    <Flex justify="center" className="qh-chat-time">
      <button
        type="button"
        className="qh-chat-time-btn"
        aria-label={full ? '收起时间' : '显示完整时间'}
        onClick={() => setFull((v) => !v)}
      >
        {label}
      </button>
    </Flex>
  );
}

function ChatMessageStatusHint({
  status,
  mine,
  sendTime,
}: {
  status?: DisplayMessage['status'];
  mine: boolean;
  sendTime: number;
}) {
  const showSending = useDelayedSendingIndicator(status, sendTime);
  if (!mine || (status !== 'sending' && status !== 'failed')) return null;
  if (status === 'sending') {
    if (!showSending) return null;
    return (
      <ReloadOutlined
        spin
        aria-label="发送中"
        style={{
          color: webColor.timestamp,
          fontSize: 12,
          flexShrink: 0,
        }}
      />
    );
  }
  return (
    <Typography.Text
      style={{
        ...webType.timestamp,
        color: webColor.danger,
        fontSize: 12,
        lineHeight: '16px',
        flexShrink: 0,
      }}
    >
      发送失败
    </Typography.Text>
  );
}

export const WebChatMessageList = memo(forwardRef<
  ChatMessageListHandle,
  {
    loading: boolean;
    messages: DisplayMessage[];
    loadingMore: boolean;
    hasMoreBefore: boolean;
    onLoadOlder: () => void;
    onDismissComposer?: () => void;
    onOpenImage: (uri: string) => void;
    onOpenVideo: (params: { uri: string; fileName?: string }) => void;
    onOpenFile: (params: { uri: string; fileName: string }) => void;
    onOpenActionMenu: (
      kind: MessageActionKind,
      content: string,
      rect: { x: number; y: number; width: number; height: number },
      opts?: { cursorX?: number; cursorY?: number; imageWidth?: number; imageHeight?: number },
    ) => void;
    onPressAudienceAvatar: () => void;
    actorAvatarUrl?: string;
    audienceAvatarUrl?: string;
    audienceAvatarColor?: string;
    actorNickname?: string;
    audienceNickname?: string;
  }
>(function WebChatMessageList(props, ref) {
  const wrapRef = useRef<HTMLElement | null>(null);
  const viewportRef = useRef<HTMLElement | null>(null);
  const scrollNodeRef = useRef<HTMLElement | null>(null);
  const listyRef = useRef<ListyRef>(null);
  const rowRefs = useRef(new Map<string, HTMLElement>());
  const [height, setHeight] = useState(480);

  useEffect(() => {
    const el = viewportRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => setHeight(Math.max(120, el.clientHeight)));
    ro.observe(el);
    setHeight(Math.max(120, el.clientHeight));
    return () => ro.disconnect();
  }, []);

  const readNode = useCallback((): HTMLElement | null => {
    if (scrollNodeRef.current?.isConnected) {
      scrollNodeRef.current.style.overflowAnchor = 'none';
      return scrollNodeRef.current;
    }
    const root = wrapRef.current;
    if (!root) return null;
    const node = findOverflowScroll(root);
    scrollNodeRef.current = node;
    node.style.overflowAnchor = 'none';
    return node;
  }, []);

  const port = {
    readNode,
    scrollToEnd: (opts: { animated: boolean }) => {
      const items = buildChatListItems(props.messages);
      const last = items[items.length - 1];
      if (last) listyRef.current?.scrollTo({ key: last.key, align: 'bottom' });
      void opts;
    },
    scrollToY: (y: number) => {
      listyRef.current?.scrollTo(y);
    },
    scrollAnchorToViewport: (anchorKey: string, viewportY: number) => {
      listyRef.current?.scrollTo({ key: anchorKey, align: 'top', offset: viewportY });
      const node = readNode();
      if (node && Number.isFinite(node.scrollTop)) {
        scrollNodeRef.current = node;
      }
    },
    measureAnchorViewportY: (anchorKey: string): number | null => {
      const row = rowRefs.current.get(anchorKey);
      const list = readNode();
      if (!row || !list) return null;
      return row.getBoundingClientRect().top - list.getBoundingClientRect().top;
    },
  };

  const list = useChatListController({
    isWeb: true,
    inverted: false,
    loading: props.loading,
    loadingMore: props.loadingMore,
    hasMoreBefore: props.hasMoreBefore,
    messages: props.messages,
    onLoadOlder: props.onLoadOlder,
    onDismissComposer: props.onDismissComposer,
    port,
  });

  useImperativeHandle(ref, () => list.handle, [list.handle]);

  const listyItems = useMemo<ListyRow[]>(() => {
    if (props.hasMoreBefore || props.loadingMore) {
      return [{ type: 'load-more', key: LOAD_MORE_KEY }, ...list.listItems];
    }
    return list.listItems;
  }, [list.listItems, props.hasMoreBefore, props.loadingMore]);

  const bindWrap = (node: unknown) => {
    const el =
      node instanceof HTMLElement
        ? node
        : node && typeof node === 'object' && 'nativeElement' in node
          ? ((node as { nativeElement?: HTMLElement }).nativeElement ?? null)
          : null;
    wrapRef.current = el;
  };

  const renderItem = (item: ListyRow) => {
    if (item.type === 'load-more') {
      return (
        <Flex
          align="center"
          justify="center"
          style={{ height: LOAD_MORE_HEADER_HEIGHT, cursor: props.loadingMore ? 'default' : 'pointer' }}
          onClick={() => {
            if (!props.loadingMore) list.tryLoadOlder();
          }}
        >
          {props.loadingMore ? (
            <Flex align="center" gap={6}>
              <Spin size="small" />
              <Typography.Text type="secondary" style={webType.hint}>
                加载更早消息…
              </Typography.Text>
            </Flex>
          ) : (
            <Typography.Text type="secondary" style={webType.hint}>
              点击或上滑加载更早消息
            </Typography.Text>
          )}
        </Flex>
      );
    }
    if (item.type === 'time') {
      return <WebChatTime time={item.time} />;
    }
    const msg = item.message;
    const mine = msg.mine;
    const letter = mine
      ? (props.actorNickname || '我').charAt(0)
      : (props.audienceNickname || '用').charAt(0);
    const avatarUrl = mine ? props.actorAvatarUrl : props.audienceAvatarUrl;

    const bubble = (() => {
      if (msg.kind === 'text') {
        return (
          <Flex
            style={{
              maxWidth: 560,
              padding: '8px 12px',
              borderRadius: 10,
              background: mine ? chromeCssVars.mineBubbleBg : chromeCssVars.peerBubbleBg,
              color: mine ? chromeCssVars.mineBubbleFg : webColor.text,
            }}
            onContextMenu={(e) => {
              e.preventDefault();
              const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
              props.onOpenActionMenu('text', msg.text, r, { cursorX: e.clientX, cursorY: e.clientY });
            }}
          >
            <EmojiText
              text={msg.text}
              color={mine ? chromeCssVars.mineBubbleFg : webColor.text}
            />
          </Flex>
        );
      }
      if (msg.kind === 'image') {
        return (
          <WebChatImage
            url={msg.imageUrl}
            presetWidth={msg.imageWidth}
            presetHeight={msg.imageHeight}
            isEmojiSticker={msg.isEmojiSticker}
            onClick={() => props.onOpenImage(msg.imageUrl)}
            onContextMenu={(e) => {
              e.preventDefault();
              const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
              props.onOpenActionMenu(
                msg.isEmojiSticker ? 'sticker' : 'image',
                msg.imageUrl,
                r,
                {
                  cursorX: e.clientX,
                  cursorY: e.clientY,
                  imageWidth: msg.imageWidth,
                  imageHeight: msg.imageHeight,
                },
              );
            }}
          />
        );
      }
      if (msg.kind === 'voice') {
        if (!msg.voiceUrl) {
          return (
            <Flex
              style={{
                padding: '8px 12px',
                borderRadius: 10,
                background: mine ? chromeCssVars.mineBubbleBg : chromeCssVars.peerBubbleBg,
              }}
            >
              <Typography.Text style={{ color: mine ? chromeCssVars.mineBubbleFg : webColor.text }}>[语音]</Typography.Text>
            </Flex>
          );
        }
        return <WebChatVoice duration={msg.duration} voiceUrl={msg.voiceUrl} mine={mine} />;
      }
      if (msg.kind === 'video') {
        return (
          <WebChatVideo
            snapshotUrl={msg.snapshotUrl}
            duration={msg.duration}
            snapshotWidth={msg.snapshotWidth}
            snapshotHeight={msg.snapshotHeight}
            onClick={() => {
              if (msg.videoUrl) props.onOpenVideo({ uri: msg.videoUrl, fileName: '视频' });
            }}
          />
        );
      }
      if (msg.kind === 'location') {
        if (!Number.isFinite(msg.latitude) || !Number.isFinite(msg.longitude)) {
          return (
            <Flex
              style={{
                padding: '8px 12px',
                borderRadius: 10,
                background: mine ? chromeCssVars.mineBubbleBg : chromeCssVars.peerBubbleBg,
              }}
            >
              <Typography.Text style={{ color: mine ? chromeCssVars.mineBubbleFg : webColor.text }}>[位置]</Typography.Text>
            </Flex>
          );
        }
        return (
          <WebChatLocation
            description={msg.description}
            latitude={msg.latitude}
            longitude={msg.longitude}
            mine={mine}
          />
        );
      }
      if (msg.kind === 'file') {
        return (
          <WebChatFile
            fileName={msg.fileName}
            fileSize={msg.fileSize}
            mine={mine}
            sending={msg.status === 'sending'}
            onClick={() => {
              if (msg.status === 'sending') return;
              if (msg.fileUrl) props.onOpenFile({ uri: msg.fileUrl, fileName: msg.fileName });
            }}
          />
        );
      }
      return (
        <Flex
          style={{
            padding: '8px 12px',
            borderRadius: 10,
            background: mine ? chromeCssVars.mineBubbleBg : chromeCssVars.peerBubbleBg,
          }}
        >
          <Typography.Text style={{ color: mine ? chromeCssVars.mineBubbleFg : webColor.text }}>[消息]</Typography.Text>
        </Flex>
      );
    })();

    return (
      <Flex
        ref={(node) => {
          const el =
            node instanceof HTMLElement
              ? node
              : node && typeof node === 'object' && 'nativeElement' in (node as object)
                ? (node as { nativeElement?: HTMLElement }).nativeElement
                : null;
          if (el) rowRefs.current.set(item.key, el);
          else rowRefs.current.delete(item.key);
        }}
        justify={mine ? 'flex-end' : 'flex-start'}
        gap={8}
        style={{ padding: '6px 12px' }}
      >
        {mine ? null : (
          <Avatar
            src={avatarUrl || undefined}
            style={{
              // cursor: 'pointer', // TODO: 资料弹窗接入后恢复
              background: props.audienceAvatarColor || undefined,
              color: webColor.onPrimary,
              border: 'none',
            }}
            // onClick={props.onPressAudienceAvatar} // TODO: 资料弹窗接入后恢复
            onClick={undefined}
          >
            {letter}
          </Avatar>
        )}
        <Flex vertical align={mine ? 'flex-end' : 'flex-start'} gap={4} style={{ maxWidth: 'min(560px, 72%)', minWidth: 0 }}>
          <Flex
            align="flex-end"
            gap={4}
            className={`qh-chat-bubble-cluster${mine ? ' is-mine' : ' is-peer'}`}
            style={{ maxWidth: '100%' }}
          >
            <ChatMessageStatusHint status={msg.status} mine={mine} sendTime={msg.time} />
            <div className="qh-chat-bubble-wrap">{bubble}</div>
            {msg.time ? (
              <span className="qh-chat-bubble-hover-time">
                {formatTaskTriggerTime(msg.time, { withClockForOlder: true })}
              </span>
            ) : null}
          </Flex>
          {msg.quote?.text ? <WebQuoteSnippet text={msg.quote.text} mine={mine} /> : null}
        </Flex>
        {mine ? <Avatar src={avatarUrl || undefined}>{letter}</Avatar> : null}
      </Flex>
    );
  };

  return (
    <Flex
      ref={bindWrap as never}
      vertical
      flex={1}
      style={{ minHeight: 0, minWidth: 0, width: '100%', height: '100%', position: 'relative', background: chromeCssVars.chatPaneBg }}
      onWheel={(e) => list.handleWheel({ deltaY: e.deltaY })}
    >
      <Flex ref={viewportRef} vertical flex={1} style={{ minHeight: 0, minWidth: 0, width: '100%' }}>
        <Listy<ListyRow>
          ref={listyRef}
          items={listyItems}
          rowKey="key"
          height={height}
          virtual={false}
          itemRender={renderItem}
          onScroll={(e) => {
            const t = e.currentTarget as unknown as HTMLElement;
            const y = t.scrollTop ?? 0;
            if (t) scrollNodeRef.current = t;
            list.handleListScroll({
              nativeEvent: {
                contentOffset: { y },
                contentSize: { height: t.scrollHeight },
                layoutMeasurement: { height: t.clientHeight },
              },
            });
          }}
        />
      </Flex>
      {list.showCover ? (
        <Flex
          align="center"
          justify="center"
          style={{ position: 'absolute', inset: 0, background: chromeCssVars.chatPaneBg, zIndex: 2 }}
        >
          <Spin />
        </Flex>
      ) : null}
    </Flex>
  );
}));
