import { Platform } from 'react-native';
import type { VoiceRecorderResult } from '@/chatMessage/message/voice-recorder';

/**
 * 将本地录音整理为后台白名单可接受格式后再上传：
 * - audio/mpeg（mp3）
 * - audio/aac
 */
export async function prepareVoiceForUpload(
  result: VoiceRecorderResult,
): Promise<VoiceRecorderResult> {
  if (Platform.OS === 'web') {
    const rawBlob: Blob =
      result.blob
      ?? (await fetch(result.uri).then((r) => r.blob()));
    const alreadyMp3 =
      rawBlob.type.includes('mpeg')
      || rawBlob.type.includes('mp3')
      || result.mimeType.includes('mpeg')
      || result.fileName.endsWith('.mp3');

    let blob: Blob = rawBlob;
    if (!alreadyMp3) {
      const { encodeVoiceBlobToMp3 } = await import('@/chatMessage/message/encode-voice-mp3');
      blob = await encodeVoiceBlobToMp3(rawBlob);
    } else if (blob.type !== 'audio/mpeg') {
      blob = new Blob([blob], { type: 'audio/mpeg' });
    }

    const uri = URL.createObjectURL(blob);
    if (result.uri.startsWith('blob:') && result.uri !== uri) {
      try {
        URL.revokeObjectURL(result.uri);
      } catch {
        /* ignore */
      }
    }
    return {
      uri,
      blob,
      durationSec: result.durationSec,
      size: blob.size,
      mimeType: 'audio/mpeg',
      fileName: `voice-${Date.now()}.mp3`,
    };
  }

  // Android / iOS：expo-audio HIGH_QUALITY 产出 AAC 音频，走 audio/aac 白名单
  const baseName = result.fileName.replace(/\.\w+$/, '') || `voice-${Date.now()}`;
  return {
    ...result,
    fileName: `${baseName}.aac`,
    mimeType: 'audio/aac',
  };
}
