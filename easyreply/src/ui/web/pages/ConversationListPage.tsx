import { Alert, Avatar, Badge, Button, Checkbox, Dropdown, Empty, Flex, Input, Spin, Typography } from 'antd';
import {
  CheckCircleOutlined,
  DeleteOutlined,
  EllipsisOutlined,
  MessageOutlined,
  ReloadOutlined,
  SearchOutlined,
  StarFilled,
  StarOutlined,
  TeamOutlined,
} from '@/ui/web/antd-icons';
import {
  memo,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
} from 'react';
import { router, useLocalSearchParams } from 'expo-router';
import { hasConversationAdoptionReview, hasConversationProactiveHint, type MockConversation } from '@/mock/data';
import { conversationChatRouteParams, prefetchConversationChatCache } from '@/features/conversations/conversation-chat-params';
import {
  conversationFavoriteKey,
  conversationRowKey,
  useConversationList,
} from '@/features/conversations/useConversationList';
import {
  conversationAudienceLabel,
  type ConversationActor,
} from '@/features/conversations/conversation-actors';
import { BatchCompleteConfirmModal } from '@/features/conversations/BatchCompleteConfirmModal';
import { FavoritesModal } from '@/features/conversations/FavoritesModal.web';
import { TransferAgentPicker } from '@/features/conversations/TransferAgentPicker';
import { ChatRoomPane } from '@/ui/web/pages/ChatRoomPage';
import { WebOverlayScroll } from '@/ui/web/chat/WebOverlayScroll';
import { WebPaneResizeHandle } from '@/ui/web/WebPaneResizeHandle';
import { chromeCssVars } from '@/ui/web/chrome-theme';
import { webColor, webFontSize, webLayout, webType } from '@/ui/web/theme';
import { EmojiText } from '@/chatMessage/components/EmojiText';
import {
  getChatListView,
  setChatListView,
  subscribeChatListView,
} from '@/lib/chat-list-view-bus';
import { setSiderActorBrand, getSiderActorBrand } from '@/lib/sider-actor-brand-bus';

/** 点开会话时路由 params 可能重绘列表，用模块级位置避免滚回顶部 */
let savedConvListScrollTop = 0;

/** 视口外额外渲染的行数，滚动时不至于露白 */
const CONV_ROW_OVERSCAN = 12;
/** 分栏尚未撑开时不要把窗口掐成 6 行；至少按一屏会话列表来算 */
const MIN_CONV_VIEWPORT_HEIGHT = 480;

/**
 * 会话列表窗口化：数百个会话时只渲染视口内的行。
 * 行高由 CSS 固定为 webLayout.convRowHeight，因此偏移可直接按 index 计算。
 */
function useConversationWindow(
  scroller: HTMLElement | null,
  total: number,
): { start: number; end: number; onScroll: () => void } {
  const [viewport, setViewport] = useState({ top: 0, height: MIN_CONV_VIEWPORT_HEIGHT });
  const frameRef = useRef<number | null>(null);
  const scrollerRef = useRef(scroller);
  scrollerRef.current = scroller;

  const sync = useCallback(() => {
    const el = scrollerRef.current;
    if (!el) return;
    const top = el.scrollTop;
    const measured = el.clientHeight || el.getBoundingClientRect().height;
    setViewport((prev) => {
      // 高度尚未撑开时仍要跟上 scrollTop，否则滚下去窗口停在第一页 + overscan
      const height = measured > 1 ? measured : prev.height;
      if (prev.top === top && prev.height === height) return prev;
      return { top, height };
    });
  }, []);

  const scheduleSync = useCallback(() => {
    if (frameRef.current != null) return;
    frameRef.current = requestAnimationFrame(() => {
      frameRef.current = null;
      sync();
    });
  }, [sync]);

  useEffect(() => {
    return () => {
      if (frameRef.current != null) cancelAnimationFrame(frameRef.current);
    };
  }, []);

  // 滚动容器从空态挂上、或下班→上班列表变长时必须重新观察，不能只在首次 effect 绑一次
  useEffect(() => {
    if (!scroller) return;
    const onScroll = () => scheduleSync();
    scroller.addEventListener('scroll', onScroll, { passive: true });
    let ro: ResizeObserver | undefined;
    if (typeof ResizeObserver !== 'undefined') {
      ro = new ResizeObserver(scheduleSync);
      ro.observe(scroller);
      if (scroller.parentElement) ro.observe(scroller.parentElement);
    }
    sync();
    return () => {
      scroller.removeEventListener('scroll', onScroll);
      ro?.disconnect();
    };
  }, [scroller, scheduleSync, sync]);

  useLayoutEffect(() => {
    sync();
    // flex 分栏要等一到两帧才有最终 clientHeight，避免窗口行数卡在偏小值
    let inner = 0;
    const outer = requestAnimationFrame(() => {
      sync();
      inner = requestAnimationFrame(sync);
    });
    return () => {
      cancelAnimationFrame(outer);
      cancelAnimationFrame(inner);
    };
  }, [sync, total, scroller]);

  const rowHeight = webLayout.convRowHeight;
  const viewportHeight = Math.max(viewport.height, MIN_CONV_VIEWPORT_HEIGHT);
  const start = Math.max(0, Math.floor(viewport.top / rowHeight) - CONV_ROW_OVERSCAN);
  const end = Math.min(
    total,
    Math.ceil((viewport.top + viewportHeight) / rowHeight) + CONV_ROW_OVERSCAN,
  );

  return { start, end: Math.max(start, end), onScroll: scheduleSync };
}

function paramStr(value?: string | string[]): string | undefined {
  if (Array.isArray(value)) return value[0];
  return value || undefined;
}

function bannerText(mode: string): string {
  if (mode === 'offline') return '网络已断开，请检查网络后重试';
  if (mode === 'timeout') return '连接超时，正在尝试重连';
  if (mode === 'reconnecting') return '正在重连…';
  return '正在连接…';
}

function isSameConversation(item: MockConversation, selectedId?: string): boolean {
  if (!selectedId) return false;
  return item.id === selectedId || item.imConversationID === selectedId;
}

const ADOPTION_REVIEW_COLOR = '#0B6E4F';
const STATUS_DOT_SIZE = 12;

function ConversationStatusDots({
  hasRedDot,
  hasProactiveHint,
}: {
  hasRedDot: boolean;
  hasProactiveHint: boolean;
}) {
  if (!hasRedDot && !hasProactiveHint) return null;

  const circle = (color: string, overlap?: boolean): CSSProperties => ({
    width: STATUS_DOT_SIZE,
    height: STATUS_DOT_SIZE,
    borderRadius: STATUS_DOT_SIZE / 2,
    background: color,
    border: `2px solid ${webColor.surface}`,
    boxSizing: 'border-box',
    ...(overlap
      ? { marginLeft: -Math.round(STATUS_DOT_SIZE / 3), position: 'relative' as const, zIndex: 1 }
      : null),
  });

  if (hasRedDot && hasProactiveHint) {
    return (
      <Flex align="center" justify="flex-end">
        <span style={circle(webColor.proactive)} />
        <span style={circle(webColor.danger, true)} />
      </Flex>
    );
  }

  return (
    <span
      style={circle(hasRedDot ? webColor.danger : webColor.proactive)}
    />
  );
}

const ConversationRow = memo(function ConversationRow({
  item,
  selected,
  favorited,
  batchSelectMode,
  batchChecked,
  onOpen,
  onDelete,
  onToggleFavorite,
  onAckProcessed,
  ackSubmitting,
  showAckAction,
  onToggleBatch,
}: {
  item: MockConversation;
  selected: boolean;
  favorited: boolean;
  batchSelectMode: boolean;
  batchChecked: boolean;
  onOpen: (item: MockConversation) => void;
  onDelete: (item: MockConversation) => void;
  onToggleFavorite: (item: MockConversation) => void;
  onAckProcessed: (item: MockConversation) => void;
  ackSubmitting: boolean;
  showAckAction: boolean;
  onToggleBatch: (item: MockConversation) => void;
}) {
  const muted = !!item.inactive;
  const selectable = batchSelectMode && !muted;
  const hasProactiveHint = hasConversationProactiveHint(item);
  const hasAdoptionReview = hasConversationAdoptionReview(item);
  const name = conversationAudienceLabel(item) || '会话';
  const className = [
    'qh-conv-row',
    muted ? 'is-muted' : '',
    !batchSelectMode && selected ? 'is-active' : '',
    batchChecked ? 'is-batch-selected' : '',
  ]
    .filter(Boolean)
    .join(' ');

  const rowButton = (
    <Button
      type="text"
      block
      className={className}
      aria-current={!batchSelectMode && selected ? 'true' : undefined}
      disabled={batchSelectMode && muted}
      onClick={() => {
        if (selectable) onToggleBatch(item);
        else onOpen(item);
      }}
    >
      {batchSelectMode ? (
        <Checkbox
          checked={batchChecked}
          disabled={muted}
          style={{ pointerEvents: 'none', flexShrink: 0 }}
        />
      ) : null}
      <Badge count={item.unread} size="small" overflowCount={99} className="qh-conv-avatar">
          <Avatar
            size={webLayout.convAvatarSize}
            src={item.audiencePlatformFaceURL?.trim() || undefined}
            style={{
              background: item.avatarColor,
              color: webColor.onPrimary,
              border: 'none',
            }}
          >
            {(item.audiencePlatformNickname || item.to || '?').trim().charAt(0) || '?'}
          </Avatar>
        </Badge>
        <Flex vertical flex={1} style={{ minWidth: 0 }} gap={webLayout.convNamePreviewGap}>
          <Flex align="center" gap={8}>
            <Typography.Text ellipsis className="qh-conv-name" style={{ ...webType.nameLabel, flex: 1 }}>
              {name}
            </Typography.Text>
            {favorited && !muted ? <StarFilled style={{ color: webColor.favorite, fontSize: webFontSize.favoriteIcon }} /> : null}
          </Flex>
          <EmojiText
            text={item.preview || ''}
            color={muted ? webColor.placeholder : chromeCssVars.rowSubFg}
            variant="preview"
            textStyle={webType.subLabel}
          />
        </Flex>
        <Flex
          vertical
          align="flex-end"
          gap={6}
          style={{ alignSelf: 'stretch', flexShrink: 0, minWidth: 24 }}
        >
          <Typography.Text type="secondary" className="qh-conv-time" style={webType.timestamp}>
            {item.time}
          </Typography.Text>
          {/* 「AI复审」与状态点同一行：右侧列高度不超过正文，行高才能恒定 */}
          <Flex align="center" justify="flex-end" gap={6} style={{ minHeight: STATUS_DOT_SIZE }}>
            {!muted && hasAdoptionReview ? (
              <Typography.Text
                style={{
                  margin: 0,
                  fontSize: 11,
                  fontWeight: 600,
                  lineHeight: '14px',
                  color: ADOPTION_REVIEW_COLOR,
                  whiteSpace: 'nowrap',
                }}
              >
                AI复审
              </Typography.Text>
            ) : null}
            {!muted ? (
              <ConversationStatusDots
                hasRedDot={!!item.hasRedDot}
                hasProactiveHint={hasProactiveHint}
              />
            ) : null}
          </Flex>
        </Flex>
      </Button>
  );

  if (batchSelectMode) return rowButton;

  return (
    <Dropdown
      trigger={['contextMenu']}
      menu={{
        items: item.inactive
          ? [{ key: 'del', icon: <DeleteOutlined />, danger: true, label: '删除' }]
          : [
              ...(showAckAction
                ? [
                    {
                      key: 'ack',
                      icon: <CheckCircleOutlined />,
                      label: ackSubmitting ? '处理中…' : '已处理',
                      disabled: ackSubmitting,
                    },
                  ]
                : []),
              {
                key: 'fav',
                icon: favorited ? <StarFilled /> : <StarOutlined />,
                label: favorited ? '取消收藏' : '收藏',
              },
            ],
        onClick: ({ key }) => {
          if (key === 'del') onDelete(item);
          if (key === 'ack') onAckProcessed(item);
          if (key === 'fav') onToggleFavorite(item);
        },
      }}
    >
      {rowButton}
    </Dropdown>
  );
});

type ConversationListState = ReturnType<typeof useConversationList>;

const ActorRow = memo(function ActorRow({
  item,
  selected,
  onSelect,
  onDeleteInactive,
}: {
  item: ConversationActor;
  selected: boolean;
  onSelect: (item: ConversationActor) => void;
  onDeleteInactive: (item: ConversationActor) => void;
}) {
  const initial = (item.nickname || item.actorPlatformID || '?').trim().charAt(0) || '?';
  const actorName = item.nickname || item.actorPlatformID;
  const className = [
    'qh-conv-row',
    item.allInactive ? 'is-muted' : '',
    selected ? 'is-active' : '',
  ]
    .filter(Boolean)
    .join(' ');
  const rowButton = (
    <Button
      type="text"
      block
      className={className}
      aria-current={selected ? 'true' : undefined}
      onClick={() => onSelect(item)}
    >
      <span className="qh-conv-avatar">
        <Avatar
          size={webLayout.convAvatarSize}
          src={item.faceURL || undefined}
          style={{ background: webColor.primary, color: webColor.onPrimary, border: 'none' }}
        >
          {initial}
        </Avatar>
      </span>
      <Flex className="qh-actor-row-meta" vertical flex={1} style={{ minWidth: 0 }} gap={webLayout.convNamePreviewGap}>
        <Typography.Text ellipsis className="qh-conv-name" style={webType.nameLabel}>
          {actorName}
        </Typography.Text>
        <Typography.Text ellipsis className="qh-conv-sub" style={webType.subLabel}>
          {item.actorPlatformID}
        </Typography.Text>
      </Flex>
      <Flex
        className="qh-actor-row-status"
        align="center"
        justify="flex-end"
        style={{ flexShrink: 0, minWidth: STATUS_DOT_SIZE, minHeight: STATUS_DOT_SIZE }}
      >
        {!item.allInactive ? (
          <ConversationStatusDots
            hasRedDot={!!item.hasRedDot}
            hasProactiveHint={!!item.hasProactiveHint}
          />
        ) : null}
      </Flex>
    </Button>
  );

  if (!item.hasInactive) return rowButton;

  return (
    <Dropdown
      trigger={['contextMenu']}
      menu={{
        items: [
          {
            key: 'del-inactive',
            icon: <DeleteOutlined />,
            danger: true,
            label: '删除历史会话',
          },
        ],
        onClick: ({ key }) => {
          if (key === 'del-inactive') onDeleteInactive(item);
        },
      }}
    >
      {rowButton}
    </Dropdown>
  );
});

function ActorListPane({
  chat,
  actors,
  selectedId,
  openConversationId,
  onSelect,
}: {
  chat: ConversationListState;
  actors: ConversationActor[];
  selectedId: string | null;
  openConversationId?: string;
  onSelect: (actorPlatformID: string) => void;
}) {
  return (
    <Flex vertical className="qh-chat-list-pane">
      <Flex
        align="center"
        gap={8}
        style={{
          padding: '10px 16px',
          flexShrink: 0,
        }}
      >
        <Flex vertical style={{ flex: 1, minWidth: 0 }} gap={0}>
          <Typography.Title level={4} style={webType.paneTitle}>
            接待者
          </Typography.Title>
          <Typography.Text type="secondary" style={webType.pageSubtitle}>
            共 {actors.length} 人
          </Typography.Text>
        </Flex>
        <Button
          type="text"
          size="small"
          icon={<ReloadOutlined />}
          loading={chat.refreshing}
          disabled={chat.refreshBtnCooldown}
          onClick={() => void chat.handleManualRefresh()}
          title="刷新接待者列表"
          aria-label="刷新接待者列表"
        />
      </Flex>
      {actors.length === 0 ? (
        <Flex flex={1} align="center" justify="center">
          <Empty
            image={<TeamOutlined style={{ fontSize: webFontSize.emptyIcon, color: webColor.placeholder }} />}
            description="暂无接待者"
          />
        </Flex>
      ) : (
        <WebOverlayScroll>
          {actors.map((item) => (
            <ActorRow
              key={item.actorPlatformID}
              item={item}
              selected={selectedId === item.actorPlatformID}
              onSelect={(next) => onSelect(next.actorPlatformID)}
              onDeleteInactive={(next) =>
                chat.deleteInactiveForActor(next.actorPlatformID, openConversationId)
              }
            />
          ))}
        </WebOverlayScroll>
      )}
      <WebPaneResizeHandle pane="conv" />
    </Flex>
  );
}

function ConversationListPane({
  chat,
  selectedId,
  selectedAnnotatorId,
  selectedSupervisor,
  openFavoritesOnMount = false,
}: {
  chat: ConversationListState;
  selectedId?: string;
  selectedAnnotatorId?: string;
  selectedSupervisor: boolean;
  openFavoritesOnMount?: boolean;
}) {
  const scrollerRef = useRef<HTMLElement | null>(null);
  const [scrollerEl, setScrollerEl] = useState<HTMLElement | null>(null);
  const listWindow = useConversationWindow(scrollerEl, chat.list.length);

  const bindScroller = useCallback((el: HTMLElement | null) => {
    scrollerRef.current = el;
    setScrollerEl((prev) => (prev === el ? prev : el));
  }, []);

  useEffect(() => {
    if (!openFavoritesOnMount) return;
    chat.openFavorites();
    router.setParams({ favorites: undefined });
  }, [openFavoritesOnMount, chat.openFavorites]);

  const openInPane = useCallback(
    (item: MockConversation) => {
      savedConvListScrollTop = scrollerRef.current?.scrollTop ?? savedConvListScrollTop;
      prefetchConversationChatCache(item);
      const next = conversationChatRouteParams(item);
      const sameItem = isSameConversation(item, selectedId);
      const sameGate =
        selectedSupervisor === (next.supervisor === '1') &&
        (selectedAnnotatorId ?? '') === next.annotatorId;
      if (sameItem && sameGate) return;
      router.setParams(next);
    },
    [selectedId, selectedAnnotatorId, selectedSupervisor],
  );

  const toggleBatch = useCallback(
    (item: MockConversation) => {
      const id = (item.id ?? '').trim();
      if (id) chat.toggleBatchSelection(id);
    },
    [chat.toggleBatchSelection],
  );

  useLayoutEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;
    el.scrollTop = savedConvListScrollTop;
    listWindow.onScroll();
  }, [selectedId, chat.loading, chat.list.length, listWindow.onScroll]);

  return (
    <Flex vertical className="qh-chat-list-pane">
      <Flex
        align="center"
        gap={8}
        style={{
          padding: '10px 16px',
          flexShrink: 0,
        }}
      >
        <Flex vertical style={{ flex: 1, minWidth: 0 }} gap={0}>
          <Flex align="center" gap={8}>
            <Typography.Title level={4} style={webType.paneTitle}>
              聊天
            </Typography.Title>
          </Flex>
          <Typography.Text type="secondary" style={webType.pageSubtitle}>
            {chat.batchSelectMode
              ? chat.batchPreparing
                ? '正在准备默认选中…'
                : `已选 ${chat.selectedTaskIds.size} 个活跃会话`
              : chat.headerSubtitle}
          </Typography.Text>
        </Flex>
        <Flex align="center" gap={4} style={{ flexShrink: 0 }}>
          <Button
            type="text"
            size="small"
            icon={<ReloadOutlined />}
            loading={chat.refreshing}
            disabled={chat.refreshBtnCooldown}
            onClick={() => void chat.handleManualRefresh()}
            title="刷新会话列表"
            aria-label="刷新会话列表"
          />
          {!chat.isSupervisor ? (
            chat.batchSelectMode ? (
              <>
                <Button
                  size="small"
                  type="text"
                  onClick={chat.cancelBatchSelect}
                  disabled={chat.batchActionBusy}
                >
                  取消
                </Button>
                <Button
                  size="small"
                  type="primary"
                  danger={chat.batchKind === 'complete'}
                  loading={chat.batchActionBusy}
                  disabled={chat.batchPreparing}
                  onClick={() => chat.confirmBatchAction()}
                >
                  {chat.batchKind === 'transfer' ? '转移' : '结束'}
                </Button>
              </>
            ) : (
              <Dropdown
                trigger={['click']}
                placement="bottomRight"
                menu={{
                  items: [
                    { key: 'batch-complete', label: '批量结束' },
                    { key: 'batch-transfer', label: '批量转移' },
                    { key: 'favorites', label: '我的收藏' }
                  ],
                  onClick: ({ key }) => {
                    if (key === 'favorites') chat.openFavorites();
                    if (key === 'batch-complete') chat.startBatchComplete();
                    if (key === 'batch-transfer') chat.startBatchTransfer();
                  },
                }}
              >
                <Button
                  type="text"
                  icon={<EllipsisOutlined style={{ fontSize: webFontSize.moreIcon }} />}
                  title="更多操作"
                  aria-label="更多操作"
                />
              </Dropdown>
            )
          ) : null}
        </Flex>
      </Flex>

      {chat.bannerMode ? (
        <Alert
          type={chat.bannerMode === 'offline' ? 'error' : 'warning'}
          title={bannerText(chat.bannerMode)}
          action={
            <Button size="small" onClick={() => chat.retry()}>
              重试
            </Button>
          }
          showIcon
          style={{ margin: '8px 12px 0', flexShrink: 0 }}
        />
      ) : null}

      <Flex className="qh-conv-toolbar" align="center" gap={8}>
        <Input
          className="qh-conv-search"
          allowClear
          variant="borderless"
          prefix={<SearchOutlined />}
          placeholder="搜索"
          value={chat.keyword}
          onChange={(e) => chat.setKeyword(e.target.value)}
        />
      </Flex>

      {chat.loading && chat.list.length === 0 ? (
        <Flex flex={1} align="center" justify="center">
          <Spin />
        </Flex>
      ) : chat.list.length === 0 ? (
        <Flex flex={1} align="center" justify="center">
          <Empty description="暂无会话" />
        </Flex>
      ) : (
        <WebOverlayScroll
          viewportRef={bindScroller}
          onScroll={(e) => {
            savedConvListScrollTop = e.currentTarget.scrollTop;
            listWindow.onScroll();
          }}
        >
          <div
            style={{
              height: chat.list.length * webLayout.convRowHeight,
              flexShrink: 0,
              position: 'relative',
            }}
          >
            <div
              style={{
                position: 'absolute',
                insetInline: 0,
                top: listWindow.start * webLayout.convRowHeight,
              }}
            >
              {chat.list.slice(listWindow.start, listWindow.end).map((item) => {
                const taskId = (item.id ?? '').trim();
                const rowKey = conversationRowKey(item) || taskId;
                if (!rowKey) return null;
                return (
                  <div
                    key={rowKey}
                    style={{ height: webLayout.convRowHeight, overflow: 'hidden' }}
                  >
                    <ConversationRow
                      item={item}
                      selected={isSameConversation(item, selectedId)}
                      favorited={chat.favoritedKeys.has(conversationFavoriteKey(item))}
                      batchSelectMode={chat.batchSelectMode}
                      batchChecked={!!taskId && chat.selectedTaskIds.has(taskId)}
                      onOpen={openInPane}
                      onDelete={chat.deleteInactive}
                      onToggleFavorite={chat.toggleFavorite}
                      onAckProcessed={chat.ackProcessed}
                      ackSubmitting={chat.isAckSubmitting(taskId)}
                      showAckAction={chat.canAckConversationPending(item)}
                      onToggleBatch={toggleBatch}
                    />
                  </div>
                );
              })}
            </div>
          </div>
        </WebOverlayScroll>
      )}
      <WebPaneResizeHandle pane="conv" />
      <BatchCompleteConfirmModal {...chat.batchConfirmModalProps} />
      <TransferAgentPicker {...chat.transferPickerProps} />
      <FavoritesModal
        visible={chat.favoritesModalVisible}
        onClose={chat.closeFavorites}
        onFavoritesChange={chat.syncFavoritedKeys}
      />
    </Flex>
  );
}

export default function ConversationListPage() {
  const params = useLocalSearchParams<{
    id?: string;
    annotatorId?: string;
    supervisor?: string;
    favorites?: string;
  }>();
  const selectedId = paramStr(params.id);
  const annotatorId = paramStr(params.annotatorId);
  const supervisorParam = paramStr(params.supervisor) === '1';
  const openFavoritesOnMount = paramStr(params.favorites) === '1';
  const chat = useConversationList();
  const [listView, setListView] = useState(getChatListView);

  useEffect(() => subscribeChatListView(setListView), []);

  const handleSelectActor = useCallback(
    (actorPlatformID: string) => {
      chat.selectActor(actorPlatformID);
      const picked = chat.actors.find((item) => item.actorPlatformID === actorPlatformID);
      setSiderActorBrand(
        picked
          ? {
              actorPlatformID: picked.actorPlatformID,
              nickname: picked.nickname || picked.actorPlatformID,
              faceURL: picked.faceURL,
            }
          : null,
      );
      setChatListView('chat');
      router.setParams({ id: '', annotatorId: '', supervisor: '' });
    },
    [chat.selectActor, chat.actors],
  );

  useEffect(() => {
    if (!selectedId) return;
    chat.selectActorByConversation(selectedId);
  }, [selectedId, chat.selectActorByConversation]);

  useEffect(() => {
    const current = getSiderActorBrand();
    if (!current) return;
    const pinned = chat.actors.find((item) => item.actorPlatformID === current.actorPlatformID);
    if (!pinned) return;
    setSiderActorBrand({
      actorPlatformID: pinned.actorPlatformID,
      nickname: pinned.nickname || pinned.actorPlatformID,
      faceURL: pinned.faceURL,
    });
  }, [chat.actors]);

  return (
    <Flex className="qh-chat-split">
      {listView === 'hosts' ? (
        <ActorListPane
          chat={chat}
          actors={chat.actors}
          selectedId={chat.selectedActorPlatformID}
          openConversationId={selectedId}
          onSelect={handleSelectActor}
        />
      ) : (
        <ConversationListPane
          chat={chat}
          selectedId={selectedId}
          selectedAnnotatorId={annotatorId}
          selectedSupervisor={supervisorParam}
          openFavoritesOnMount={openFavoritesOnMount}
        />
      )}
      <Flex vertical className="qh-chat-room-pane">
        {selectedId ? (
          <ChatRoomPane
            key={`${selectedId}:${annotatorId ?? ''}:${supervisorParam ? '1' : '0'}`}
            taskID={selectedId}
            annotatorId={annotatorId}
            supervisorParam={supervisorParam}
          />
        ) : (
          <Flex flex={1} align="center" justify="center" style={{ height: '100%', width: '100%', background: chromeCssVars.chatPaneBg }}>
            <Empty
              image={<MessageOutlined style={{ fontSize: webFontSize.emptyIcon, color: webColor.primary }} />}
              description="从左侧选择一个会话开始回复"
            />
          </Flex>
        )}
      </Flex>
    </Flex>
  );
}
