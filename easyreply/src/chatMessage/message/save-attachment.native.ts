import * as MediaLibrary from 'expo-media-library';
import * as Sharing from 'expo-sharing';
import { downloadAttachmentToCache } from './download-attachment';
import { inferAttachmentPreviewKind } from './attachment-mime';

export async function saveAttachmentNative(params: {
  url: string;
  fileName: string;
}): Promise<void> {
  const { localUri } = await downloadAttachmentToCache(params);
  const kind = inferAttachmentPreviewKind(params.fileName, params.url);

  if (kind === 'image' || kind === 'video') {
    const permission = await MediaLibrary.requestPermissionsAsync(true);
    if (!permission.granted) {
      throw new Error('需要相册权限以保存图片或视频');
    }
    await MediaLibrary.saveToLibraryAsync(localUri);
    return;
  }

  const available = await Sharing.isAvailableAsync();
  if (!available) {
    throw new Error('当前设备不支持保存到文件或分享');
  }
  await Sharing.shareAsync(localUri, {
    dialogTitle: params.fileName || '保存文件',
    mimeType: undefined,
  });
}
