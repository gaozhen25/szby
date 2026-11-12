import type { IMConnection } from './connection';
import type { AckPayload, IMFrame, OutboxItem } from './types';
import { calcBackoffDelay } from './utils';

type OutboxListener = () => void;
type OutboxFailedHandler = (clientMsgId: string, conversationId: string) => void;

export class OutboxQueue {
  private items = new Map<string, OutboxItem>();
  private ackTimers = new Map<string, ReturnType<typeof setTimeout>>();
  private listeners = new Set<OutboxListener>();
  private failedHandler: OutboxFailedHandler | null = null;

  onFailed(handler: OutboxFailedHandler): void { this.failedHandler = handler; }
  subscribe(listener: OutboxListener): () => void { this.listeners.add(listener); return () => this.listeners.delete(listener); }
  private notify(): void { this.listeners.forEach((fn) => fn()); }

  enqueue(connection: IMConnection, item: Omit<OutboxItem, 'retryCount' | 'nextRetryAt' | 'createdAt'>): void {
    const outboxItem: OutboxItem = { ...item, retryCount: 0, nextRetryAt: Date.now(), createdAt: Date.now() };
    this.items.set(item.clientMsgId, outboxItem); this.notify(); this.trySend(connection, outboxItem);
  }

  handleAck(payload: AckPayload): void { this.clearAckTimer(payload.clientMsgId); this.items.delete(payload.clientMsgId); this.notify(); }

  markFailed(clientMsgId: string): void {
    const item = this.items.get(clientMsgId); this.clearAckTimer(clientMsgId); this.items.delete(clientMsgId); this.notify();
    if (item) this.failedHandler?.(clientMsgId, item.conversationId);
  }

  private trySend(connection: IMConnection, item: OutboxItem): void {
    if (connection.getState() !== 'connected') return;
    try { connection.sendFrame(item.frame); this.setAckTimeout(item.clientMsgId, connection); } catch { this.scheduleRetry(connection, item); }
  }

  private setAckTimeout(clientMsgId: string, connection: IMConnection): void {
    this.clearAckTimer(clientMsgId);
    this.ackTimers.set(clientMsgId, setTimeout(() => { const item = this.items.get(clientMsgId); if (item) this.scheduleRetry(connection, item); }, connection.getOptions().ackTimeout));
  }

  private clearAckTimer(clientMsgId: string): void { const timer = this.ackTimers.get(clientMsgId); if (timer) { clearTimeout(timer); this.ackTimers.delete(clientMsgId); } }

  private scheduleRetry(connection: IMConnection, item: OutboxItem): void {
    const next = item.retryCount + 1;
    const delay = calcBackoffDelay(next, 1000, 30000);
    item.retryCount = next; item.nextRetryAt = Date.now() + delay;
    setTimeout(() => this.trySend(connection, item), delay);
  }
}

let _outboxQueue: OutboxQueue | null = null;
export function getOutboxQueue(): OutboxQueue { if (!_outboxQueue) _outboxQueue = new OutboxQueue(); return _outboxQueue; }
export function resetOutboxQueue(): void { _outboxQueue = null; }
export default getOutboxQueue;
