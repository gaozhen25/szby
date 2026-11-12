/** Web 应用内弹层挂载点（手机框内部），避免 RN Modal / portal 到 body 后撑满整个浏览器 */

export const APP_OVERLAY_HOST_ID = 'qh-app-overlay-root';

let overlayHost: HTMLElement | null = null;

export function registerAppOverlayHost(node: unknown): void {
  if (typeof document === 'undefined') return;
  const el =
    node && typeof node === 'object' && 'nodeType' in (node as object)
      ? (node as HTMLElement)
      : null;
  overlayHost = el;
  if (el) el.id = APP_OVERLAY_HOST_ID;
}

export function getAppOverlayHost(): HTMLElement | null {
  if (typeof document === 'undefined') return null;
  if (overlayHost && document.contains(overlayHost)) return overlayHost;
  return document.getElementById(APP_OVERLAY_HOST_ID);
}
