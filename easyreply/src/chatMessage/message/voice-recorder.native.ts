import * as FileSystem from 'expo-file-system/legacy';
import { Platform } from 'react-native';

export type VoiceRecorderResult = {
  uri: string;
  blob?: Blob;
  durationSec: number;
  size: number;
  mimeType: string;
  fileName: string;
};

type ExpoAudioModule = typeof import('expo-audio');

let audio: ExpoAudioModule | null = null;
try {
  // 动态加载：未打进原生包时避免 import 阶段直接白屏崩溃
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  audio = require('expo-audio') as ExpoAudioModule;
} catch (e) {
  console.warn('[voice-recorder] expo-audio 原生模块不可用，请重新编译安装 App', e);
}

type ActiveNativeRecording = {
  recorder: InstanceType<ExpoAudioModule['AudioModule']['AudioRecorder']>;
  startedAt: number;
};

let active: ActiveNativeRecording | null = null;

function toPlatformOptions(options: Record<string, unknown>): Record<string, unknown> {
  const common = {
    extension: options.extension,
    sampleRate: options.sampleRate,
    numberOfChannels: options.numberOfChannels,
    bitRate: options.bitRate,
    isMeteringEnabled: options.isMeteringEnabled ?? false,
  };
  if (Platform.OS === 'ios') {
    return { ...common, ...((options.ios as object) || {}) };
  }
  return { ...common, ...((options.android as object) || {}) };
}

/** Android / iOS：expo-audio */
export function isVoiceRecordingSupported(): boolean {
  return typeof audio?.AudioModule?.AudioRecorder === 'function';
}

export async function startVoiceRecording(): Promise<void> {
  if (!audio) {
    throw new Error('当前安装包未包含录音模块，请重新编译安装 App 后再试');
  }
  if (active) {
    await cancelVoiceRecording();
  }

  const permission = await audio.requestRecordingPermissionsAsync();
  if (!permission.granted) {
    throw new Error('需要麦克风权限，请在系统设置中允许录音');
  }

  await audio.setAudioModeAsync({
    playsInSilentMode: true,
    allowsRecording: true,
  });

  const options = toPlatformOptions(
    audio.RecordingPresets.HIGH_QUALITY as unknown as Record<string, unknown>,
  );
  const recorder = new audio.AudioModule.AudioRecorder(options);
  await recorder.prepareToRecordAsync();
  recorder.record();
  active = { recorder, startedAt: Date.now() };
}

export async function cancelVoiceRecording(): Promise<void> {
  const cur = active;
  active = null;
  if (!cur) return;
  try {
    if (cur.recorder.isRecording) {
      await cur.recorder.stop();
    }
  } catch {
    /* ignore */
  }
  try {
    cur.recorder.release();
  } catch {
    /* ignore */
  }
  try {
    await audio?.setAudioModeAsync({ allowsRecording: false });
  } catch {
    /* ignore */
  }
}

export async function stopVoiceRecording(): Promise<VoiceRecorderResult | null> {
  const cur = active;
  active = null;
  if (!cur) return null;

  const durationSec = Math.max(
    0,
    cur.recorder.currentTime || (Date.now() - cur.startedAt) / 1000,
  );

  try {
    await cur.recorder.stop();
  } catch {
    /* ignore */
  }

  const uri = cur.recorder.uri;
  try {
    cur.recorder.release();
  } catch {
    /* ignore */
  }
  try {
    await audio?.setAudioModeAsync({ allowsRecording: false });
  } catch {
    /* ignore */
  }

  if (!uri) return null;

  let size = 0;
  try {
    const info = await FileSystem.getInfoAsync(uri);
    if (info.exists && typeof info.size === 'number') size = info.size;
  } catch {
    /* ignore */
  }

  return {
    uri,
    durationSec,
    size,
    mimeType: 'audio/mp4',
    fileName: `voice-${Date.now()}.m4a`,
  };
}
