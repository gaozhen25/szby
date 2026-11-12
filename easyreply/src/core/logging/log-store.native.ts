import * as FileSystem from 'expo-file-system/legacy';
import type { LogChannel } from './types';
import {
  logFileName,
  parseLogFileName,
  type LogStore,
  type LogStoreFileInfo,
} from './log-store.types';

function logsDir(): string {
  const base = FileSystem.documentDirectory;
  if (!base) throw new Error('[LocalLog] documentDirectory unavailable');
  return `${base}logs/`;
}

async function ensureDir(): Promise<string> {
  const dir = logsDir();
  const info = await FileSystem.getInfoAsync(dir);
  if (!info.exists) {
    await FileSystem.makeDirectoryAsync(dir, { intermediates: true });
  }
  return dir;
}

export const logStore: LogStore = {
  async ensureReady() {
    await ensureDir();
  },

  async append(channel: LogChannel, dateKey: string, chunk: string) {
    const dir = await ensureDir();
    const name = logFileName(dateKey, channel);
    const uri = `${dir}${name}`;
    const info = await FileSystem.getInfoAsync(uri);
    if (info.exists) {
      const prev = await FileSystem.readAsStringAsync(uri);
      await FileSystem.writeAsStringAsync(uri, prev + chunk);
    } else {
      await FileSystem.writeAsStringAsync(uri, chunk);
    }
  },

  async listFiles(): Promise<LogStoreFileInfo[]> {
    const dir = await ensureDir();
    const names = await FileSystem.readDirectoryAsync(dir);
    const out: LogStoreFileInfo[] = [];
    for (const name of names) {
      const parsed = parseLogFileName(name);
      if (!parsed) continue;
      const uri = `${dir}${name}`;
      const info = await FileSystem.getInfoAsync(uri);
      out.push({
        name,
        uri,
        dateKey: parsed.dateKey,
        channel: parsed.channel,
        size: info.exists && 'size' in info && typeof info.size === 'number' ? info.size : 0,
      });
    }
    return out.sort((a, b) => a.name.localeCompare(b.name));
  },

  async readFile(uri: string) {
    return FileSystem.readAsStringAsync(uri);
  },

  async deleteFile(uri: string) {
    await FileSystem.deleteAsync(uri, { idempotent: true });
  },

  async writeTempExportFile(fileName: string, content: string | Uint8Array) {
    const base = FileSystem.cacheDirectory || FileSystem.documentDirectory;
    if (!base) throw new Error('[LocalLog] cacheDirectory unavailable');
    const uri = `${base}${fileName}`;
    if (typeof content === 'string') {
      await FileSystem.writeAsStringAsync(uri, content);
    } else {
      const { uint8ToBase64 } = await import('./zip-store');
      await FileSystem.writeAsStringAsync(uri, uint8ToBase64(content), {
        encoding: FileSystem.EncodingType.Base64,
      });
    }
    return uri;
  },
};
