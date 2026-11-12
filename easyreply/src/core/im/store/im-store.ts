import type { ChatMessage, Conversation } from '../types';
class IMStore {
  private messages = new Map<string, ChatMessage[]>();
  private conversations = new Map<string, Conversation>();
  getMessages(conversationId: string): ChatMessage[] { return this.messages.get(conversationId) ?? []; }
  getLastSeq(conversationId: string): number { const msgs = this.getMessages(conversationId); return msgs.length > 0 ? Math.max(...msgs.map((m) => m.seq ?? 0)) : 0; }
  upsertMessage(msg: ChatMessage): void { const msgs = this.getMessages(msg.conversationId); const idx = msgs.findIndex((m) => m.clientMsgId === msg.clientMsgId); if (idx >= 0) msgs[idx] = msg; else msgs.push(msg); this.messages.set(msg.conversationId, msgs); }
  upsertMessages(conversationId: string, msgs: ChatMessage[]): void { const existing = this.getMessages(conversationId); const ids = new Set(existing.map((m) => m.clientMsgId)); const merged = [...existing, ...msgs.filter((m) => !ids.has(m.clientMsgId))]; this.messages.set(conversationId, merged); }
  updateMessage(clientMsgId: string, patch: Partial<ChatMessage>): void { for (const [cid, msgs] of this.messages) { const idx = msgs.findIndex((m) => m.clientMsgId === clientMsgId); if (idx >= 0) { msgs[idx] = { ...msgs[idx], ...patch }; return; } } }
  getConversation(id: string): Conversation | undefined { return this.conversations.get(id); }
  getConversations(): Conversation[] { return Array.from(this.conversations.values()).sort((a, b) => b.updatedAt - a.updatedAt); }
  setConversations(convs: Conversation[]): void { this.conversations.clear(); convs.forEach((c) => this.conversations.set(c.id, c)); }
  upsertConversation(conv: Conversation): void { this.conversations.set(conv.id, conv); }
  updateConversation(id: string, patch: Partial<Conversation>): void { const conv = this.conversations.get(id); if (conv) this.conversations.set(id, { ...conv, ...patch }); }
}

let _store: IMStore | null = null;
export function getIMStore(): IMStore { if (!_store) _store = new IMStore(); return _store; }
export function resetIMStore(): void { _store = null; }
export default getIMStore;
