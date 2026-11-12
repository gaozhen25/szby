export type VoiceRecorderResult = {
  uri: string;
  blob?: Blob;
  durationSec: number;
  size: number;
  mimeType: string;
  fileName: string;
};

type ActiveRecording = {
  mediaRecorder: MediaRecorder;
  stream: MediaStream;
  chunks: Blob[];
  startedAt: number;
  mimeType: string;
};

let active: ActiveRecording | null = null;

function pickMimeType(): string {
  if (typeof MediaRecorder === 'undefined') return '';
  const candidates = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/mp4',
    'audio/mpeg',
    'audio/aac',
    'audio/ogg',
  ];
  for (const type of candidates) {
    if (MediaRecorder.isTypeSupported(type)) return type;
  }
  return '';
}

function extForMime(mimeType: string): string {
  if (mimeType.includes('webm')) return 'webm';
  if (mimeType.includes('ogg')) return 'ogg';
  if (mimeType.includes('mp4') || mimeType.includes('aac') || mimeType.includes('m4a')) return 'm4a';
  if (mimeType.includes('mpeg') || mimeType.includes('mp3')) return 'mp3';
  return 'webm';
}

function isSecureMicContext(): boolean {
  if (typeof window === 'undefined') return false;
  // Chrome：非安全上下文（如 http://局域网IP）下 mediaDevices 会是 undefined
  return window.isSecureContext === true;
}

/** Web：浏览器 MediaRecorder（不依赖 ExpoAudio 原生模块） */
export function isVoiceRecordingSupported(): boolean {
  return (
    isSecureMicContext()
    && typeof navigator !== 'undefined'
    && !!navigator.mediaDevices?.getUserMedia
    && typeof MediaRecorder !== 'undefined'
  );
}

export async function startVoiceRecording(): Promise<void> {
  if (active) {
    await cancelVoiceRecording();
  }
  if (!isSecureMicContext()) {
    throw new Error('浏览器要求 https 或 localhost 才能使用麦克风');
  }
  if (!isVoiceRecordingSupported()) {
    throw new Error('当前浏览器不支持录音');
  }

  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const mimeType = pickMimeType();
  const mediaRecorder = mimeType
    ? new MediaRecorder(stream, { mimeType })
    : new MediaRecorder(stream);
  const chunks: Blob[] = [];
  mediaRecorder.ondataavailable = (ev) => {
    if (ev.data && ev.data.size > 0) chunks.push(ev.data);
  };
  active = {
    mediaRecorder,
    stream,
    chunks,
    startedAt: Date.now(),
    mimeType: mediaRecorder.mimeType || mimeType || 'audio/webm',
  };
  mediaRecorder.start(100);
}

function stopTracks(stream: MediaStream) {
  stream.getTracks().forEach((t) => {
    try {
      t.stop();
    } catch {
      /* ignore */
    }
  });
}

export async function cancelVoiceRecording(): Promise<void> {
  const cur = active;
  active = null;
  if (!cur) return;
  try {
    if (cur.mediaRecorder.state !== 'inactive') cur.mediaRecorder.stop();
  } catch {
    /* ignore */
  }
  stopTracks(cur.stream);
}

export async function stopVoiceRecording(): Promise<VoiceRecorderResult | null> {
  const cur = active;
  active = null;
  if (!cur) return null;

  const durationSec = Math.max(0, (Date.now() - cur.startedAt) / 1000);
  const blob = await new Promise<Blob | null>((resolve) => {
    const finish = () => {
      const type = cur.mimeType || 'audio/webm';
      if (!cur.chunks.length) {
        resolve(null);
        return;
      }
      resolve(new Blob(cur.chunks, { type }));
    };
    if (cur.mediaRecorder.state === 'inactive') {
      finish();
      return;
    }
    cur.mediaRecorder.onstop = finish;
    try {
      cur.mediaRecorder.stop();
    } catch {
      finish();
    }
  });
  stopTracks(cur.stream);
  if (!blob || blob.size === 0) return null;

  const mimeType = blob.type || cur.mimeType || 'audio/webm';
  const ext = extForMime(mimeType);
  const fileName = `voice-${Date.now()}.${ext}`;
  const uri = URL.createObjectURL(blob);
  return {
    uri,
    blob,
    durationSec,
    size: blob.size,
    mimeType,
    fileName,
  };
}
