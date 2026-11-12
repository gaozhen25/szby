import { useCallback, useMemo, useRef, useState, type MouseEvent } from 'react';
import { Button, Empty, Flex, Spin } from 'antd';
import { HeartOutlined, PlusOutlined, SearchOutlined, SmileOutlined } from '@/ui/web/antd-icons';
import type { CustomSticker } from '@/chatMessage/stickerPack';
import { centerChipScrollX } from '@/chatMessage/stickerPack/centerChipScroll';
import { useRemoteStickers } from '@/chatMessage/stickerPack/useRemoteStickers';
import { WECHAT_EMOJI_SOURCES } from '@/core/im/wechat-emoji';
import { getWechatEmojiUri } from '@/chatMessage/message/chat-emoji-draft';
import { ClickSpark } from '@/ui/web/bits/ClickSpark';
import { WebRemoteStickerCell } from '@/ui/web/chat/WebRemoteStickerCell';
import { webColor, webFontSize, webLayout } from '@/ui/web/theme';

type TabId = 'search' | 'emoji' | 'sticker';

export function WebEmojiPanel({
  stickers,
  onSelectEmoji,
  onSendSticker,
  onManageStickers,
}: {
  stickers: CustomSticker[];
  onSelectEmoji: (name: string) => void;
  onSendSticker: (sticker: CustomSticker) => void;
  onManageStickers: () => void;
}) {
  const [tab, setTab] = useState<TabId>('emoji');
  const [broken, setBroken] = useState<Set<string>>(() => new Set());
  const remote = useRemoteStickers(tab === 'search');

  const emojis = useMemo(
    () =>
      Object.keys(WECHAT_EMOJI_SOURCES)
        .map((name) => ({ name, uri: getWechatEmojiUri(name) }))
        .filter((e): e is { name: string; uri: string } => !!e.uri && !broken.has(e.name)),
    [broken],
  );

  const chipsRef = useRef<HTMLDivElement>(null);

  const onRemoteScroll = (e: { currentTarget: HTMLDivElement }) => {
    const el = e.currentTarget;
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 56) remote.onLoadMore();
  };

  const onChipClick = useCallback((e: MouseEvent<HTMLButtonElement>, action: () => void) => {
    action();
    const scroller = chipsRef.current;
    const chip = e.currentTarget;
    if (!scroller) return;
    const scrollerRect = scroller.getBoundingClientRect();
    const chipRect = chip.getBoundingClientRect();
    const left = centerChipScrollX({
      viewportWidth: scroller.clientWidth,
      contentWidth: scroller.scrollWidth,
      chipX: chipRect.left - scrollerRect.left + scroller.scrollLeft,
      chipWidth: chipRect.width,
    });
    const instant =
      typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    scroller.scrollTo({ left, behavior: instant ? 'auto' : 'smooth' });
  }, []);

  return (
    <Flex vertical className="qh-emoji-panel">
      {tab === 'search' ? (
        <ClickSpark sparkColor={webColor.primary}>
          <div className="qh-sticker-chips" ref={chipsRef}>
            <button
              type="button"
              className={`qh-sticker-chip${remote.tagCodes.length === 0 ? ' is-active' : ''}`}
              onClick={(e) => onChipClick(e, remote.onPressAll)}
            >
              全部
            </button>
            {remote.tags.map((t) => (
              <button
                key={t.code}
                type="button"
                className={`qh-sticker-chip${remote.tagCodes.includes(t.code) ? ' is-active' : ''}`}
                onClick={(e) => onChipClick(e, () => remote.onPressTag(t.code))}
              >
                {t.name}
              </button>
            ))}
            {remote.optionsError ? <span className="qh-sticker-chip-hint">标签暂不可用</span> : null}
          </div>
        </ClickSpark>
      ) : null}
      <div className="qh-emoji-body" onScroll={tab === 'search' ? onRemoteScroll : undefined}>
        {tab === 'search' ? (
          remote.loading && remote.items.length === 0 ? (
            <Flex flex={1} align="center" justify="center" style={{ minHeight: 120 }}>
              <Spin />
            </Flex>
          ) : remote.error && remote.items.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={remote.error}>
              <Button type="link" onClick={remote.reload}>
                重试
              </Button>
            </Empty>
          ) : remote.items.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无表情" />
          ) : (
            <Flex wrap="wrap" gap={8} className="qh-emoji-stickers">
              {remote.items.map((item) => (
                <WebRemoteStickerCell
                  key={item.uuid}
                  item={item}
                  onSend={(sticker) => onSendSticker(remote.toSendable(sticker))}
                />
              ))}
              {remote.loadingMore ? (
                <Flex align="center" justify="center" style={{ width: '100%', padding: 8 }}>
                  <Spin size="small" />
                </Flex>
              ) : null}
            </Flex>
          )
        ) : tab === 'sticker' ? (
          <Flex wrap="wrap" gap={8} className="qh-emoji-stickers">
            <button
              type="button"
              className="qh-sticker-add-cell"
              aria-label="添加自定义表情"
              title="添加自定义表情"
              onClick={onManageStickers}
            >
              <PlusOutlined style={{ fontSize: webFontSize.lg }} />
            </button>
            {stickers.map((s) => (
              <button
                key={s.id}
                type="button"
                className="qh-sticker-send-cell"
                aria-label="发送自定义表情"
                onClick={() => onSendSticker(s)}
              >
                <img
                  src={s.url}
                  alt=""
                  width={webLayout.emojiSticker}
                  height={webLayout.emojiSticker}
                />
              </button>
            ))}
          </Flex>
        ) : emojis.length ? (
          <div className="qh-emoji-grid">
            {emojis.map((e) => (
              <button
                key={e.name}
                type="button"
                className="qh-emoji-cell"
                aria-label={e.name}
                onClick={() => onSelectEmoji(e.name)}
              >
                <img
                  src={e.uri}
                  alt={e.name}
                  onError={() => {
                    setBroken((prev) => {
                      if (prev.has(e.name)) return prev;
                      const next = new Set(prev);
                      next.add(e.name);
                      return next;
                    });
                  }}
                />
              </button>
            ))}
          </div>
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配的表情" />
        )}
      </div>

      <Flex align="center" className="qh-emoji-tabs">
        <Button
          type="text"
          className={`qh-emoji-tab${tab === 'search' ? ' is-active' : ''}`}
          icon={<SearchOutlined style={{ fontSize: webFontSize.emojiTabIcon }} />}
          aria-label="表情库"
          onClick={() => setTab('search')}
        />
        <Button
          type="text"
          className={`qh-emoji-tab${tab === 'emoji' ? ' is-active' : ''}`}
          icon={<SmileOutlined style={{ fontSize: webFontSize.emojiTabIcon }} />}
          aria-label="表情"
          onClick={() => setTab('emoji')}
        />
        <Button
          type="text"
          className={`qh-emoji-tab${tab === 'sticker' ? ' is-active' : ''}`}
          icon={<HeartOutlined style={{ fontSize: webFontSize.emojiTabIcon }} />}
          aria-label="我的表情"
          onClick={() => setTab('sticker')}
        />
      </Flex>
    </Flex>
  );
}
