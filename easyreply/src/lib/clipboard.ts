import { Platform } from 'react-native';
import * as Clipboard from 'expo-clipboard';
import * as FileSystem from 'expo-file-system/legacy';

export async function copyText(text: string): Promise<boolean> {
  if (!text) return false;
  try {
    if (Platform.OS === 'web' && typeof navigator !== 'undefined' && navigator.clipboard) {
      await navigator.clipboard.writeText(text);
      return true;
    }
    await Clipboard.setStringAsync(text);
    return true;
  } catch {
    return false;
  }
}

/** 将本地 / 远程图片写入系统剪贴板（供粘贴到微信等） */
export async function copyImage(uri: string): Promise<boolean> {
  if (!uri) return false;
  try {
    if (Platform.OS === 'web') {
      // Web 暂不提供气泡复制菜单；保留实现便于后续启用
      const res = await fetch(uri);
      const blob = await res.blob();
      if (typeof navigator !== 'undefined' && navigator.clipboard && typeof ClipboardItem !== 'undefined') {
        await navigator.clipboard.write([new ClipboardItem({ [blob.type || 'image/png']: blob })]);
        return true;
      }
      return false;
    }

    let base64: string;
    if (uri.startsWith('data:')) {
      base64 = uri.replace(/^data:image\/[\w+.-]+;base64,/, '');
    } else if (/^(file|content):/i.test(uri)) {
      base64 = await FileSystem.readAsStringAsync(uri, { encoding: 'base64' });
    } else {
      const dest = `${FileSystem.cacheDirectory}qh-copy-${Date.now()}`;
      const downloaded = await FileSystem.downloadAsync(uri, dest);
      base64 = await FileSystem.readAsStringAsync(downloaded.uri, { encoding: 'base64' });
      void FileSystem.deleteAsync(downloaded.uri, { idempotent: true });
    }

    if (!base64) return false;
    await Clipboard.setImageAsync(base64);
    return true;
  } catch {
    return false;
  }
}
