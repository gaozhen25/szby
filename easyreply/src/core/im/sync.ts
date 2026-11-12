import { fetchMessagesSince } from '@/api/im';
import type { IMConnection } from './connection';
import { createSyncFrame } from './protocol';
import { getIMStore } from './store/im-store';
import type { ChatMessage } from './types';
import { imCaptureError } from './utils';

export class SyncService {
  async syncConversation(conversationId: string): Promise<ChatMessage[]> {
    const store = getIMStore(); const lastSeq = store.getLastSeq(conversationId);
    try { const result = await fetchMessagesSince(conversationId, lastSeq); if (result.length > 0) store.upsertMessages(conversationId, result); return result; }
    catch (error) {
      imCaptureError('同步', 'REST sync 失败', error, { conversationId, lastSeq });
      return [];
    }
  }
  requestWsSync(connection: IMConnection, conversationId: string): void { if (connection.getState() !== 'connected') return; const lastSeq = getIMStore().getLastSeq(conversationId); connection.sendFrame(createSyncFrame({ conversationId, lastSeq })); }
  handleSyncResult(conversationId: string, messages: ChatMessage[]): void { if (messages.length === 0) return; getIMStore().upsertMessages(conversationId, messages); }
  async syncAll(conversationIds: string[]): Promise<void> { await Promise.all(conversationIds.map((id) => this.syncConversation(id))); }
}

let _syncService: SyncService | null = null;
export function getSyncService(): SyncService { if (!_syncService) _syncService = new SyncService(); return _syncService; }
export default getSyncService;
