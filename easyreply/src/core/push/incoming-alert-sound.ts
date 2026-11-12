// ============================================================
// 前台新消息提示音（不依赖系统通知渠道）
// ============================================================
import { Platform, Vibration } from 'react-native';

type ExpoAudioModule = typeof import('expo-audio');
type AudioPlayer = ReturnType<ExpoAudioModule['createAudioPlayer']>;

let audio: ExpoAudioModule | null | undefined;
let current: { player: AudioPlayer; stop: () => void } | null = null;
let lastPlayAt = 0;
const SOUND_THROTTLE_MS = 1200;

function getAudio(): ExpoAudioModule | null {
  if (audio !== undefined) return audio;
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    audio = require('expo-audio') as ExpoAudioModule;
  } catch {
    audio = null;
  }
  return audio;
}

function resolveSoundSource(): unknown {
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    return require('../../../assets/newMsg.mp3');
  } catch {
    return null;
  }
}

/** 播放提示音 + 短震。正在看同一会话时不要调用。 */
export function playNativeIncomingFeedback(): void {
  if (Platform.OS === 'web') return;
  const now = Date.now();
  if (now - lastPlayAt < SOUND_THROTTLE_MS) return;
  lastPlayAt = now;

  try {
    Vibration.vibrate(80);
  } catch {
    // ignore
  }

  const mod = getAudio();
  const src = resolveSoundSource();
  if (!mod || !src) return;

  try {
    void mod.setAudioModeAsync({
      playsInSilentMode: true,
      allowsRecording: false,
    });

    current?.stop();
    const next = mod.createAudioPlayer(src as never);
    const stop = () => {
      try {
        next.pause();
        next.remove();
      } catch {
        // ignore
      }
      if (current?.player === next) current = null;
    };
    const sub = next.addListener('playbackStatusUpdate', (status) => {
      if (status.didJustFinish) {
        sub.remove();
        stop();
      }
    });
    current = { player: next, stop };
    next.volume = 1;
    next.play();
  } catch (e) {
    console.warn('[Notify] play incoming sound failed', e);
  }
}
