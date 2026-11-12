import { useCallback, useRef } from 'react';
import {
  Button,
  Dropdown,
  Flex,
  Input,
  Modal,
  Typography,
} from 'antd';
import type { MenuProps } from 'antd';
import { EllipsisOutlined } from '@/ui/web/antd-icons';
import { useChatRoomScreen } from '@/chatMessage/room/useChatRoomScreen';
import { deriveChatMoreMenuModel } from '@/chatMessage/components/ChatMoreMenuSheet';
import { CHAT_MORE_MENU_LABELS } from '@/chatMessage/components/chat-more-menu-flags';
import { WebProactiveActionHintBanner } from '@/ui/web/chat/WebProactiveActionHintBanner';
import type { ChatInputAreaHandle } from '@/chatMessage/components/ChatInputArea';
import type { ChatMessageListHandle } from '@/chatMessage/list';
import type { AdoptionDraftItem } from '@/chatMessage/components/AdoptionReviewSheet';
import { WebChatMessageList } from '@/ui/web/chat/WebChatMessageList';
import { WebChatComposer } from '@/ui/web/chat/WebChatComposer';
import { WebAdoptionModal } from '@/ui/web/chat/WebAdoptionModal';
// import { WebAudienceProfileModal } from '@/ui/web/chat/WebAudienceProfileModal';
import { WebMediaPreview } from '@/ui/web/chat/WebMediaPreview';
import { WebMessageActionMenu } from '@/ui/web/chat/WebMessageActionMenu';
import { chromeCssVars } from '@/ui/web/chrome-theme';
import { webColor, webFontSize, webType } from '@/ui/web/theme';
import { TransferAgentPicker } from '@/features/conversations/TransferAgentPicker';

export function ChatRoomPane({
  taskID,
  annotatorId,
  supervisorParam = false,
  onSupervisorTakeoverComplete,
}: {
  taskID: string;
  annotatorId?: string;
  supervisorParam?: boolean;
  onSupervisorTakeoverComplete?: (taskID: string) => void;
}) {
  const messageListRef = useRef<ChatMessageListHandle>(null);
  const inputAreaRef = useRef<ChatInputAreaHandle>(null);
  // TODO: 点击头像查看资料弹窗，后续接入后恢复
  // const [audienceProfileOpen, setAudienceProfileOpen] = useState(false);
  const chat = useChatRoomScreen({
    taskID,
    annotatorId,
    supervisorParam,
    messageListRef,
    inputAreaRef,
    onSupervisorTakeoverComplete,
  });
  const { session } = chat;
  // TODO: 点击头像查看资料弹窗，后续接入后恢复
  // const handlePressAudienceAvatar = useCallback(() => {
  //   chat.handleOpenAudienceProfile();
  //   setAudienceProfileOpen(true);
  // }, [chat.handleOpenAudienceProfile]);
  const handlePressAudienceAvatar = useCallback(() => {
    // no-op：资料弹窗入口暂关
  }, []);
  const more = deriveChatMoreMenuModel({
    taskAnnotatorID: session.taskAnnotatorID,
    taskMode: session.taskMode,
    skillGroup: session.skillGroup,
    currentHasRedDot: session.currentHasRedDot,
  });

  const menuItems: MenuProps['items'] = [];
  if (more.showAckPending) {
    menuItems.push({
      key: 'ack',
      label: chat.ackSubmitting ? CHAT_MORE_MENU_LABELS.ackSubmitting : CHAT_MORE_MENU_LABELS.ack,
      disabled: chat.ackSubmitting,
    });
  }
  if (!more.isSupervisor) {
    menuItems.push({ key: 'report', label: CHAT_MORE_MENU_LABELS.report });
    if (more.showAgentTransfer) {
      menuItems.push({
        key: 'transfer',
        label: CHAT_MORE_MENU_LABELS.transfer,
        disabled: chat.transferSubmitting,
      });
    }
    menuItems.push({ key: 'end', label: CHAT_MORE_MENU_LABELS.end, danger: true });
  }
  // TODO: 临时隐藏开启/关闭 AI 托管入口，恢复时将 chat-more-menu-flags 中开关改为 true
  if (more.showAgentTaskMode) {
    menuItems.push({ key: 'mode', label: more.agentTaskModeLabel, disabled: chat.taskModeSubmitting });
  }
  if (more.showSupervisorTakeover) {
    menuItems.push({ key: 'takeover', label: CHAT_MORE_MENU_LABELS.takeover, disabled: chat.takeoverSubmitting });
  }
  if (more.isSupervisorOwnTask) {
    menuItems.push({ key: 'complete', label: CHAT_MORE_MENU_LABELS.complete, disabled: chat.completeSubmitting });
    menuItems.push({ key: 'return', label: CHAT_MORE_MENU_LABELS.return, disabled: chat.returnSubmitting });
  }

  const onMenuClick: MenuProps['onClick'] = ({ key }) => {
    if (key === 'ack') chat.handleAckProcessed();
    if (key === 'report') chat.handleOpenReport();
    if (key === 'transfer') chat.handleOpenTransfer();
    if (key === 'end') chat.handleEndChat();
    if (key === 'mode') chat.handleToggleTaskMode();
    if (key === 'takeover') chat.handleTakeover();
    if (key === 'complete') chat.handleCompleteTask();
    if (key === 'return') chat.handleReturnToAgent();
  };

  return (
    <Flex vertical className="qh-chat-room" style={{ height: '100%', width: '100%', minHeight: 0, minWidth: 0 }}>
      <Flex
        align="center"
        gap={12}
        style={{
          padding: '10px 16px',
          borderBottom: `1px solid ${webColor.separator}`,
          background: chromeCssVars.chatPaneBg,
          flexShrink: 0,
        }}
      >
        <Typography.Title level={4} ellipsis style={{ ...webType.chatNavTitle, flex: 1 }}>
          {chat.navTitle}
        </Typography.Title>
        {chat.showMoreMenu && menuItems.length > 0 ? (
          <Dropdown menu={{ items: menuItems, onClick: onMenuClick }} trigger={['click']}>
            <Button
              type="text"
              icon={<EllipsisOutlined style={{ fontSize: webFontSize.moreIcon }} />}
              aria-label="更多操作"
            />
          </Dropdown>
        ) : null}
      </Flex>

      <Flex
        vertical
        flex={1}
        className="qh-chat-body"
        style={{ minHeight: 0, minWidth: 0, width: '100%', position: 'relative' }}
      >
        <WebChatMessageList
          ref={messageListRef}
          loading={chat.loading}
          messages={chat.messages}
          loadingMore={chat.loadingMore}
          hasMoreBefore={chat.hasMoreBefore}
          onLoadOlder={chat.handleLoadOlder}
          onDismissComposer={chat.dismissComposer}
          onOpenImage={chat.openImageViewer}
          onOpenVideo={chat.openVideoViewer}
          onOpenFile={chat.openFileViewer}
          onOpenActionMenu={chat.openMessageActionMenu}
          onPressAudienceAvatar={handlePressAudienceAvatar}
          actorAvatarUrl={session.actorAvatarUrl}
          audienceAvatarUrl={session.audienceAvatarUrl}
          audienceAvatarColor={session.audienceAvatarColor}
          actorNickname={session.actorNickname}
          audienceNickname={session.audienceNickname}
        />

        <WebProactiveActionHintBanner
          visible={chat.showProactiveHintBanner}
          hints={session.proactiveActionHints}
          canQuickSend={chat.isChatInputOpen}
          onDismiss={chat.handleDismissProactiveHint}
          onQuickSend={chat.handleQuickSendProactiveHint}
          onFillDraft={(text) => {
            if (!chat.isChatInputOpen) return;
            chat.setDraft(text);
          }}
        />
      </Flex>

      <WebChatComposer
        ref={inputAreaRef}
        roomKey={taskID}
        bannerHint={chat.bannerHint}
        bannerCountdownEndAt={chat.bannerCountdownEndAt}
        adoptionReviewVisible={chat.needsAdoptionReview}
        onAdoptionReviewPress={() => session.setAdoptionModalOpen(true)}
        inputEnabled={chat.inputEnabled}
        inputPlaceholder={chat.inputPlaceholder}
        sendingImage={chat.sendingImage}
        sendingVoice={chat.sendingVoice}
        sendingFile={chat.sendingFile}
        sendingVideo={chat.sendingVideo}
        onChangeDraft={chat.setDraft}
        onSend={chat.handleSend}
        onPickImage={() => void chat.handlePickImage()}
        onSendPickedFile={(file) => void chat.handleSendPickedFile(file)}
        onPickVideo={() => void chat.handlePickVideo()}
        onSendSticker={chat.handleSendSticker}
      />

      <TransferAgentPicker
        visible={chat.transferPickerOpen}
        confirming={chat.transferSubmitting}
        onClose={chat.closeTransferPicker}
        onConfirm={chat.handleTransferToAgent}
      />

      <Modal
        open={chat.reportOpen}
        title="上报问题"
        okText="确认上报"
        confirmLoading={chat.submitting}
        onCancel={chat.closeReport}
        onOk={chat.handleReportSubmit}
        styles={{ title: webType.modalTitle }}
      >
        <Typography.Paragraph type="secondary" style={webType.modalSubtitle}>
          转交主管处理，转交后你将无法继续发送消息
        </Typography.Paragraph>
        <Input.TextArea
          value={chat.reportText}
          onChange={(e) => chat.setReportText(e.target.value)}
          placeholder="请输入需要上报的问题描述（可选）"
          maxLength={500}
          rows={4}
        />
      </Modal>

      <WebAdoptionModal
        open={session.adoptionModalOpen}
        adoption={session.adoptionContext}
        submitting={chat.adoptionSubmitting}
        onClose={() => session.setAdoptionModalOpen(false)}
        onSubmit={(drafts: AdoptionDraftItem[], mode, opts) =>
          chat.handleAdoptionSubmit(drafts, mode, opts)
        }
      />

      <WebMediaPreview state={chat.previewState} onClose={chat.closePreview} />

      {/* TODO: 点击头像查看资料弹窗，后续接入后恢复
      <WebAudienceProfileModal
        open={audienceProfileOpen}
        taskID={taskID}
        nickname={session.audienceNickname}
        avatarUrl={session.audienceAvatarUrl}
        onClose={() => setAudienceProfileOpen(false)}
      />
      */}

      <WebMessageActionMenu
        visible={!!chat.actionMenu}
        kind={chat.actionMenu?.kind ?? 'text'}
        anchor={chat.actionMenu?.anchor ?? null}
        onClose={() => chat.setActionMenu(null)}
        onAction={(id) => void chat.handleMessageAction(id)}
      />
    </Flex>
  );
}

export default ChatRoomPane;
