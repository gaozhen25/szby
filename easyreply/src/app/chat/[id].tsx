import { useRef } from 'react';
import { Animated, Pressable, StyleSheet, useWindowDimensions, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { router, useLocalSearchParams } from 'expo-router';
import { CustomNavBar } from '@/components/UI/CustomNavBar';
import { ScreenCanvas } from '@/components/UI/ScreenCanvas';
import { ChatType } from '@/design/chat-type';
import { useTheme } from '@/design/theme-context';
import { MoreOutlined } from '@/ui/antd-icons';
import {
  AdoptionReviewBanner,
  AdoptionReviewModal,
  ChatInputArea,
  ChatMessageList,
  ChatMoreMenuSheet,
  MediaPreviewModal,
  ProactiveActionHintBanner,
  ReportTransferModal,
  useChatRoomScreen,
  MessageActionMenu,
  type ChatInputAreaHandle,
  type ChatMessageListHandle,
} from '@/chatMessage';
import { TransferAgentPicker } from '@/features/conversations/TransferAgentPicker';

export default function ChatDetailScreen() {
  const params = useLocalSearchParams<{
    id: string;
    annotatorId?: string;
    supervisor?: string;
  }>();
  const taskID = params.id ?? '';
  const theme = useTheme();
  const { width: screenWidth, height: screenHeight } = useWindowDimensions();
  const messageListRef = useRef<ChatMessageListHandle>(null);
  const inputAreaRef = useRef<ChatInputAreaHandle>(null);
  const chat = useChatRoomScreen({
    taskID,
    annotatorId: params.annotatorId,
    supervisorParam: params.supervisor === '1',
    messageListRef,
    inputAreaRef,
  });
  const { session } = chat;

  return (
    <ScreenCanvas
      safeAreaTop={false}
      showOrbs={false}
      style={{ backgroundColor: ChatType.color.chatBg }}
    >
      <StatusBar style="dark" />
      <CustomNavBar
        title={chat.navTitle}
        onBack={() => router.back()}
        style={{ backgroundColor: ChatType.color.chatChrome, borderBottomColor: '#F0F1F3', flexShrink: 0 }}
        showBackRedDot={session.otherConvHasRedDot}
        showBackYellowDot={session.otherConvHasYellowDot}
        rightMinWidth={88}
        right={
          <>
            {chat.showMoreMenu ? (
              <Pressable
                onPress={() => chat.setMoreMenuOpen(true)}
                hitSlop={8}
                accessibilityRole="button"
                accessibilityLabel="更多操作"
              >
                <MoreOutlined size={22} color={theme.text} />
              </Pressable>
            ) : null}
          </>
        }
      />

      <Animated.View style={styles.kav}>
        <View style={styles.chatBody}>
          <ChatMessageList
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
            onPressAudienceAvatar={chat.handleOpenAudienceProfile}
            actorAvatarUrl={session.actorAvatarUrl}
            audienceAvatarUrl={session.audienceAvatarUrl}
            audienceAvatarColor={session.audienceAvatarColor}
            actorNickname={session.actorNickname}
            audienceNickname={session.audienceNickname}
          />

          <ProactiveActionHintBanner
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
        </View>

        <Animated.View style={{ marginBottom: chat.keyboardOffset }}>
          <AdoptionReviewBanner
            visible={chat.needsAdoptionReview}
            onPress={() => session.setAdoptionModalOpen(true)}
          />

          <ChatInputArea
            ref={inputAreaRef}
            bannerHint={chat.bannerHint}
            bannerCountdownEndAt={chat.bannerCountdownEndAt}
            inputEnabled={chat.inputEnabled}
            inputPlaceholder={chat.inputPlaceholder}
            draftRoomKey={chat.draftRoomKey}
            keyboardVisible={chat.keyboardVisible}
            sendingImage={chat.sendingImage}
            sendingVoice={chat.sendingVoice}
            sendingFile={chat.sendingFile}
            sendingVideo={chat.sendingVideo}
            onChangeDraft={chat.setDraft}
            onSend={chat.handleSend}
            onPickImage={() => void chat.handlePickImage()}
            onTakePhoto={() => void chat.handleTakePhoto()}
            onPickFile={() => void chat.handlePickFile()}
            onPickVideo={() => void chat.handlePickVideo()}
            onSendVoice={(result) => { void chat.handleSendVoice(result); }}
            onSendSticker={chat.handleSendSticker}
            onComposerFocus={chat.nudgeKeyboardLift}
          />
        </Animated.View>
      </Animated.View>

      <ChatMoreMenuSheet
        visible={chat.moreMenuOpen}
        taskAnnotatorID={session.taskAnnotatorID}
        taskMode={session.taskMode}
        skillGroup={session.skillGroup}
        currentHasRedDot={session.currentHasRedDot}
        ackSubmitting={chat.ackSubmitting}
        taskModeSubmitting={chat.taskModeSubmitting}
        takeoverSubmitting={chat.takeoverSubmitting}
        transferSubmitting={chat.transferSubmitting}
        returnSubmitting={chat.returnSubmitting}
        completeSubmitting={chat.completeSubmitting}
        onClose={chat.closeMoreMenu}
        onAckProcessed={chat.handleAckProcessed}
        onOpenReport={chat.handleOpenReport}
        onToggleTaskMode={chat.handleToggleTaskMode}
        onEndChat={chat.handleEndChat}
        onTakeover={chat.handleTakeover}
        onOpenTransfer={chat.handleOpenTransfer}
        onCompleteTask={chat.handleCompleteTask}
        onReturnToAgent={chat.handleReturnToAgent}
      />

      <TransferAgentPicker
        visible={chat.transferPickerOpen}
        confirming={chat.transferSubmitting}
        onClose={chat.closeTransferPicker}
        onConfirm={chat.handleTransferToAgent}
      />

      <ReportTransferModal
        visible={chat.reportOpen}
        value={chat.reportText}
        submitting={chat.submitting}
        onChangeText={chat.setReportText}
        onClose={chat.closeReport}
        onSubmit={chat.handleReportSubmit}
      />

      <AdoptionReviewModal
        visible={session.adoptionModalOpen}
        adoption={session.adoptionContext}
        submitting={chat.adoptionSubmitting}
        onClose={() => session.setAdoptionModalOpen(false)}
        onSubmit={chat.handleAdoptionSubmit}
      />

      <MessageActionMenu
        visible={!!chat.actionMenu}
        kind={chat.actionMenu?.kind ?? 'text'}
        anchor={chat.actionMenu?.anchor ?? null}
        screenWidth={screenWidth}
        screenHeight={screenHeight}
        onClose={() => chat.setActionMenu(null)}
        onAction={(id) => { void chat.handleMessageAction(id); }}
      />

      <MediaPreviewModal state={chat.previewState} onClose={chat.closePreview} />
    </ScreenCanvas>
  );
}

const styles = StyleSheet.create({
  kav: { flex: 1, minHeight: 0, overflow: 'hidden' },
  chatBody: { flex: 1, minHeight: 0, position: 'relative', overflow: 'hidden' },
});
