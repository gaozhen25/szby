import type { LogChannel } from './types';
import {
  logFileName,
  parseLogFileName,
  type LogStore,
  type LogStoreFileInfo,
} from './log-store.types';

/**
 * Web 全量日志：IndexedDB 分块存储（append 只写新块，避免整文件读写）。
 * 导出仍走 LogStore.readFile → zip Blob，与 local-logger 现有流程一致。
 */

const DB_NAME = 'qinghui-local-logs';
const DB_VERSION = 1;
const META_STORE = 'meta';
const CHUNK_STORE = 'chunks';
const URI_PREFIX = 'idb:file:';

/** 旧 AsyncStorage 键（一次性迁移后清除） */
const LEGACY_INDEX_KEY = '@qinghui/local-logs/index';
const LEGACY_FILE_PREFIX = '@qinghui/local-logs/file:';

type FileMeta = {
  name: string;
  dateKey: string;
  channel: LogChannel;
  size: number;
  nextSeq: number;
};

type ChunkRow = {
  id?: number;
  fileName: string;
  seq: number;
  text: string;
};

let dbPromise: Promise<IDBDatabase> | null = null;
let migrated = false;

function fileUri(name: string): string {
  return `${URI_PREFIX}${name}`;
}

function nameFromUri(uri: string): string {
  return uri.startsWith(URI_PREFIX) ? uri.slice(URI_PREFIX.length) : uri;
}

function openDb(): Promise<IDBDatabase> {
  if (typeof indexedDB === 'undefined') {
    return Promise.reject(new Error('[LocalLog] IndexedDB unavailable'));
  }
  if (!dbPromise) {
    dbPromise = new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(META_STORE)) {
          db.createObjectStore(META_STORE, { keyPath: 'name' });
        }
        if (!db.objectStoreNames.contains(CHUNK_STORE)) {
          const store = db.createObjectStore(CHUNK_STORE, {
            keyPath: 'id',
            autoIncrement: true,
          });
          store.createIndex('byFile', 'fileName', { unique: false });
          store.createIndex('byFileSeq', ['fileName', 'seq'], { unique: true });
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => {
        dbPromise = null;
        reject(req.error ?? new Error('[LocalLog] IndexedDB open failed'));
      };
    });
  }
  return dbPromise;
}

function reqToPromise<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error ?? new Error('[LocalLog] IndexedDB request failed'));
  });
}

function txDone(tx: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error ?? new Error('[LocalLog] IndexedDB tx failed'));
    tx.onabort = () => reject(tx.error ?? new Error('[LocalLog] IndexedDB tx aborted'));
  });
}

async function getMeta(db: IDBDatabase, name: string): Promise<FileMeta | undefined> {
  const tx = db.transaction(META_STORE, 'readonly');
  const row = await reqToPromise(tx.objectStore(META_STORE).get(name));
  return row as FileMeta | undefined;
}

async function listMeta(db: IDBDatabase): Promise<FileMeta[]> {
  const tx = db.transaction(META_STORE, 'readonly');
  const rows = await reqToPromise(tx.objectStore(META_STORE).getAll());
  return (rows as FileMeta[]) || [];
}

async function readChunksText(db: IDBDatabase, fileName: string): Promise<string> {
  const tx = db.transaction(CHUNK_STORE, 'readonly');
  const index = tx.objectStore(CHUNK_STORE).index('byFileSeq');
  const range = IDBKeyRange.bound([fileName, 0], [fileName, Number.MAX_SAFE_INTEGER]);
  const rows = await reqToPromise(index.getAll(range));
  const chunks = (rows as ChunkRow[]) || [];
  if (chunks.length === 0) return '';
  if (chunks.length === 1) return chunks[0].text || '';
  return chunks.map((c) => c.text || '').join('');
}

async function listChunkKeys(db: IDBDatabase, fileName: string): Promise<IDBValidKey[]> {
  const tx = db.transaction(CHUNK_STORE, 'readonly');
  const index = tx.objectStore(CHUNK_STORE).index('byFile');
  return reqToPromise(index.getAllKeys(IDBKeyRange.only(fileName)));
}

async function deleteFileInternal(db: IDBDatabase, name: string): Promise<void> {
  const chunkKeys = await listChunkKeys(db, name);
  const tx = db.transaction([META_STORE, CHUNK_STORE], 'readwrite');
  tx.objectStore(META_STORE).delete(name);
  const chunkStore = tx.objectStore(CHUNK_STORE);
  for (const key of chunkKeys) {
    chunkStore.delete(key);
  }
  await txDone(tx);
}

async function appendChunk(
  db: IDBDatabase,
  channel: LogChannel,
  dateKey: string,
  chunk: string,
): Promise<void> {
  if (!chunk) return;
  const name = logFileName(dateKey, channel);
  // 先读 meta（只读事务），再写（读写事务），避免同一事务内 await 导致自动提交
  const existing = await getMeta(db, name);
  const meta: FileMeta = existing
    ? { ...existing }
    : {
        name,
        dateKey,
        channel,
        size: 0,
        nextSeq: 0,
      };
  const seq = meta.nextSeq;
  meta.nextSeq = seq + 1;
  meta.size += chunk.length;

  const tx = db.transaction([META_STORE, CHUNK_STORE], 'readwrite');
  tx.objectStore(CHUNK_STORE).add({ fileName: name, seq, text: chunk } satisfies ChunkRow);
  tx.objectStore(META_STORE).put(meta);
  await txDone(tx);
}

/**
 * 将旧 AsyncStorage 日志迁入 IndexedDB（失败不影响 IDB 正常写入）。
 */
async function migrateFromAsyncStorage(db: IDBDatabase): Promise<void> {
  if (migrated) return;
  migrated = true;
  try {
    const AsyncStorage = (
      await import('@react-native-async-storage/async-storage')
    ).default;
    const rawIndex = await AsyncStorage.getItem(LEGACY_INDEX_KEY);
    if (!rawIndex) return;

    let names: string[] = [];
    try {
      const parsed = JSON.parse(rawIndex) as unknown;
      names = Array.isArray(parsed)
        ? parsed.filter((x): x is string => typeof x === 'string')
        : [];
    } catch {
      names = [];
    }

    for (const name of names) {
      const parsed = parseLogFileName(name);
      if (!parsed) continue;
      const existing = await getMeta(db, name);
      if (existing && existing.size > 0) continue;
      const content =
        (await AsyncStorage.getItem(`${LEGACY_FILE_PREFIX}${name}`)) || '';
      if (!content) continue;
      await appendChunk(db, parsed.channel, parsed.dateKey, content);
    }

    const toRemove = [
      LEGACY_INDEX_KEY,
      ...names.map((n) => `${LEGACY_FILE_PREFIX}${n}`),
    ];
    const anyStorage = AsyncStorage as {
      removeMany?: (keys: string[]) => Promise<void>;
      multiRemove?: (keys: string[]) => Promise<void>;
      removeItem: (key: string) => Promise<void>;
    };
    if (typeof anyStorage.removeMany === 'function') {
      await anyStorage.removeMany(toRemove);
    } else if (typeof anyStorage.multiRemove === 'function') {
      await anyStorage.multiRemove(toRemove);
    } else {
      for (const key of toRemove) {
        await anyStorage.removeItem(key);
      }
    }
  } catch (e) {
    console.warn('[LocalLog] AsyncStorage → IndexedDB migrate skipped', e);
  }
}

export const logStore: LogStore = {
  async ensureReady() {
    const db = await openDb();
    await migrateFromAsyncStorage(db);
  },

  async append(channel: LogChannel, dateKey: string, chunk: string) {
    const db = await openDb();
    await appendChunk(db, channel, dateKey, chunk);
  },

  async listFiles(): Promise<LogStoreFileInfo[]> {
    const db = await openDb();
    const metas = await listMeta(db);
    return metas
      .map((m) => ({
        name: m.name,
        uri: fileUri(m.name),
        dateKey: m.dateKey,
        channel: m.channel,
        size: m.size,
      }))
      .sort((a, b) => a.name.localeCompare(b.name));
  },

  async readFile(uri: string) {
    const db = await openDb();
    return readChunksText(db, nameFromUri(uri));
  },

  async deleteFile(uri: string) {
    const db = await openDb();
    await deleteFileInternal(db, nameFromUri(uri));
  },

  async writeTempExportFile() {
    // Web 走 Blob 下载，不需要临时文件
    return '';
  },
};
