import { Platform } from 'react-native';
import { upload } from '@/lib/http';
import { prepareImageForUpload } from '@/lib/image-compress';

/** 后台资源上传上限（与 Chat API / 网关一致） */
export const CHAT_UPLOAD_MAX_BYTES = 50 * 1024 * 1024;
export const CHAT_UPLOAD_OVERSIZE_MESSAGE = '文件不能超过 50MB，请压缩后重试';

export function isChatUploadOverSize(size?: number | null): boolean {
  return typeof size === 'number' && Number.isFinite(size) && size > CHAT_UPLOAD_MAX_BYTES;
}

export interface AssetUploadResult {
  ok: boolean;
  objectKey: string;
  url: string;
  md5: string;
  size: number;
  contentType: string;
}

function formatUploadSize(bytes: number | null | undefined): string {
  if (bytes == null || !Number.isFinite(bytes) || bytes < 0) return '未知';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function formatUploadSpeed(bytes: number, durationMs: number): string {
  if (durationMs <= 0 || bytes <= 0) return '—';
  const bytesPerSec = (bytes * 1000) / durationMs;
  if (bytesPerSec < 1024) return `${bytesPerSec.toFixed(0)} B/s`;
  if (bytesPerSec < 1024 * 1024) return `${(bytesPerSec / 1024).toFixed(1)} KB/s`;
  return `${(bytesPerSec / (1024 * 1024)).toFixed(2)} MB/s`;
}

async function resolveNativeUploadFileSize(uri: string): Promise<number | null> {
  try {
    const FileSystem = await import('expo-file-system/legacy');
    const info = await FileSystem.getInfoAsync(uri);
    if (info.exists && typeof info.size === 'number' && info.size >= 0) return info.size;
  } catch {
    // ignore
  }
  return null;
}

function resolveUploadMimeType(params: {
  subdir: 'image' | 'video' | 'voice' | 'file';
  fileName: string;
  mimeType?: string;
  blobType?: string;
}): string {
  const explicit = (params.mimeType || '').trim().toLowerCase();
  const fromBlob = (params.blobType || '').trim().toLowerCase();
  const fromName = (params.fileName || '').trim().toLowerCase();

  // 显式 mime 优先（GIF 等不能被空 blob.type 或错误默认 jpeg 覆盖）
  if (explicit) return explicit;
  if (fromBlob) return fromBlob;
  if (fromName.endsWith('.gif')) return 'image/gif';
  if (fromName.endsWith('.png')) return 'image/png';
  if (fromName.endsWith('.webp')) return 'image/webp';
  if (fromName.endsWith('.jpg') || fromName.endsWith('.jpeg')) return 'image/jpeg';

  if (params.subdir === 'image') return 'image/jpeg';
  if (params.subdir === 'voice') return 'audio/mpeg';
  if (params.subdir === 'video') return 'video/mp4';
  if (params.subdir === 'file') return 'application/octet-stream';
  return 'application/octet-stream';
}

async function uploadAssetFile(params: {
  uri: string;
  fileName: string;
  mimeType: string;
  subdir: 'image' | 'video' | 'voice' | 'file';
  blob?: Blob;
}): Promise<AssetUploadResult> {
  const form = new FormData();
  const endpoint = `/api/app/assets/upload?subdir=${params.subdir}`;
  let fileSizeBytes: number | null = null;
  const startedAt = Date.now();

  try {
    if (Platform.OS === 'web') {
      let blob = params.blob;
      if (!blob) {
        const res = await fetch(params.uri);
        blob = await res.blob();
      }
      const resolvedMime = resolveUploadMimeType({
        subdir: params.subdir,
        fileName: params.fileName,
        mimeType: params.mimeType,
        blobType: blob.type,
      });
      const file = new File([blob], params.fileName, {
        type: resolvedMime,
      });
      fileSizeBytes = file.size;
      if (isChatUploadOverSize(file.size)) {
        throw new Error(CHAT_UPLOAD_OVERSIZE_MESSAGE);
      }
      form.append('file', file);
    } else {
      const resolvedMime = resolveUploadMimeType({
        subdir: params.subdir,
        fileName: params.fileName,
        mimeType: params.mimeType,
      });
      fileSizeBytes = params.blob?.size ?? (await resolveNativeUploadFileSize(params.uri));
      form.append('file', {
        uri: params.uri,
        name: params.fileName,
        type: resolvedMime,
      } as unknown as Blob);
    }

    console.log('[AssetUpload] 开始上传', {
      platform: Platform.OS,
      endpoint,
      subdir: params.subdir,
      fileName: params.fileName,
      fileSizeBytes,
      fileSize: formatUploadSize(fileSizeBytes),
    });

    const result = await upload<AssetUploadResult>(endpoint, form);

    const durationMs = Date.now() - startedAt;
    const sizeForRate = fileSizeBytes ?? result.size ?? null;
    console.log('[AssetUpload] 上传成功', {
      platform: Platform.OS,
      endpoint,
      subdir: params.subdir,
      fileName: params.fileName,
      fileSizeBytes: sizeForRate,
      fileSize: formatUploadSize(sizeForRate),
      durationMs,
      durationSec: Number((durationMs / 1000).toFixed(2)),
      averageSpeed: sizeForRate != null ? formatUploadSpeed(sizeForRate, durationMs) : '—',
      response: result,
    });
    return result;
  } catch (e) {
    const durationMs = Date.now() - startedAt;
    console.warn('[AssetUpload] 上传失败', {
      platform: Platform.OS,
      endpoint,
      subdir: params.subdir,
      fileName: params.fileName,
      fileSizeBytes,
      fileSize: formatUploadSize(fileSizeBytes),
      durationMs,
      durationSec: Number((durationMs / 1000).toFixed(2)),
      error: e instanceof Error ? e.message : String(e),
    });
    throw e;
  }
}

export async function uploadImageAsset(params: {
  uri: string;
  fileName?: string;
  mimeType?: string;
  blob?: Blob;
  width?: number;
  height?: number;
}): Promise<AssetUploadResult> {
  const prepared = await prepareImageForUpload(params.uri, params.width, params.height, {
    mimeType: params.mimeType,
    fileName: params.fileName,
    blob: params.blob,
  });
  return uploadAssetFile({
    uri: prepared.uri,
    fileName: prepared.fileName,
    mimeType: prepared.mimeType,
    subdir: 'image',
    blob: prepared.blob,
  });
}

/** 上传聊天语音（subdir=voice，多为 .mp3） */
export async function uploadVoiceAsset(params: {
  uri: string;
  fileName?: string;
  mimeType?: string;
  blob?: Blob;
}): Promise<AssetUploadResult> {
  return uploadAssetFile({
    uri: params.uri,
    fileName: params.fileName || `voice-${Date.now()}.mp3`,
    mimeType: params.mimeType || 'audio/mpeg',
    subdir: 'voice',
    blob: params.blob,
  });
}

/** 上传聊天视频（subdir=video，白名单 video/mp4 / video/quicktime） */
export async function uploadVideoAsset(params: {
  uri: string;
  fileName?: string;
  mimeType?: string;
  blob?: Blob;
}): Promise<AssetUploadResult> {
  return uploadAssetFile({
    uri: params.uri,
    fileName: params.fileName || `video-${Date.now()}.mp4`,
    mimeType: params.mimeType || 'video/mp4',
    subdir: 'video',
    blob: params.blob,
  });
}

/** 上传聊天文件（subdir=file，白名单 application/* / text/*） */
export async function uploadFileAsset(params: {
  uri: string;
  fileName?: string;
  mimeType?: string;
  blob?: Blob;
}): Promise<AssetUploadResult> {
  return uploadAssetFile({
    uri: params.uri,
    fileName: params.fileName || `file-${Date.now()}`,
    mimeType: params.mimeType || 'application/octet-stream',
    subdir: 'file',
    blob: params.blob,
  });
}
