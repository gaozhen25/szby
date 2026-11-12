type PlayHandle = {
  stop: () => void;
};

type ExpoAudioModule = typeof import('expo-audio');

let audio: ExpoAudioModule | null = null;
try {
  // 动态加载：未打进原生包时避免 import 阶段直接白屏崩溃
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  audio = require('expo-audio') as ExpoAudioModule;
} catch (e) {
  console.warn('[voice-player] expo-audio 原生模块不可用，请重新编译安装 App', e);
}

type AudioPlayer = ReturnType<NonNullable<ExpoAudioModule>['createAudioPlayer']>;

let current: { player: AudioPlayer; stop: () => void } | null = null;

/** Android / iOS：expo-audio 播放 */
export function playVoiceUrl(url: string, onEnded?: () => void): PlayHandle {
  if (!audio) {
    onEnded?.();
    return { stop: () => undefined };
  }

  stopVoicePlayback();
  if (!url) {
    onEnded?.();
    return { stop: () => undefined };
  }

  void audio.setAudioModeAsync({
    playsInSilentMode: true,
    allowsRecording: false,
  });

  const player = audio.createAudioPlayer(url, { updateInterval: 250 });
  const stop = () => {
    try {
      player.pause();
      player.remove();
    } catch {
      /* ignore */
    }
    if (current?.player === player) current = null;
  };

  const sub = player.addListener('playbackStatusUpdate', (status) => {
    if (status.didJustFinish) {
      sub.remove();
      stop();
      onEnded?.();
    }
  });

  current = { player, stop };
  try {
    player.play();
  } catch {
    stop();
    onEnded?.();
  }
  return { stop };
}

export function stopVoicePlayback(): void {
  current?.stop();
  current = null;
}
