// ============================================================
// Web 异步 chunk 的失败恢复
//
// 两类失败走同一套策略：
//   1. import() 本身 reject（chunk 404 / 网络抖动）
//   2. chunk 加载成功但渲染时崩溃（模块对不上，读属性读到 undefined）
//
// 策略：先按「瞬时抖动」重试一次；仍失败就比对服务器构建版本，
// 只有确认是发版造成的才硬刷新。判定不出来就把错误抛给 ErrorBoundary，
// 让用户看到可重试的界面，而不是白屏或无限刷新。
//
// 防死循环用「已经从哪个构建刷新过」来记，而不是「刷新过几次」：
// 刷新成功后 entry 变了，下次发版还能再自愈一次；
// 若刷新后又回到同一个构建（比如多台机器版本不一致），则不再刷。
// ============================================================
import { getRunningEntry, isStaleBuild } from '@/lib/web-build-version';

const RELOAD_FLAG = 'qh:web-build-reloads';
const MAX_TRACKED = 4;
const RETRY_DELAY_MS = 200;

function readReloadedEntries(): string[] {
  try {
    const raw = sessionStorage.getItem(RELOAD_FLAG);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === 'string') : [];
  } catch {
    return [];
  }
}

function rememberReloadedEntry(entry: string): boolean {
  try {
    const next = [...readReloadedEntries(), entry].slice(-MAX_TRACKED);
    sessionStorage.setItem(RELOAD_FLAG, JSON.stringify(next));
    return true;
  } catch {
    // 隐私模式下 sessionStorage 可能不可用；写不进防重标记就不刷新，避免死循环
    return false;
  }
}

/**
 * 确认是发版导致的失败时硬刷新一次。
 * 返回 true 表示已触发刷新，调用方不用再管这个错误。
 */
export async function recoverIfStaleBuild(): Promise<boolean> {
  if (typeof window === 'undefined') return false;
  const running = getRunningEntry();
  if (!running) return false;
  // 已经从这个构建刷过一次还是坏的，再刷也没用
  if (readReloadedEntries().includes(running)) return false;
  if (!(await isStaleBuild())) return false;
  if (!rememberReloadedEntry(running)) return false;
  window.location.reload();
  return true;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * 包装 React.lazy 的加载函数：失败重试一次，再失败则尝试按发版自愈。
 * 自愈会触发整页刷新，此时返回一个永不 settle 的 promise，
 * 让 Suspense 停在 loading 而不是闪一下错误界面。
 *
 * 开发态不重试：Metro 热更新后旧模块号会失效，重试只会连刷 unknown module。
 */
export function loadChunkWithRecovery<T>(load: () => Promise<T>): () => Promise<T> {
  if (__DEV__) return load;
  return async () => {
    try {
      return await load();
    } catch {
      await delay(RETRY_DELAY_MS);
    }
    try {
      return await load();
    } catch (err) {
      if (await recoverIfStaleBuild()) return new Promise<T>(() => {});
      throw err;
    }
  };
}
