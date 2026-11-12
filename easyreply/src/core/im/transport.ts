// ============================================================
// WebSocket 传输层
// 只记连接生命周期；帧正文由连接层/会话层落盘，避免同一帧打两遍原文
//
// 弱网要点：
// - 握手超时：new WebSocket 可能既不 open 也不 close（TCP 黑洞 / 弱网 / 强制门户），
//   必须自己兜超时，否则 connect() 永挂、上层 connectInFlight 不复位，将永远不再重连。
// - 陈旧 socket 守卫：重连时旧 socket 的 close/error 会晚到，若不按代次丢弃，
//   会误伤新连接（emit 假 close，甚至 reject 新的 connect promise）。
// ============================================================
import { imLog, imWarn } from './utils';

export type TransportEvent =
  | { type: 'open' }
  | { type: 'close'; code: number; reason: string }
  | { type: 'error'; error: Error }
  | { type: 'message'; data: string };

export type TransportListener = (event: TransportEvent) => void;

export interface IMTransport {
  connect(url: string, handshakeTimeoutMs?: number): Promise<void>;
  send(data: string): void;
  close(code?: number, reason?: string): void;
  getReadyState(): number;
  subscribe(listener: TransportListener): () => void;
}

const WS_OPEN = 1;
const WS_CLOSED = 3;
const DEFAULT_HANDSHAKE_TIMEOUT = 12_000;

/** WebSocket 的最小可用面，规避 RN / DOM 两套 typings 差异 */
type AnyWebSocket = {
  readyState: number;
  send(data: string): void;
  close(code?: number, reason?: string): void;
  onopen: ((ev: unknown) => void) | null;
  onmessage: ((ev: { data: unknown }) => void) | null;
  onerror: ((ev: unknown) => void) | null;
  onclose: ((ev: { code?: number; reason?: string }) => void) | null;
};

function detachHandlers(ws: AnyWebSocket): void {
  ws.onopen = null;
  ws.onmessage = null;
  ws.onerror = null;
  ws.onclose = null;
}

class WebSocketTransport implements IMTransport {
  private ws: AnyWebSocket | null = null;
  private listeners = new Set<TransportListener>();
  private connectPromise: Promise<void> | null = null;
  /** 每次新建 socket 自增；只有 activeSeq 对应的 socket 事件才被采纳 */
  private socketSeq = 0;
  private activeSeq = 0;

  subscribe(listener: TransportListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private emit(event: TransportEvent): void {
    this.listeners.forEach((listener) => listener(event));
  }

  /** 丢弃某个 socket：摘掉回调并关闭，之后它的任何事件都不再上抛 */
  private discardSocket(ws: AnyWebSocket): void {
    detachHandlers(ws);
    try {
      ws.close(1000, 'discarded');
    } catch {
      /* ignore */
    }
  }

  connect(url: string, handshakeTimeoutMs = DEFAULT_HANDSHAKE_TIMEOUT): Promise<void> {
    if (this.connectPromise) return this.connectPromise;
    this.connectPromise = new Promise<void>((resolve, reject) => {
      if (!url) {
        this.connectPromise = null;
        reject(new Error('[IM] WebSocket URL is not configured'));
        return;
      }
      this.close(1000, 'reconnect');

      const seq = ++this.socketSeq;
      this.activeSeq = seq;
      const isCurrent = () => this.activeSeq === seq;

      // 定时器由本次握手的闭包持有：外部 close() / 后续 connect() 都不会误清，
      // 保证这个 promise 一定会 settle。
      let handshakeTimer: ReturnType<typeof setTimeout> | null = null;
      let settled = false;
      const settle = (fn: () => void): void => {
        if (settled) return;
        settled = true;
        if (handshakeTimer) {
          clearTimeout(handshakeTimer);
          handshakeTimer = null;
        }
        // 已被新一代 socket 接管时不要清掉别人的 promise
        if (isCurrent()) this.connectPromise = null;
        fn();
      };

      imLog('传输层', '正在发起 WebSocket 握手', { url });
      const ws = new WebSocket(url) as unknown as AnyWebSocket;
      this.ws = ws;

      handshakeTimer = setTimeout(() => {
        handshakeTimer = null;
        if (settled) return;
        imWarn('传输层', `WebSocket 握手超时（>${handshakeTimeoutMs}ms），主动关闭并交由上层重连`, {
          url,
          readyState: ws.readyState,
        });
        if (isCurrent() && this.ws === ws) this.ws = null;
        this.discardSocket(ws);
        settle(() => reject(new Error(`[IM] WebSocket handshake timed out (>${handshakeTimeoutMs}ms)`)));
      }, handshakeTimeoutMs);

      ws.onopen = () => {
        if (!isCurrent()) {
          this.discardSocket(ws);
          return;
        }
        imLog('传输层', 'WebSocket 握手成功，连接已打开', { url });
        settle(() => resolve());
        this.emit({ type: 'open' });
      };

      ws.onmessage = (event) => {
        if (!isCurrent()) return;
        const data = typeof event.data === 'string' ? event.data : String(event.data);
        // 不落原文：连接层解帧后按 type 记，会话层记业务语义
        this.emit({ type: 'message', data });
      };

      ws.onerror = () => {
        const error = new Error('[IM] WebSocket error');
        if (!isCurrent()) {
          settle(() => reject(error));
          return;
        }
        imWarn('传输层', 'WebSocket 发生错误', { url });
        this.emit({ type: 'error', error });
        settle(() => reject(error));
      };

      ws.onclose = (event) => {
        const code = typeof event.code === 'number' ? event.code : 1006;
        const reason = event.reason || 'closed';
        detachHandlers(ws);
        // 重连过程中旧 socket 的迟到 close 不能影响新连接，但仍要让旧 promise 结算
        if (!isCurrent()) {
          imLog('传输层', '忽略陈旧 WebSocket 的关闭事件', { code, reason });
          settle(() => reject(new Error(`[IM] Stale WebSocket closed: ${code}`)));
          return;
        }
        imWarn('传输层', 'WebSocket 已关闭', { code, reason });
        if (this.ws === ws) this.ws = null;
        this.emit({ type: 'close', code, reason });
        settle(() => reject(new Error(`[IM] WebSocket closed: ${code}`)));
      };
    });
    return this.connectPromise;
  }

  send(data: string): void {
    if (!this.ws || this.ws.readyState !== WS_OPEN) throw new Error('[IM] WebSocket is not open');
    // 不落原文：上行由连接层/会话层按帧类型记录
    this.ws.send(data);
  }

  close(code: number = 1000, reason: string = 'client close'): void {
    if (this.ws) {
      const s = this.ws;
      this.ws = null;
      try {
        s.close(code, reason);
      } catch {
        /* ignore */
      }
    }
    this.connectPromise = null;
  }

  getReadyState(): number {
    return this.ws?.readyState ?? WS_CLOSED;
  }
}

export function createTransport(): IMTransport {
  return new WebSocketTransport();
}
export default createTransport;
