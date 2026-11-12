import { forwardRef, useImperativeHandle, useRef } from 'react';
import {
  ActivityIndicator,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useTheme } from '@/design/theme-context';
import {
  AppstoreOutlined,
  CameraOutlined,
  CloseOutlined,
  FolderOpenOutlined,
  ClockCircleOutlined,
  LockOutlined,
  PictureOutlined,
  PlusOutlined,
  SmileOutlined,
  SoundOutlined,
  VideoCameraOutlined,
} from '@/ui/antd-icons';
import { resolveBottomInset } from '@/lib/safe-area-bottom';
import { ChatComposer, type ChatComposerHandle } from './ChatComposer';
import { CountdownText } from '@/chatMessage/components/CountdownText';
import { VoiceRecordingOverlay } from '@/chatMessage/components/VoiceRecordingOverlay';
import { WebVoiceRecordingBar } from '@/chatMessage/components/WebVoiceRecordingBar';
import { useComposerChrome } from '@/chatMessage/composer';
import { useChatDraft } from '@/chatMessage/room/chat-draft-store';
import type { VoiceRecorderResult } from '@/chatMessage/message/voice-recorder';
import {
  EmojiPanel,
  EMOJI_PANEL_HEIGHT,
  type CustomSticker,
} from '@/chatMessage/stickerPack';

export type ChatInputAreaHandle = {
  /** 选图/拍照前收起附件面板（与门禁校验的先后顺序由调用方决定） */
  closeAttachPanel: () => void;
  /** 收起键盘：必须 blur WebView composer，仅 Keyboard.dismiss 对 contentEditable 无效 */
  dismissKeyboard: () => void;
  /** 聚焦输入框（Web 进房自动聚焦 / 发送后保持焦点） */
  focus: () => void;
};

/** 临时隐藏语音入口；录音/发送链路仍保留，改回 true 即可恢复 */
const SHOW_VOICE_ENTRY = false;

/** 锁定提示条 + 输入栏 + 附件面板 + 表情面板 */
export const ChatInputArea = forwardRef<
  ChatInputAreaHandle,
  {
    bannerHint: string | null;
    /** 非空时在 bannerHint 后追加倒计时（AI 自动回复窗口剩余时间） */
    bannerCountdownEndAt?: number | null;
    inputEnabled: boolean;
    inputPlaceholder: string;
    /** 草稿由本组件自己订阅（见 chat-draft-store），聊天页不因逐字输入重渲染 */
    draftRoomKey: string;
    keyboardVisible: boolean;
    sendingImage: boolean;
    sendingVoice?: boolean;
    sendingFile?: boolean;
    sendingVideo?: boolean;
    onChangeDraft: (text: string) => void;
    onSend: (text?: string) => void;
    onPickImage: () => void;
    onTakePhoto: () => void;
    onPickFile: () => void;
    onPickVideo: () => void;
    onSendVoice: (result: VoiceRecorderResult) => void;
    onSendSticker: (sticker: CustomSticker) => void;
    onComposerFocus?: () => void;
  }
>(function ChatInputArea(
  {
    bannerHint,
    bannerCountdownEndAt = null,
    inputEnabled,
    inputPlaceholder,
    draftRoomKey,
    keyboardVisible,
    sendingVoice = false,
    onChangeDraft,
    onSend,
    onPickImage,
    onTakePhoto,
    onPickFile,
    onPickVideo,
    onSendVoice,
    onSendSticker,
    onComposerFocus,
  },
  ref,
) {
  const theme = useTheme();
  const draft = useChatDraft(draftRoomKey);
  const insets = useSafeAreaInsets();
  const bottomInset = resolveBottomInset(insets.bottom);
  const composerRef = useRef<ChatComposerHandle | null>(null);
  const holdBtnRef = useRef<View | null>(null);
  const chrome = useComposerChrome({
    inputEnabled,
    sendingVoice,
    onSend,
    onSendVoice,
    composerRef,
  });

  useImperativeHandle(
    ref,
    () => ({
      closeAttachPanel: chrome.closeAttachPanel,
      dismissKeyboard: chrome.dismissKeyboard,
      focus: () => composerRef.current?.focus(),
    }),
    [chrome.closeAttachPanel, chrome.dismissKeyboard],
  );

  const circleBorder = theme.textSubtle;
  const showWebRecordingBar = chrome.showWebRecordingBar;
  const barPaddingBottom =
    chrome.emojiPanelOpen || chrome.attachPanelOpen || showWebRecordingBar
      ? 8
      : keyboardVisible
        ? 8
        : Math.max(bottomInset, 8);

  return (
    <>
      {bannerHint ? (
        <View style={[styles.lockBanner, { backgroundColor: theme.warningSoft, borderTopColor: theme.warning + '40' }]}>
          {bannerCountdownEndAt == null ? (
            <LockOutlined size={14} color={theme.warning} />
          ) : (
            <ClockCircleOutlined size={14} color={theme.warning} />
          )}
          <Text style={[styles.lockText, { color: theme.warning }]}>{bannerHint}</Text>
          {bannerCountdownEndAt == null ? null : (
            <CountdownText
              endAt={bannerCountdownEndAt}
              format="seconds"
              style={[styles.lockText, styles.lockCountdown, { color: theme.warning }]}
            />
          )}
        </View>
      ) : null}

      <View
        style={[
          styles.inputBar,
          {
            paddingBottom: barPaddingBottom,
            backgroundColor: showWebRecordingBar ? '#1C1C1E' : theme.surface,
            borderTopColor: showWebRecordingBar ? '#1C1C1E' : theme.divider,
          },
        ]}
      >
        {showWebRecordingBar ? (
          <WebVoiceRecordingBar
            sending={sendingVoice}
            onCancel={chrome.handleWebCancel}
            onSend={chrome.handleWebSend}
          />
        ) : (
          <>
            {SHOW_VOICE_ENTRY ? (
              <Pressable
                onPress={chrome.handleToggleVoiceMode}
                hitSlop={8}
                disabled={!inputEnabled || sendingVoice}
                style={({ pressed }) => [
                  styles.circleBtn,
                  { borderColor: inputEnabled ? circleBorder : theme.placeholder },
                  pressed && { opacity: 0.7 },
                ]}
                accessibilityLabel={chrome.voiceMode ? '切换到键盘' : '切换到语音'}
              >
                {chrome.voiceMode ? (
                  <AppstoreOutlined size={20} color={inputEnabled ? theme.text : theme.placeholder} />
                ) : (
                  <SoundOutlined size={20} color={inputEnabled ? theme.text : theme.placeholder} />
                )}
              </Pressable>
            ) : null}

            {SHOW_VOICE_ENTRY && chrome.voiceMode ? (
              chrome.isWeb ? (
                <Pressable
                  onPress={() => { void chrome.handleWebClickStart(); }}
                  disabled={!inputEnabled || sendingVoice}
                  style={({ pressed }) => [
                    styles.holdBtn,
                    {
                      backgroundColor: theme.surface2,
                      borderColor: theme.divider,
                      opacity: pressed ? 0.92 : 1,
                    },
                  ]}
                  accessibilityLabel="点击说话"
                >
                  {sendingVoice ? (
                    <ActivityIndicator size="small" color={theme.textSubtle} />
                  ) : (
                    <Text style={[styles.holdBtnText, { color: theme.text }]}>点击 说话</Text>
                  )}
                </Pressable>
              ) : (
                <Pressable
                  ref={(node) => {
                    holdBtnRef.current = node;
                  }}
                  onLayout={(e) => {
                    chrome.onHoldLayout(e);
                    chrome.measureHoldBtn(holdBtnRef.current);
                  }}
                  onPressIn={(e) => {
                    chrome.measureHoldBtn(holdBtnRef.current);
                    void chrome.handleHoldStart(e);
                  }}
                  onPressOut={chrome.handleHoldEnd}
                  onResponderMove={chrome.handleHoldMove}
                  onTouchMove={chrome.handleHoldMove}
                  disabled={!inputEnabled || sendingVoice}
                  style={({ pressed }) => [
                    styles.holdBtn,
                    {
                      backgroundColor: theme.surface2,
                      borderColor: theme.divider,
                      opacity: pressed || chrome.recording ? 0.92 : 1,
                    },
                  ]}
                  accessibilityLabel="按住说话"
                >
                  {sendingVoice ? (
                    <ActivityIndicator size="small" color={theme.textSubtle} />
                  ) : (
                    <Text style={[styles.holdBtnText, { color: theme.text }]}>按住 说话</Text>
                  )}
                </Pressable>
              )
            ) : (
              <ChatComposer
                ref={composerRef}
                value={draft}
                onChangeText={onChangeDraft}
                onFocus={() => {
                  chrome.onComposerFocus();
                  onComposerFocus?.();
                }}
                onSubmitEditing={(text) => onSend(text)}
                editable={inputEnabled}
                placeholder={inputPlaceholder}
                placeholderTextColor={theme.placeholder}
                textColor={theme.text}
                backgroundColor={theme.surface2}
                maxLength={5000}
              />
            )}

            <View style={styles.trailingActions}>
              <Pressable
                onPress={chrome.handleToggleEmojiPanel}
                hitSlop={8}
                disabled={!inputEnabled}
                style={({ pressed }) => [
                  styles.actionBtn,
                  chrome.emojiPanelOpen && { backgroundColor: theme.primarySoft },
                  pressed && { opacity: 0.7 },
                ]}
                accessibilityLabel="选择表情"
                accessibilityState={{ selected: chrome.emojiPanelOpen }}
              >
                <SmileOutlined
                  size={34}
                  color={
                    !inputEnabled
                      ? theme.placeholder
                      : chrome.emojiPanelOpen
                        ? theme.primary
                        : theme.textSubtle
                  }
                />
              </Pressable>
              <Pressable
                onPress={chrome.handleToggleAttachPanel}
                hitSlop={8}
                disabled={!inputEnabled}
                style={({ pressed }) => [
                  styles.attachBtn,
                  inputEnabled && chrome.attachPanelOpen
                    ? {
                        borderColor: theme.primary,
                        backgroundColor: theme.primarySoft,
                      }
                    : {
                        borderColor: inputEnabled ? circleBorder : theme.placeholder,
                        backgroundColor: 'transparent',
                      },
                  pressed && { opacity: 0.7 },
                ]}
                accessibilityLabel="更多操作"
                accessibilityState={{ selected: chrome.attachPanelOpen }}
              >
                {chrome.attachPanelOpen ? (
                  <CloseOutlined
                    size={22}
                    color={!inputEnabled ? theme.placeholder : theme.primary}
                  />
                ) : (
                  <PlusOutlined
                    size={22}
                    color={!inputEnabled ? theme.placeholder : theme.textSubtle}
                  />
                )}
              </Pressable>
            </View>
          </>
        )}
      </View>
      {chrome.attachPanelOpen && inputEnabled && !showWebRecordingBar ? (
        <View
          style={{
            paddingBottom: keyboardVisible ? 8 : Math.max(bottomInset, 8),
            backgroundColor: theme.surface,
          }}
        >
          <View style={[styles.attachPanel, { borderTopColor: theme.divider }]}>
            <Pressable
              style={({ pressed }) => [styles.attachPanelItem, pressed && { opacity: 0.7 }]}
              onPress={onPickImage}
            >
              <View style={[styles.attachPanelIcon, { backgroundColor: theme.surface2 }]}>
                <PictureOutlined size={26} color={theme.textSubtle} />
              </View>
              <Text style={[styles.attachPanelLabel, { color: theme.textSubtle }]}>照片</Text>
            </Pressable>
            {!chrome.isWeb ? (
              <Pressable
                style={({ pressed }) => [styles.attachPanelItem, pressed && { opacity: 0.7 }]}
                onPress={onTakePhoto}
              >
                <View style={[styles.attachPanelIcon, { backgroundColor: theme.surface2 }]}>
                  <CameraOutlined size={26} color={theme.textSubtle} />
                </View>
                <Text style={[styles.attachPanelLabel, { color: theme.textSubtle }]}>拍照</Text>
              </Pressable>
            ) : null}
            <Pressable
              style={({ pressed }) => [styles.attachPanelItem, pressed && { opacity: 0.7 }]}
              onPress={onPickVideo}
            >
              <View style={[styles.attachPanelIcon, { backgroundColor: theme.surface2 }]}>
                <VideoCameraOutlined size={26} color={theme.textSubtle} />
              </View>
              <Text style={[styles.attachPanelLabel, { color: theme.textSubtle }]}>视频</Text>
            </Pressable>
            <Pressable
              style={({ pressed }) => [styles.attachPanelItem, pressed && { opacity: 0.7 }]}
              onPress={onPickFile}
            >
              <View style={[styles.attachPanelIcon, { backgroundColor: theme.surface2 }]}>
                <FolderOpenOutlined size={26} color={theme.textSubtle} />
              </View>
              <Text style={[styles.attachPanelLabel, { color: theme.textSubtle }]}>文件</Text>
            </Pressable>
          </View>
        </View>
      ) : null}
      {inputEnabled && !showWebRecordingBar && chrome.emojiPanelOpen ? (
        <View
          style={{
            height: EMOJI_PANEL_HEIGHT + (keyboardVisible ? 8 : Math.max(bottomInset, 8)),
            overflow: 'hidden',
            backgroundColor: '#FFFFFF',
          }}
        >
          <EmojiPanel
            onSelectEmoji={chrome.handleInsertEmoji}
            onDelete={chrome.handleBackspace}
            onSend={chrome.handleEmojiSend}
            canSend={!!draft.trim()}
            onSelectSticker={onSendSticker}
            backgroundColor="#FFFFFF"
            borderColor={theme.divider}
            primaryColor={theme.primary}
            iconColor={theme.textSubtle}
            disabledColor={theme.divider}
          />
          <View
            style={{
              height: keyboardVisible ? 8 : Math.max(bottomInset, 8),
              backgroundColor: '#FFFFFF',
            }}
          />
        </View>
      ) : null}

      {!chrome.isWeb ? <VoiceRecordingOverlay visible={chrome.recording} zone={chrome.recordZone} /> : null}
    </>
  );
});

const styles = StyleSheet.create({
  lockBanner: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 14, paddingVertical: 8, borderTopWidth: StyleSheet.hairlineWidth },
  lockText: { fontSize: 13, fontWeight: '500' },
  lockCountdown: { marginLeft: -2, fontVariant: ['tabular-nums'] },
  inputBar: { flexDirection: 'row', alignItems: 'flex-end', paddingHorizontal: 10, paddingTop: 8, borderTopWidth: StyleSheet.hairlineWidth, gap: 8 },
  circleBtn: {
    width: 32,
    height: 32,
    borderRadius: 16,
    borderWidth: StyleSheet.hairlineWidth * 2,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 2,
  },
  trailingActions: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 2,
  },
  actionBtn: {
    width: 34,
    height: 34,
    borderRadius: 17,
    alignItems: 'center',
    justifyContent: 'center',
  },
  attachBtn: {
    width: 30,
    height: 30,
    borderRadius: 15,
    borderWidth: 2.5,
    alignItems: 'center',
    justifyContent: 'center',
  },
  holdBtn: {
    flex: 1,
    minHeight: 36,
    borderRadius: 6,
    borderWidth: StyleSheet.hairlineWidth,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 8,
    paddingHorizontal: 12,
  },
  holdBtnText: {
    fontSize: 16,
    fontWeight: '600',
    letterSpacing: 1,
  },
  attachPanel: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    paddingHorizontal: 8,
    paddingTop: 16,
    paddingBottom: 12,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  attachPanelItem: { width: '25%', alignItems: 'center', gap: 8, paddingHorizontal: 4 },
  attachPanelIcon: {
    width: 56,
    height: 56,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  attachPanelLabel: { fontSize: 12, lineHeight: 16 },
});
