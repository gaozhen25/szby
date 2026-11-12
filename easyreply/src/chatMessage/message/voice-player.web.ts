type PlayHandle = {
  stop: () => void;
  pause: () => void;
  audio: HTMLAudioElement | null;
};

let current: {
  url: string;
  audio: HTMLAudioElement;
  stop: () => void;
  onEnded?: () => void;
} | null = null;

function unloadAudio(audio: HTMLAudioElement): void {
  audio.ontimeupdate = null;
  audio.onended = null;
  audio.onerror = null;
  try {
    audio.pause();
    audio.removeAttribute('src');
    audio.load();
  } catch {
    /* ignore */
  }
}

/** Web：HTMLAudioElement 播放 */
export function playVoiceUrl(
  url: string,
  onEnded?: () => void,
  onTimeUpdate?: (currentTime: number, duration: number) => void,
): PlayHandle {
  if (typeof Audio === 'undefined' || !url) {
    onEnded?.();
    return { stop: () => undefined, pause: () => undefined, audio: null };
  }

  if (current?.url === url && current.audio && !current.audio.ended) {
    const audio = current.audio;
    current.onEnded = onEnded;
    audio.ontimeupdate = () => {
      const dur = Number.isFinite(audio.duration) ? audio.duration : 0;
      onTimeUpdate?.(audio.currentTime, dur);
    };
    audio.onended = () => {
      if (current?.audio === audio) current = null;
      onEnded?.();
    };
    audio.onerror = () => {
      if (current?.audio === audio) {
        unloadAudio(audio);
        current = null;
      }
      onEnded?.();
    };
    void audio.play().catch(() => {
      if (current?.audio === audio) {
        current.stop();
        current = null;
      }
      onEnded?.();
    });
    return {
      stop: current.stop,
      pause: () => audio.pause(),
      audio,
    };
  }

  stopVoicePlayback();
  const audio = new Audio(url);
  const stop = () => {
    unloadAudio(audio);
    if (current?.audio === audio) current = null;
  };
  audio.ontimeupdate = () => {
    const dur = Number.isFinite(audio.duration) ? audio.duration : 0;
    onTimeUpdate?.(audio.currentTime, dur);
  };
  audio.onended = () => {
    if (current?.audio === audio) current = null;
    onEnded?.();
  };
  audio.onerror = () => {
    stop();
    onEnded?.();
  };
  current = { url, audio, stop, onEnded };
  void audio.play().catch(() => {
    stop();
    onEnded?.();
  });
  return {
    stop,
    pause: () => audio.pause(),
    audio,
  };
}

export function stopVoicePlayback(): void {
  const prev = current;
  current = null;
  if (!prev) return;
  prev.stop();
  prev.onEnded?.();
}
