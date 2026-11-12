/**
 * Web：将录音 Blob（多为 webm/opus）转为后台白名单格式 audio/mpeg（mp3）。
 * 使用 @breezystack/lamejs（修复原 lamejs 的 MPEGMode is not defined）。
 */
import { Mp3Encoder } from '@breezystack/lamejs';

export async function encodeVoiceBlobToMp3(input: Blob): Promise<Blob> {
  if (input.type.includes('mpeg') || input.type.includes('mp3')) {
    return input.type === 'audio/mpeg' ? input : new Blob([input], { type: 'audio/mpeg' });
  }

  const AudioCtx =
    typeof AudioContext !== 'undefined'
      ? AudioContext
      : (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!AudioCtx) {
    throw new Error('当前浏览器不支持音频转码');
  }

  const ctx = new AudioCtx();
  try {
    const ab = await input.arrayBuffer();
    const audioBuffer = await ctx.decodeAudioData(ab.slice(0));
    const channels = Math.min(2, audioBuffer.numberOfChannels) as 1 | 2;
    const sampleRate = audioBuffer.sampleRate;
    const left = audioBuffer.getChannelData(0);
    const right = channels > 1 ? audioBuffer.getChannelData(1) : left;

    const encoder = new Mp3Encoder(channels, sampleRate, 128);
    const blockSize = 1152;
    const parts: ArrayBuffer[] = [];

    for (let i = 0; i < left.length; i += blockSize) {
      const leftChunk = floatTo16BitPCM(left, i, blockSize);
      const mp3buf =
        channels === 1
          ? encoder.encodeBuffer(leftChunk)
          : encoder.encodeBuffer(leftChunk, floatTo16BitPCM(right, i, blockSize));
      if (mp3buf.length > 0) parts.push(copyToArrayBuffer(mp3buf));
    }
    const flush = encoder.flush();
    if (flush.length > 0) parts.push(copyToArrayBuffer(flush));

    if (!parts.length) {
      throw new Error('音频转码失败');
    }
    return new Blob(parts, { type: 'audio/mpeg' });
  } finally {
    void ctx.close();
  }
}

function floatTo16BitPCM(input: Float32Array, offset: number, length: number): Int16Array {
  const end = Math.min(offset + length, input.length);
  const out = new Int16Array(end - offset);
  for (let i = 0, j = offset; j < end; i++, j++) {
    const s = Math.max(-1, Math.min(1, input[j] ?? 0));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}

function copyToArrayBuffer(data: Int8Array | Uint8Array): ArrayBuffer {
  const copy = new Uint8Array(data.length);
  copy.set(data);
  return copy.buffer;
}
