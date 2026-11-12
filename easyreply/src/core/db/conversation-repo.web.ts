// ============================================================
// 会话仓储 · Web 实现（Dexie / IndexedDB）
// 覆盖同目录 conversation-repo.ts（Metro 平台后缀解析），
// 因此 expo-sqlite 不会进 Web bundle，dexie 也不会进 Native bundle。
// ============================================================
import Dexie, { type Table } from 'dexie';
import type { ConversationDiff, ConversationRepo, ConversationRow } from './types';

const DATABASE_NAME = 'qinghui-cache';

type ConversationKey = [string, string];

class CacheDatabase extends Dexie {
  conversations!: Table<ConversationRow, ConversationKey>;

  constructor() {
    super(DATABASE_NAME);
    this.version(1).stores({
      conversations: '[scopeKey+taskID], scopeKey, [scopeKey+sortTime]',
    });
  }
}

let database: CacheDatabase | null = null;

/** 延迟建库：避免模块加载阶段就触碰 IndexedDB */
function getDatabase(): CacheDatabase {
  if (!database) database = new CacheDatabase();
  return database;
}

export const conversationRepo: ConversationRepo = {
  async loadScope(scopeKey) {
    // 按 scopeKey 单列索引取，再在 JS 侧排序：与 Native 的 WHERE scope_key = ? 语义一致。
    // 若改用 [scopeKey+sortTime] 复合索引，sortTime 一旦缺失该行就不会进索引而被静默漏读。
    const rows = await getDatabase().conversations.where('scopeKey').equals(scopeKey).toArray();
    return rows.sort((a, b) => b.sortTime - a.sortTime);
  },

  async applyDiff(scopeKey, diff: ConversationDiff) {
    if (!diff.upserts.length && !diff.deleteTaskIDs.length) return;
    const db = getDatabase();
    await db.transaction('rw', db.conversations, async () => {
      if (diff.deleteTaskIDs.length) {
        await db.conversations.bulkDelete(
          diff.deleteTaskIDs.map((taskID): ConversationKey => [scopeKey, taskID]),
        );
      }
      if (diff.upserts.length) {
        await db.conversations.bulkPut(diff.upserts);
      }
    });
  },

  async clearScope(scopeKey) {
    await getDatabase().conversations.where('scopeKey').equals(scopeKey).delete();
  },
};
