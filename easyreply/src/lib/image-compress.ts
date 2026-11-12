import { Platform } from 'react-native';
import * as FileSystem from 'expo-file-system/legacy';
import { manipulateAsync, SaveFormat } from 'expo-image-manipulator';

/** 聊天图片上传目标上限（非 GIF） */
export const CHAT_IMAGE_MAX_BYTES = 500 * 1024;
/** GIF 动图不做 JPEG 压缩，允许原样上传的上限 */
export const CHAT_GIF_MAX_BYTES = 5 * 1024 * 1024;

export interface PreparedImage {
  uri: string;
  width?: number;
  height?: number;
  mimeType: string;
  fileName: string;
  size: number;
  /** Web 上可透传原始 Blob，避免二次 fetch 丢 type */
  blob?: Blob;
}

export type PrepareImageOptions = {
  mimeType?: string | null;
  fileName?: string | null;
  /** ImagePicker / DocumentPicker 给出的原始 File/Blob（Web） */
  blob?: Blob | null;
};

async function getFileMeta(
  uri: string,
  blob?: Blob | null,
): Promise<{ size: number; blobType?: string; blob?: Blob }> {
  if (blob) {
    return {
      size: blob.size,
      blobType: (blob.type || '').trim().toLowerCase() || undefined,
      blob,
    };
  }
  if (Platform.OS === 'web') {
    const res = await fetch(uri);
    const fetched = await res.blob();
    return {
      size: fetched.size,
      blobType: (fetched.type || '').trim().toLowerCase() || undefined,
      blob: fetched,
    };
  }
  const info = await FileSystem.getInfoAsync(uri);
  if (!info.exists) throw new Error('图片文件不存在');
  return { size: info.size ?? 0 };
}

async function getFileSize(uri: string): Promise<number> {
  const meta = await getFileMeta(uri);
  return meta.size;
}

function decodeBase64ToBytes(base64: string): Uint8Array {
  const normalized = base64.replace(/^data:[^;]+;base64,/, '');
  if (typeof atob === 'function') {
    const binary = atob(normalized);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return bytes;
  }
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=';
  let str = normalized.replace(/[^A-Za-z0-9+/=]/g, '');
  const out: number[] = [];
  for (let i = 0; i < str.length; i += 4) {
    const enc1 = chars.indexOf(str[i]!);
    const enc2 = chars.indexOf(str[i + 1]!);
    const enc3 = chars.indexOf(str[i + 2]!);
    const enc4 = chars.indexOf(str[i + 3]!);
    const chr1 = (enc1 << 2) | (enc2 >> 4);
    const chr2 = ((enc2 & 15) << 4) | (enc3 >> 2);
    const chr3 = ((enc3 & 3) << 6) | enc4;
    out.push(chr1);
    if (enc3 !== 64 && str[i + 2] !== undefined) out.push(chr2);
    if (enc4 !== 64 && str[i + 3] !== undefined) out.push(chr3);
  }
  return new Uint8Array(out);
}

function headerIsGif(bytes: Uint8Array | null | undefined): boolean {
  if (!bytes || bytes.length < 6) return false;
  return (
    bytes[0] === 0x47 &&
    bytes[1] === 0x49 &&
    bytes[2] === 0x46 &&
    bytes[3] === 0x38 &&
    (bytes[4] === 0x37 || bytes[4] === 0x39) &&
    bytes[5] === 0x61
  );
}

async function readHeaderBytes(
  uri: string,
  blob?: Blob | null,
  length = 6,
): Promise<Uint8Array | null> {
  try {
    if (blob) {
      const buf = await blob.slice(0, length).arrayBuffer();
      return new Uint8Array(buf);
    }
    if (Platform.OS === 'web') {
      const res = await fetch(uri);
      const buf = await res.arrayBuffer();
      return new Uint8Array(buf.slice(0, length));
    }
    try {
      const base64 = await FileSystem.readAsStringAsync(uri, {
        encoding: 'base64',
        length,
        position: 0,
      });
      return decodeBase64ToBytes(base64).slice(0, length);
    } catch {
      const res = await fetch(uri);
      const buf = await res.arrayBuffer();
      return new Uint8Array(buf.slice(0, length));
    }
  } catch {
    return null;
  }
}

function isGifHint(params: {
  uri: string;
  mimeType?: string | null;
  fileName?: string | null;
  blobType?: string;
}): boolean {
  const mime = (params.mimeType || params.blobType || '').trim().toLowerCase();
  if (mime === 'image/gif' || mime.endsWith('/gif')) return true;
  const name = (params.fileName || '').trim().toLowerCase();
  if (name.endsWith('.gif')) return true;
  const path = params.uri.split('?')[0].trim().toLowerCase();
  return path.endsWith('.gif');
}

function resolveStaticImageMimeType(params: {
  mimeType?: string | null;
  blobType?: string;
  fileName?: string | null;
}): string {
  const mime = (params.mimeType || params.blobType || '').trim().toLowerCase();
  if (mime.startsWith('image/')) return mime;
  const name = (params.fileName || '').trim().toLowerCase();
  if (name.endsWith('.png')) return 'image/png';
  if (name.endsWith('.webp')) return 'image/webp';
  if (name.endsWith('.jpg') || name.endsWith('.jpeg')) return 'image/jpeg';
  return 'image/jpeg';
}

function buildPreparedImage(params: {
  uri: string;
  width?: number;
  height?: number;
  mimeType: string;
  fileName?: string | null;
  size: number;
  blob?: Blob;
}): PreparedImage {
  const ext =
    params.mimeType === 'image/png'
      ? 'png'
      : params.mimeType === 'image/webp'
        ? 'webp'
        : params.mimeType === 'image/gif'
          ? 'gif'
          : 'jpg';
  const baseName = (params.fileName || '').trim().replace(/\.[^.]+$/, '');
  return {
    uri: params.uri,
    width: params.width,
    height: params.height,
    mimeType: params.mimeType,
    fileName: baseName ? `${baseName}.${ext}` : `image-${Date.now()}.${ext}`,
    size: params.size,
    blob: params.blob,
  };
}

async function compressImageWithCanvas(
  source: Blob,
  maxBytes: number,
  initialWidth?: number,
  initialHeight?: number,
): Promise<{ blob: Blob; width: number; height: number; uri: string }> {
  const bitmap = await createImageBitmap(source);
  const sourceWidth = initialWidth && initialWidth > 0 ? initialWidth : bitmap.width;
  const sourceHeight = initialHeight && initialHeight > 0 ? initialHeight : bitmap.height;

  const drawToBlob = (width: number, height: number, quality: number): Promise<Blob> =>
    new Promise((resolve, reject) => {
      const canvas = document.createElement('canvas');
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext('2d');
      if (!ctx) {
        reject(new Error('无法压缩图片'));
        return;
      }
      ctx.drawImage(bitmap, 0, 0, width, height);
      canvas.toBlob(
        (blob) => (blob ? resolve(blob) : reject(new Error('图片压缩失败'))),
        'image/jpeg',
        quality,
      );
    });

  try {
    for (let quality = 0.85; quality >= 0.35; quality -= 0.1) {
      const blob = await drawToBlob(sourceWidth, sourceHeight, quality);
      if (blob.size <= maxBytes) {
        return {
          blob,
          width: sourceWidth,
          height: sourceHeight,
          uri: URL.createObjectURL(blob),
        };
      }
    }

    for (let scale = 0.85; scale >= 0.35; scale -= 0.1) {
      const width = Math.max(320, Math.floor(sourceWidth * scale));
      const height = Math.max(320, Math.floor(sourceHeight * (width / sourceWidth)));
      const blob = await drawToBlob(width, height, 0.75);
      if (blob.size <= maxBytes) {
        return {
          blob,
          width,
          height,
          uri: URL.createObjectURL(blob),
        };
      }
    }
  } finally {
    bitmap.close?.();
  }

  throw new Error('图片压缩后仍超过 500KB，请换一张较小的图片');
}

async function compressStaticImage(
  uri: string,
  width: number | undefined,
  height: number | undefined,
  sourceBlob: Blob | undefined,
): Promise<PreparedImage> {
  if (Platform.OS === 'web') {
    const blob = sourceBlob ?? (await (await fetch(uri)).blob());
    const compressed = await compressImageWithCanvas(blob, CHAT_IMAGE_MAX_BYTES, width, height);
    return buildPreparedImage({
      uri: compressed.uri,
      width: compressed.width,
      height: compressed.height,
      mimeType: 'image/jpeg',
      size: compressed.blob.size,
      blob: compressed.blob,
    });
  }

  let currentUri = uri;
  let currentWidth = width;
  let currentHeight = height;
  let size = await getFileSize(currentUri);

  for (let quality = 0.85; quality >= 0.35; quality -= 0.1) {
    const result = await manipulateAsync(currentUri, [], {
      compress: quality,
      format: SaveFormat.JPEG,
    });
    currentUri = result.uri;
    currentWidth = result.width;
    currentHeight = result.height;
    size = await getFileSize(currentUri);
    if (size <= CHAT_IMAGE_MAX_BYTES) {
      return buildPreparedImage({
        uri: currentUri,
        width: currentWidth,
        height: currentHeight,
        mimeType: 'image/jpeg',
        size,
      });
    }
  }

  const baseWidth = currentWidth ?? width ?? 1280;
  for (let scale = 0.85; scale >= 0.35; scale -= 0.1) {
    const targetWidth = Math.max(320, Math.floor(baseWidth * scale));
    const result = await manipulateAsync(uri, [{ resize: { width: targetWidth } }], {
      compress: 0.75,
      format: SaveFormat.JPEG,
    });
    size = await getFileSize(result.uri);
    if (size <= CHAT_IMAGE_MAX_BYTES) {
      return buildPreparedImage({
        uri: result.uri,
        width: result.width,
        height: result.height,
        mimeType: 'image/jpeg',
        size,
      });
    }
  }

  throw new Error('图片压缩后仍超过 500KB，请换一张较小的图片');
}

/**
 * 准备上传用图片：
 * - GIF：不做 JPEG 压缩，≤5MB 原样上传，超出则拒绝
 * - 其它：压缩到 500KB 以内（已满足则原样上传）
 */
export async function prepareImageForUpload(
  uri: string,
  width?: number,
  height?: number,
  options?: PrepareImageOptions,
): Promise<PreparedImage> {
  const meta = await getFileMeta(uri, options?.blob);
  let size = meta.size;
  const header = await readHeaderBytes(uri, options?.blob ?? meta.blob);
  const gifByHeader = headerIsGif(header);
  const gifByHint = isGifHint({
    uri,
    mimeType: options?.mimeType,
    fileName: options?.fileName,
    blobType: meta.blobType,
  });
  const gif = gifByHeader || gifByHint;

  if (__DEV__) {
    console.log('[ImagePrepare]', {
      gif,
      gifByHeader,
      gifByHint,
      mimeType: options?.mimeType,
      fileName: options?.fileName,
      blobType: meta.blobType,
      size,
      uri: uri.slice(0, 80),
    });
  }

  if (gif) {
    if (size > CHAT_GIF_MAX_BYTES) {
      throw new Error('GIF 不能超过 5MB，请换一张较小的动图');
    }
    return buildPreparedImage({
      uri,
      width,
      height,
      mimeType: 'image/gif',
      fileName: options?.fileName,
      size,
      blob: meta.blob,
    });
  }

  if (size <= CHAT_IMAGE_MAX_BYTES) {
    return buildPreparedImage({
      uri,
      width,
      height,
      mimeType: resolveStaticImageMimeType({
        mimeType: options?.mimeType,
        blobType: meta.blobType,
        fileName: options?.fileName,
      }),
      fileName: options?.fileName,
      size,
      blob: meta.blob,
    });
  }

  return compressStaticImage(uri, width, height, meta.blob);
}
