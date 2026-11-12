import { Linking, Platform } from 'react-native';

/**
 * 打开聊天文件消息（contentType=105）
 * Web / iOS / Android：统一用浏览器打开远程 URL
 */
export async function openChatFileAttachment(params: {
  url: string;
  fileName?: string;
}): Promise<void> {
  const url = params.url.trim();
  if (!url) throw new Error('文件地址无效');

  if (Platform.OS === 'web') {
    if (typeof window === 'undefined') throw new Error('当前环境无法打开文件');
    window.open(url, '_blank', 'noopener,noreferrer');
    return;
  }

  const canOpen = await Linking.canOpenURL(url);
  if (!canOpen) throw new Error('无法使用浏览器打开该文件');
  await Linking.openURL(url);
}
