// ============================================================
// 会话仓储 · Native 实现（expo-sqlite）
// Web 端由同目录 conversation-repo.web.ts 覆盖（Metro 平台后缀解析）
// ============================================================
import * as SQLite from 'expo-sqlite';
import type { ConversationDiff, ConversationRepo, ConversationRow } from './types';

const DATABASE_NAME = 'qinghui-cache.db';
/** SQLite 变量上限为 999，删除语句留出 scope_key 的位置 */
const DELETE_CHUNK_SIZE = 500;

type SqliteConversationRow = {
  scope_key: string;
  task_id: string;
  im_conversation_id: string;
  sort_time: number;
  inactive: number;
  updated_at: number;
  data: string;
};

const UPSERT_SQL = `
  INSERT INTO conversations
    (scope_key, task_id, im_conversation_id, sort_time, inactive, updated_at, data)
  VALUES
    ($scopeKey, $taskID, $imConversationID, $sortTime, $inactive, $updatedAt, $data)
  ON CONFLICT(scope_key, task_id) DO UPDATE SET
    im_conversation_id = excluded.im_conversation_id,
    sort_time = excluded.sort_time,
    inactive = excluded.inactive,
    updated_at = excluded.updated_at,
    data = excluded.data
`;

let dbPromise: Promise<SQLite.SQLiteDatabase> | null = null;

function openDatabase(): Promise<SQLite.SQLiteDatabase> {
  if (dbPromise) return dbPromise;
  dbPromise = (async () => {
    const db = await SQLite.openDatabaseAsync(DATABASE_NAME);
    await db.execAsync(`
      PRAGMA journal_mode = WAL;
      CREATE TABLE IF NOT EXISTS conversations (
        scope_key TEXT NOT NULL,
        task_id TEXT NOT NULL,
        im_conversation_id TEXT NOT NULL DEFAULT '',
        sort_time INTEGER NOT NULL DEFAULT 0,
        inactive INTEGER NOT NULL DEFAULT 0,
        updated_at INTEGER NOT NULL DEFAULT 0,
        data TEXT NOT NULL,
        PRIMARY KEY (scope_key, task_id)
      );
      CREATE INDEX IF NOT EXISTS idx_conversations_scope_sort
        ON conversations (scope_key, sort_time DESC);
    `);
    return db;
  })();
  // 打开失败时清掉 promise，下次调用可重试
  dbPromise.catch(() => {
    dbPromise = null;
  });
  return dbPromise;
}

function toRow(row: SqliteConversationRow): ConversationRow {
  return {
    scopeKey: row.scope_key,
    taskID: row.task_id,
    imConversationID: row.im_conversation_id,
    sortTime: row.sort_time,
    inactive: row.inactive,
    updatedAt: row.updated_at,
    data: row.data,
  };
}

function chunk<T>(items: T[], size: number): T[][] {
  const chunks: T[][] = [];
  for (let i = 0; i < items.length; i += size) chunks.push(items.slice(i, i + size));
  return chunks;
}

export const conversationRepo: ConversationRepo = {
  async loadScope(scopeKey) {
    const db = await openDatabase();
    const rows = await db.getAllAsync<SqliteConversationRow>(
      'SELECT * FROM conversations WHERE scope_key = ? ORDER BY sort_time DESC',
      scopeKey,
    );
    return rows.map(toRow);
  },

  async applyDiff(scopeKey, diff: ConversationDiff) {
    if (!diff.upserts.length && !diff.deleteTaskIDs.length) return;
    const db = await openDatabase();
    await db.withExclusiveTransactionAsync(async (txn) => {
      for (const ids of chunk(diff.deleteTaskIDs, DELETE_CHUNK_SIZE)) {
        const placeholders = ids.map(() => '?').join(',');
        await txn.runAsync(
          `DELETE FROM conversations WHERE scope_key = ? AND task_id IN (${placeholders})`,
          scopeKey,
          ...ids,
        );
      }
      if (!diff.upserts.length) return;
      const statement = await txn.prepareAsync(UPSERT_SQL);
      try {
        for (const row of diff.upserts) {
          await statement.executeAsync({
            $scopeKey: row.scopeKey,
            $taskID: row.taskID,
            $imConversationID: row.imConversationID,
            $sortTime: row.sortTime,
            $inactive: row.inactive,
            $updatedAt: row.updatedAt,
            $data: row.data,
          });
        }
      } finally {
        await statement.finalizeAsync();
      }
    });
  },

  async clearScope(scopeKey) {
    const db = await openDatabase();
    await db.runAsync('DELETE FROM conversations WHERE scope_key = ?', scopeKey);
  },
};
