// ============================================================
// Web 发版版本判定
//
// 产物里的 chunk 文件名带 content hash，但 Metro 的 moduleId 是构建期递增的整数，
// 一次发版就会整体重排。所以「页面用的是旧构建、服务器上已是新构建」这种混合状态下，
// 异步 chunk 里的模块引用会指到错误的模块，表现就是某个页面点进去整页崩溃
// （典型报错：Cannot read properties of undefined (reading 'Title')），
// 而用户手动刷几次拿到新 index.html 之后就恢复正常。
//
// 这里提供「当前运行的构建」和「服务器上的构建」的比对能力，
// 让加载失败/渲染崩溃时能判断是不是发版造成的，从而只在该刷新时刷新。
// nginx 已把 build-info.json 设为 no-store（见 nginx.conf）。
// ============================================================

const BUILD_INFO_URL = '/build-info.json';

/** 当前页面实际加载的 entry chunk，直接从 DOM 读，和构建产物一一对应 */
export function getRunningEntry(): string | null {
  if (typeof document === 'undefined') return null;
  const el = document.querySelector<HTMLScriptElement>(
    'script[src*="/_expo/static/js/web/entry-"]',
  );
  if (!el) return null;
  try {
    return new URL(el.src, window.location.origin).pathname;
  } catch {
    return el.getAttribute('src');
  }
}

/** 服务器上当前发布的 entry chunk；拿不到（离线/404/老部署没这文件）时返回 null */
export async function fetchDeployedEntry(): Promise<string | null> {
  if (typeof fetch !== 'function') return null;
  try {
    const res = await fetch(`${BUILD_INFO_URL}?t=${Date.now()}`, {
      cache: 'no-store',
      credentials: 'omit',
    });
    if (!res.ok) return null;
    const json: unknown = await res.json();
    const entry = (json as { entry?: unknown } | null)?.entry;
    return typeof entry === 'string' ? entry : null;
  } catch {
    return null;
  }
}

/**
 * 服务器上的构建是否已经和当前页面不一致。
 * 判定不了（网络异常、缺 build-info.json）时返回 false —— 宁可把错误暴露出来，
 * 也不要在原因未知的情况下自动刷新。
 */
export async function isStaleBuild(): Promise<boolean> {
  const running = getRunningEntry();
  if (!running) return false;
  const deployed = await fetchDeployedEntry();
  if (!deployed) return false;
  return deployed !== running;
}
