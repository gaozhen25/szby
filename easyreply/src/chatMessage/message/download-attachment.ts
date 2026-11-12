import * as FileSystem from 'expo-file-system/legacy';
import { Platform } from 'react-native';

function sanitizeFileName(name: string): string {
  const trimmed = name.trim() || `attachment-${Date.now()}`;
  return trimmed.replace(/[\\/:*?"<>|]+/g, '_');
}

export async function downloadAttachmentToCache(params: {
  url: string;
  fileName: string;
}): Promise<{ localUri: string; fileName: string }> {
  const url = params.url.trim();
  if (!url) throw new Error('文件地址无效');
  const fileName = sanitizeFileName(params.fileName);
  if (Platform.OS === 'web') {
    const response = await fetch(url);
    if (!response.ok) throw new Error('文件下载失败');
    const blob = await response.blob();
    return { localUri: URL.createObjectURL(blob), fileName };
  }
  const target = `${FileSystem.cacheDirectory}qh-attachment-${Date.now()}-${fileName}`;
  const result = await FileSystem.downloadAsync(url, target);
  return { localUri: result.uri, fileName };
}
