import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { Alert, Button, Flex, Popover, Space, Upload } from 'antd';
import {
  FolderOpenOutlined,
  PictureOutlined,
  SmileOutlined,
  VideoCameraOutlined,
} from '@/ui/web/antd-icons';
import type { ChatInputAreaHandle } from '@/chatMessage/components/ChatInputArea';
import {
  ChatComposer,
  type ChatComposerHandle,
} from '@/chatMessage/components/ChatComposer';
import { formatAiReplyRemainingSeconds } from '@/chatMessage/message/ai-reply-window';
import { useChatDraft } from '@/chatMessage/room/chat-draft-store';
import {
  ensureCustomStickersHydrated,
  getCustomStickersSnapshot,
  subscribeCustomStickers,
  type CustomSticker,
} from '@/chatMessage/stickerPack';
import { WebCustomStickersModal } from '@/ui/web/chat/WebCustomStickersModal';
import { WebEmojiPanel } from '@/ui/web/chat/WebEmojiPanel';
import { chromeCssVars } from '@/ui/web/chrome-theme';
import { webColor } from '@/ui/web/theme';

function BannerCountdown({ endAt }: { endAt: number }) {
  const [label, setLabel] = useState(() => formatAiReplyRemainingSeconds(endAt));
  useEffect(() => {
    setLabel(formatAiReplyRemainingSeconds(endAt));
    const timer = setInterval(() => setLabel(formatAiReplyRemainingSeconds(endAt)), 500);
    return () => clearInterval(timer);
  }, [endAt]);
  return <span style={{ fontVariantNumeric: 'tabular-nums' }}>{label}</span>;
}

export const WebChatComposer = forwardRef<
  ChatInputAreaHandle,
  {
    bannerHint: string | null;
    /** 非空时在 bannerHint 后追加倒计时（AI 自动回复窗口剩余时间） */
    bannerCountdownEndAt?: number | null;
    /** 展示「有AI消息需要复审」横幅 */
    adoptionReviewVisible?: boolean;
    onAdoptionReviewPress?: () => void;
    inputEnabled: boolean;
    inputPlaceholder: string;
    sendingImage: boolean;
    sendingVoice?: boolean;
    sendingFile?: boolean;
    sendingVideo?: boolean;
    onChangeDraft: (text: string) => void;
    onSend: (text?: string) => void;
    onPickImage: () => void;
    /** Web Upload 已选中的 File，直接发送（勿再弹 DocumentPicker） */
    onSendPickedFile: (file: File) => void;
    onPickVideo: () => void;
    onSendSticker: (sticker: CustomSticker) => void;
    /** 会话标识：进房自动聚焦 + 订阅本会话草稿（草稿在 chat-draft-store，不走页面 state） */
    roomKey: string;
  }
>(function WebChatComposer(props, ref) {
  const composerRef = useRef<ChatComposerHandle>(null);
  const draft = useChatDraft(props.roomKey);
  const [stickers, setStickers] = useState<CustomSticker[]>([]);
  const [emojiOpen, setEmojiOpen] = useState(false);
  const [manageOpen, setManageOpen] = useState(false);
  const countdownEndAt = props.bannerCountdownEndAt ?? null;

  useImperativeHandle(ref, () => ({
    closeAttachPanel: () => {},
    dismissKeyboard: () => composerRef.current?.blur(),
    focus: () => composerRef.current?.focus(),
  }), []);

  useEffect(() => {
    if (!props.inputEnabled) return;
    const t = window.setTimeout(() => composerRef.current?.focus(), 50);
    return () => clearTimeout(t);
  }, [props.inputEnabled, props.roomKey]);

  useEffect(() => {
    let alive = true;
    void ensureCustomStickersHydrated().then((list) => {
      if (alive) setStickers(list);
    });
    const off = subscribeCustomStickers((list) => {
      if (alive) setStickers(list);
    });
    setStickers(getCustomStickersSnapshot());
    return () => {
      alive = false;
      off();
    };
  }, []);

  const closeEmojiPanel = () => setEmojiOpen(false);

  const handleSelectEmoji = (name: string) => {
    composerRef.current?.insertEmoji(name);
    closeEmojiPanel();
    window.setTimeout(() => composerRef.current?.focus(), 0);
  };

  const handleSendSticker = (sticker: CustomSticker) => {
    closeEmojiPanel();
    props.onSendSticker(sticker);
  };

  const emojiContent = (
    <WebEmojiPanel
      stickers={stickers}
      onSelectEmoji={handleSelectEmoji}
      onSendSticker={handleSendSticker}
      onManageStickers={() => {
        setManageOpen(true);
      }}
    />
  );

  return (
    <Flex vertical style={{ borderTop: `1px solid ${webColor.separator}`, background: chromeCssVars.chatPaneBg, padding: 12 }} gap={8}>
      {/* 复审条仍置顶；AI 自动回复倒计时改到操作栏右下空白区，不锁输入 */}
      {props.adoptionReviewVisible ? (
        <Alert
          type="warning"
          showIcon
          title="有AI消息需要复审"
          action={
            <Button
              type="link"
              size="small"
              onClick={props.onAdoptionReviewPress}
              style={{ fontWeight: 600, color: webColor.primary, paddingInline: 0 }}
            >
              去处理
            </Button>
          }
        />
      ) : null}
      {props.bannerHint && countdownEndAt == null ? (
        <Alert type="warning" showIcon title={props.bannerHint} />
      ) : null}
      <div className="qh-web-composer">
        <ChatComposer
          ref={composerRef}
          value={draft}
          onChangeText={props.onChangeDraft}
          onSubmitEditing={(text) => {
            if (!props.inputEnabled) return;
            const payload = text.trim();
            if (!payload) return;
            props.onSend(payload);
          }}
          editable={props.inputEnabled}
          placeholder={props.inputPlaceholder}
          placeholderTextColor={webColor.placeholder}
          textColor={webColor.text}
          backgroundColor={webColor.surface}
          maxLength={5000}
        />
      </div>
      <Flex align="center" justify="space-between" gap={8} className="qh-composer-actions">
        <Space>
          <Popover
            content={emojiContent}
            trigger="click"
            placement="topLeft"
            arrow={false}
            open={emojiOpen}
            onOpenChange={(next) => {
              if (manageOpen && !next) return;
              setEmojiOpen(next);
            }}
            overlayClassName="qh-emoji-popover"
          >
            <Button type="text" className="qh-composer-action" icon={<SmileOutlined />} disabled={!props.inputEnabled} />
          </Popover>
          <Button
            type="text"
            className="qh-composer-action"
            icon={<PictureOutlined />}
            disabled={!props.inputEnabled}
            onClick={props.onPickImage}
          />
          <Button
            type="text"
            className="qh-composer-action"
            icon={<VideoCameraOutlined />}
            disabled={!props.inputEnabled}
            onClick={props.onPickVideo}
          />
          <Upload
            showUploadList={false}
            beforeUpload={(file) => {
              props.onSendPickedFile(file as File);
              return false;
            }}
          >
            <Button type="text" className="qh-composer-action" icon={<FolderOpenOutlined />} disabled={!props.inputEnabled} />
          </Upload>
        </Space>
        {props.bannerHint && countdownEndAt != null ? (
          <Flex
            align="center"
            style={{
              flexShrink: 1,
              minWidth: 0,
              color: webColor.warning,
              fontSize: 12,
              lineHeight: '18px',
              whiteSpace: 'nowrap',
            }}
          >
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {props.bannerHint}
              <BannerCountdown endAt={countdownEndAt} />
            </span>
          </Flex>
        ) : null}
      </Flex>
      <WebCustomStickersModal open={manageOpen} onClose={() => setManageOpen(false)} />
    </Flex>
  );
});
