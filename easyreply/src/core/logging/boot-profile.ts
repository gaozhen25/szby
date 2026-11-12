// ============================================================
// 启动期主线程阻塞探针（仅 Web）
//
// 背景：有用户反馈「刷新完立刻在聊天框打字，输入法候选字掉帧 1~2 秒后恢复」，
// 只在个别人身上出现。数据层（缓存解析、merge、排序、订阅签名、日志脱敏）
// 在 300 会话规模下合计约 1~2ms，差了三个数量级，不是 1~2 秒卡顿的来源。
//
// 剩下的可能（脚本编译执行、延迟初始化、该机器 CPU、扩展干扰）都依赖具体环境，
// 本机复现不了，所以这里把「谁占住了主线程」直接测出来：
//   1. Long Tasks API 记录每个 >50ms 的任务
//   2. 启动关键阶段打 mark，用于把长任务归因到具体阶段
//   3. 用户第一次在输入框打字时，汇总这次输入前后的长任务
//
// 结果走 logApp → 落本地诊断日志（我的页「导出诊断日志」可直接导出 zip）+ Sentry，
// 因此让当事人复现一次后导出日志即可定位，不需要他装 devtools 录 profile。
// ============================================================
import { Platform } from 'react-native';

/** 只观测启动后这段时间，避免长期占用观察者 */
const OBSERVE_WINDOW_MS = 15_000;
/** 汇总时最多列出的长任务数 */
const MAX_REPORTED_TASKS = 12;
/** 首次输入后再等这么久汇总，覆盖住用户描述的 1~2 秒 */
const REPORT_DELAY_AFTER_INPUT_MS = 2_500;

type LongTask = {
  /** 相对导航起点的毫秒数 */
  startTime: number;
  duration: number;
  /** 浏览器给出的归因容器（iframe / 自身），信息有限但能区分扩展 */
  attribution: string;
};

type PhaseMark = { name: string; at: number };

const longTasks: LongTask[] = [];
const phases: PhaseMark[] = [];

let observer: PerformanceObserver | null = null;
let started = false;
let reported = false;
let firstInputAt: number | null = null;

function now(): number {
  return typeof performance !== 'undefined' ? performance.now() : Date.now();
}

function isWebRuntime(): boolean {
  return (
    Platform.OS === 'web' &&
    typeof window !== 'undefined' &&
    typeof performance !== 'undefined'
  );
}

/**
 * 标记一个启动阶段的时刻。
 * 在长任务列表里对照 mark，就能判断某段卡顿属于哪一步（IM 初始化 / Sentry / 会话 hydrate…）。
 */
export function markBootPhase(name: string): void {
  if (!isWebRuntime()) return;
  phases.push({ name, at: now() });
  try {
    performance.mark?.(`qh:${name}`);
  } catch {
    // mark 失败不影响业务
  }
}

/** 包一段同步启动逻辑，顺带记录自身耗时 */
export function measureBootPhase<T>(name: string, fn: () => T): T {
  if (!isWebRuntime()) return fn();
  const t0 = now();
  try {
    return fn();
  } finally {
    const cost = now() - t0;
    phases.push({ name: `${name} 耗时${cost.toFixed(0)}ms`, at: t0 });
  }
}

function attributionOf(entry: PerformanceEntry): string {
  const list = (entry as { attribution?: { name?: string; containerType?: string }[] })
    .attribution;
  if (!Array.isArray(list) || list.length === 0) return 'unknown';
  const first = list[0];
  return [first?.containerType, first?.name].filter(Boolean).join(':') || 'unknown';
}

/** 找出与某个长任务时间上重叠的启动阶段，用于归因 */
function phaseAround(startTime: number): string {
  let hit = '';
  for (const p of phases) {
    if (p.at <= startTime) hit = p.name;
    else break;
  }
  return hit || '(启动早期)';
}

function buildReport(): Record<string, unknown> {
  const sorted = [...longTasks].sort((a, b) => b.duration - a.duration);
  const total = longTasks.reduce((sum, t) => sum + t.duration, 0);

  // 首次输入之后 REPORT_DELAY_AFTER_INPUT_MS 内的长任务，就是直接卡住输入法的那批
  const inputAt = firstInputAt;
  const blockingInput =
    inputAt == null
      ? []
      : longTasks.filter(
          (t) =>
            t.startTime + t.duration >= inputAt &&
            t.startTime <= inputAt + REPORT_DELAY_AFTER_INPUT_MS,
        );
  const blockingMs = blockingInput.reduce((sum, t) => sum + t.duration, 0);

  return {
    硬件并发数: typeof navigator !== 'undefined' ? navigator.hardwareConcurrency : undefined,
    设备内存GB:
      typeof navigator !== 'undefined'
        ? (navigator as { deviceMemory?: number }).deviceMemory
        : undefined,
    长任务总数: longTasks.length,
    长任务总耗时ms: Math.round(total),
    首次输入时刻ms: firstInputAt == null ? null : Math.round(firstInputAt),
    卡住输入的长任务数: blockingInput.length,
    卡住输入的总时长ms: Math.round(blockingMs),
    最长任务: sorted.slice(0, MAX_REPORTED_TASKS).map((t) => ({
      开始ms: Math.round(t.startTime),
      时长ms: Math.round(t.duration),
      归因: t.attribution,
      所处阶段: phaseAround(t.startTime),
    })),
    启动阶段: phases.map((p) => `${Math.round(p.at)}ms ${p.name}`),
  };
}

function report(reason: string): void {
  if (reported) return;
  reported = true;
  observer?.disconnect();
  observer = null;

  // 动态引入，避免 boot-profile 与 local-logger 形成模块环
  void import('./local-logger').then(({ logApp }) => {
    logApp(`[BootProfile] 启动期主线程阻塞汇总（${reason}）`, buildReport());
  });
}

/**
 * 启动探针。幂等，非 Web 直接空转。
 * 观测窗口结束或用户首次输入后自动汇总一次。
 */
export function initBootProfile(): void {
  if (started || !isWebRuntime()) return;
  if (typeof PerformanceObserver !== 'function') return;
  started = true;

  try {
    observer = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        longTasks.push({
          startTime: entry.startTime,
          duration: entry.duration,
          attribution: attributionOf(entry),
        });
      }
    });
    observer.observe({ entryTypes: ['longtask'] });
  } catch {
    // Safari 不支持 longtask：探针整体降级为只记阶段
    observer = null;
  }

  const onFirstInput = () => {
    if (firstInputAt != null) return;
    firstInputAt = now();
    markBootPhase('用户首次输入');
    setTimeout(() => report('首次输入后'), REPORT_DELAY_AFTER_INPUT_MS);
  };

  // compositionstart 覆盖输入法组字，keydown 覆盖直接输入
  window.addEventListener('compositionstart', onFirstInput, { capture: true, once: true });
  window.addEventListener('keydown', onFirstInput, { capture: true, once: true });

  setTimeout(() => report('观测窗口结束'), OBSERVE_WINDOW_MS);
}
