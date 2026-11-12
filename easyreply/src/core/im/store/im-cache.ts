export interface IMCache {
  saveMessages(conversationId: string, messages: any[]): Promise<void>;
  loadMessages(conversationId: string): Promise<any[]>;
  saveConversations(convs: any[]): Promise<void>;
  loadConversations(): Promise<any[]>;
}

class InMemoryIMCache implements IMCache {
  private msgStore = new Map<string, any[]>();
  private convStore: any[] = [];
  async saveMessages(cid: string, msgs: any[]): Promise<void> { this.msgStore.set(cid, [...msgs]); }
  async loadMessages(cid: string): Promise<any[]> { return this.msgStore.get(cid) ?? []; }
  async saveConversations(convs: any[]): Promise<void> { this.convStore = [...convs]; }
  async loadConversations(): Promise<any[]> { return this.convStore; }
}

let _cache: IMCache = new InMemoryIMCache();
export function getIMCache(): IMCache { return _cache; }
export function setIMCache(cache: IMCache): void { _cache = cache; }
export function resetIMCache(): void { _cache = new InMemoryIMCache(); }
export default getIMCache;
