import { useCallback, useEffect, useRef, useState, type RefObject } from 'react';
import { Keyboard, Platform, type GestureResponderEvent, type LayoutChangeEvent } from 'react-native';
import { appAlert } from '@/lib/app-alert';
import type { ChatComposerHandle } from '@/chatMessage/components/ChatComposer.types';
import type { VoiceRecordGestureZone } from '@/chatMessage/components/VoiceRecordingOverlay';
import {
  cancelVoiceRecording,
  isVoiceRecordingSupported,
  startVoiceRecording,
  stopVoiceRecording,
  type VoiceRecorderResult,
} from '@/chatMessage/message/voice-recorder';

const MIN_VOICE_SEC = 0.8;
const MAX_VOICE_SEC = 60;
const isWeb = Platform.OS === 'web';

/**
 * 输入区交互：表情/附件互斥、收键盘、语音录制状态。
 * 不包含排版。
 */
export function useComposerChrome(opts: {
  inputEnabled: boolean;
  sendingVoice: boolean;
  onSend: () => void;
  onSendVoice: (result: VoiceRecorderResult) => void;
  composerRef: RefObject<ChatComposerHandle | null>;
}) {
  const { inputEnabled, sendingVoice, onSend, onSendVoice, composerRef } = opts;

  const [emojiPanelOpen, setEmojiPanelOpen] = useState(false);
  const [attachPanelOpen, setAttachPanelOpen] = useState(false);
  const [voiceMode, setVoiceMode] = useState(false);
  const [recording, setRecording] = useState(false);
  const [recordZone, setRecordZone] = useState<VoiceRecordGestureZone>('send');
  const insertingEmojiRef = useRef(false);
  const holdBtnLayoutRef = useRef({ x: 0, y: 0, width: 0, height: 0 });
  const recordingRef = useRef(false);
  const finishingRef = useRef(false);
  const zoneRef = useRef<VoiceRecordGestureZone>('send');
  const maxTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const closePanelsAndBlur = useCallback(() => {
    setEmojiPanelOpen(false);
    setAttachPanelOpen(false);
    composerRef.current?.blur();
    if (Platform.OS !== 'web') Keyboard.dismiss();
    if (Platform.OS !== 'web') {
      requestAnimationFrame(() => composerRef.current?.blur());
      setTimeout(() => {
        composerRef.current?.blur();
        Keyboard.dismiss();
      }, 50);
    }
  }, [composerRef]);

  useEffect(() => {
    if (!inputEnabled) {
      setVoiceMode(false);
      setEmojiPanelOpen(false);
      setAttachPanelOpen(false);
      if (recordingRef.current) {
        recordingRef.current = false;
        setRecording(false);
        void cancelVoiceRecording();
      }
    }
  }, [inputEnabled]);

  useEffect(() => {
    return () => {
      if (maxTimerRef.current) clearTimeout(maxTimerRef.current);
      void cancelVoiceRecording();
    };
  }, []);

  const clearMaxTimer = useCallback(() => {
    if (maxTimerRef.current) {
      clearTimeout(maxTimerRef.current);
      maxTimerRef.current = null;
    }
  }, []);

  const armMaxTimer = useCallback((onTimeout: () => void) => {
    clearMaxTimer();
    maxTimerRef.current = setTimeout(onTimeout, MAX_VOICE_SEC * 1000);
  }, [clearMaxTimer]);

  const handleInsertEmoji = useCallback((name: string) => {
    insertingEmojiRef.current = true;
    composerRef.current?.insertEmoji(name);
    setTimeout(() => {
      insertingEmojiRef.current = false;
    }, 500);
  }, [composerRef]);

  const handleBackspace = useCallback(() => {
    insertingEmojiRef.current = true;
    composerRef.current?.backspace();
    setTimeout(() => {
      insertingEmojiRef.current = false;
    }, 500);
  }, [composerRef]);

  const handleEmojiSend = useCallback(() => {
    insertingEmojiRef.current = true;
    composerRef.current?.blur();
    const finish = () => {
      onSend();
      requestAnimationFrame(() => composerRef.current?.blur());
      setTimeout(() => {
        insertingEmojiRef.current = false;
        composerRef.current?.blur();
      }, 300);
    };
    if (Platform.OS === 'ios') {
      setTimeout(finish, 60);
    } else {
      finish();
    }
  }, [composerRef, onSend]);

  const handleToggleEmojiPanel = useCallback(() => {
    setAttachPanelOpen(false);
    if (voiceMode) setVoiceMode(false);
    setEmojiPanelOpen((v) => {
      const next = !v;
      if (next) {
        requestAnimationFrame(() => composerRef.current?.blur());
      } else {
        composerRef.current?.blur();
      }
      return next;
    });
  }, [composerRef, voiceMode]);

  const handleToggleAttachPanel = useCallback(() => {
    composerRef.current?.blur();
    setEmojiPanelOpen(false);
    if (voiceMode) setVoiceMode(false);
    setAttachPanelOpen((v) => !v);
  }, [composerRef, voiceMode]);

  const handleToggleVoiceMode = useCallback(() => {
    if (!inputEnabled || recordingRef.current) return;
    if (!voiceMode && !isVoiceRecordingSupported()) {
      const insecureWeb =
        isWeb
        && typeof window !== 'undefined'
        && window.isSecureContext === false;
      appAlert(
        '暂不支持录音',
        insecureWeb
          ? '当前页面不是安全上下文。请用 https 打开，或本机用 http://localhost 访问（不要用局域网 IP 的 http）'
          : isWeb
            ? '当前浏览器无法使用麦克风，请换用 Chrome / Safari'
            : '当前客户端缺少录音能力，请更新到最新版本后重试',
      );
      return;
    }
    setEmojiPanelOpen(false);
    setAttachPanelOpen(false);
    composerRef.current?.blur();
    setVoiceMode((v) => !v);
  }, [composerRef, inputEnabled, voiceMode]);

  const resolveZone = useCallback((pageX: number, pageY: number): VoiceRecordGestureZone => {
    const { x, y, width, height } = holdBtnLayoutRef.current;
    const midX = x + width / 2;
    if (pageY < y - 48) {
      if (pageX < midX) return 'cancel';
      return 'convert';
    }
    if (pageY < y + height && pageX < x - 8) return 'cancel';
    if (pageY < y + height && pageX > x + width + 8) return 'convert';
    return 'send';
  }, []);

  const finishRecording = useCallback(
    async (zone: VoiceRecordGestureZone) => {
      if (!recordingRef.current || finishingRef.current) return;
      finishingRef.current = true;
      clearMaxTimer();
      recordingRef.current = false;
      setRecording(false);
      setRecordZone('send');

      try {
        if (zone === 'cancel') {
          await cancelVoiceRecording();
          return;
        }
        if (zone === 'convert') {
          await cancelVoiceRecording();
          appAlert('暂不支持', '语音转文字功能即将上线');
          return;
        }

        const result = await stopVoiceRecording();
        if (!result) {
          appAlert('录音失败', '未采集到有效音频，请重试');
          return;
        }
        if (result.durationSec < MIN_VOICE_SEC) {
          appAlert('说话时间太短', isWeb ? '请点击说话后再试' : '请按住说话');
          return;
        }
        onSendVoice(result);
      } finally {
        finishingRef.current = false;
      }
    },
    [onSendVoice, clearMaxTimer],
  );

  const handleWebClickStart = useCallback(async () => {
    if (!inputEnabled || sendingVoice || recordingRef.current) return;
    try {
      await startVoiceRecording();
    } catch (err) {
      appAlert('无法录音', err instanceof Error ? err.message : '请检查麦克风权限');
      return;
    }
    recordingRef.current = true;
    zoneRef.current = 'send';
    setRecordZone('send');
    setRecording(true);
    armMaxTimer(() => {
      void finishRecording('send');
    });
  }, [inputEnabled, sendingVoice, armMaxTimer, finishRecording]);

  const handleWebCancel = useCallback(() => {
    void finishRecording('cancel');
  }, [finishRecording]);

  const handleWebSend = useCallback(() => {
    void finishRecording('send');
  }, [finishRecording]);

  const handleHoldStart = useCallback(
    async (e: GestureResponderEvent) => {
      if (isWeb || !inputEnabled || sendingVoice || recordingRef.current) return;
      const pageX = e.nativeEvent.pageX;
      const pageY = e.nativeEvent.pageY;
      try {
        await startVoiceRecording();
      } catch (err) {
        appAlert('无法录音', err instanceof Error ? err.message : '请检查麦克风权限');
        return;
      }
      recordingRef.current = true;
      zoneRef.current = resolveZone(pageX, pageY);
      setRecordZone(zoneRef.current);
      setRecording(true);
      armMaxTimer(() => {
        void finishRecording(zoneRef.current);
      });
    },
    [inputEnabled, sendingVoice, resolveZone, finishRecording, armMaxTimer],
  );

  const handleHoldMove = useCallback(
    (e: GestureResponderEvent) => {
      if (isWeb || !recordingRef.current) return;
      const next = resolveZone(e.nativeEvent.pageX, e.nativeEvent.pageY);
      if (next !== zoneRef.current) {
        zoneRef.current = next;
        setRecordZone(next);
      }
    },
    [resolveZone],
  );

  const handleHoldEnd = useCallback(() => {
    if (isWeb || !recordingRef.current) return;
    void finishRecording(zoneRef.current);
  }, [finishRecording]);

  const onHoldLayout = useCallback((e: LayoutChangeEvent) => {
    const { width, height } = e.nativeEvent.layout;
    holdBtnLayoutRef.current = { ...holdBtnLayoutRef.current, width, height };
  }, []);

  const measureHoldBtn = useCallback((target: { measureInWindow: (cb: (x: number, y: number, width: number, height: number) => void) => void } | null) => {
    target?.measureInWindow((x, y, width, height) => {
      holdBtnLayoutRef.current = { x, y, width, height };
    });
  }, []);

  const onComposerFocus = useCallback(() => {
    if (insertingEmojiRef.current) return;
    setEmojiPanelOpen(false);
    setAttachPanelOpen(false);
  }, []);

  return {
    isWeb,
    emojiPanelOpen,
    attachPanelOpen,
    voiceMode,
    recording,
    recordZone,
    showWebRecordingBar: isWeb && recording,
    closeAttachPanel: () => setAttachPanelOpen(false),
    dismissKeyboard: closePanelsAndBlur,
    handleInsertEmoji,
    handleBackspace,
    handleEmojiSend,
    handleToggleEmojiPanel,
    handleToggleAttachPanel,
    handleToggleVoiceMode,
    handleWebClickStart,
    handleWebCancel,
    handleWebSend,
    handleHoldStart,
    handleHoldMove,
    handleHoldEnd,
    onHoldLayout,
    measureHoldBtn,
    onComposerFocus,
  };
}
