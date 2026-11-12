// ============================================================
// 心跳 ping/pong：不落盘，只累计计数；控制台仍逐条输出便于联调
// 断线 / 周期性输出一行摘要到本地日志
// ============================================================
import { imLog } from './utils';

type HeartbeatCounters = {
  pingSent: number;
  pongSent: number;
  pingRecv: number;
  pongRecv: number;
  pongMismatch: number;
};

const counters: HeartbeatCounters = {
  pingSent: 0,
  pongSent: 0,
  pingRecv: 0,
  pongRecv: 0,
  pongMismatch: 0,
};

let lastFlushAt = Date.now();
/** 正常心跳安静时，最多这么久吐一行统计到本地日志 */
const FLUSH_INTERVAL_MS = 5 * 60 * 1000;

export type HeartbeatEvent =
  | 'ping_sent'
  | 'pong_sent'
  | 'ping_recv'
  | 'pong_recv'
  | 'pong_mismatch';

const HEARTBEAT_CONSOLE_LABEL: Record<HeartbeatEvent, string> = {
  ping_sent: '发送 ping 保活',
  pong_sent: '回应 pong',
  ping_recv: '收到服务端 ping',
  pong_recv: '收到心跳 pong',
  pong_mismatch: '收到心跳 pong（payload 未匹配）',
};

export function recordHeartbeat(event: HeartbeatEvent): void {
  switch (event) {
    case 'ping_sent':
      counters.pingSent += 1;
      break;
    case 'pong_sent':
      counters.pongSent += 1;
      break;
    case 'ping_recv':
      counters.pingRecv += 1;
      break;
    case 'pong_recv':
      counters.pongRecv += 1;
      break;
    case 'pong_mismatch':
      counters.pongMismatch += 1;
      break;
  }
  // 控制台保留可见性；不走 imLog/logWs，避免心跳刷盘
  console.log(`[IM][心跳] ${HEARTBEAT_CONSOLE_LABEL[event]}`);
  maybeFlushHeartbeatStats(false);
}

function snapshotAndReset(): HeartbeatCounters {
  const snap = { ...counters };
  counters.pingSent = 0;
  counters.pongSent = 0;
  counters.pingRecv = 0;
  counters.pongRecv = 0;
  counters.pongMismatch = 0;
  lastFlushAt = Date.now();
  return snap;
}

function total(c: HeartbeatCounters): number {
  return c.pingSent + c.pongSent + c.pingRecv + c.pongRecv + c.pongMismatch;
}

/** force=true：断线/停心跳时立刻打一行（有计数才写本地日志） */
export function flushHeartbeatStats(reason: string, force = true): void {
  if (!force && Date.now() - lastFlushAt < FLUSH_INTERVAL_MS) return;
  if (total(counters) === 0) {
    if (force) lastFlushAt = Date.now();
    return;
  }
  const snap = snapshotAndReset();
  imLog('心跳', `统计（${reason}）`, snap);
}

function maybeFlushHeartbeatStats(force: boolean): void {
  if (!force && Date.now() - lastFlushAt < FLUSH_INTERVAL_MS) return;
  flushHeartbeatStats('周期', force);
}
