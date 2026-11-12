import { Platform } from 'react-native';

function asDomElement(value: unknown, seen: Set<unknown> = new Set()): HTMLElement | null {
  if (!value || typeof value !== 'object' || seen.has(value)) return null;
  if (value instanceof HTMLElement) return value;
  seen.add(value);
  const raw = value as {
    getScrollableNode?: () => unknown;
    getNativeScrollRef?: () => unknown;
    _nativeNode?: unknown;
  };
  return (
    asDomElement(raw.getScrollableNode?.(), seen) ??
    asDomElement(raw.getNativeScrollRef?.(), seen) ??
    asDomElement(raw._nativeNode, seen)
  );
}

function findOverflowScroll(root: HTMLElement): HTMLElement {
  const queue: HTMLElement[] = [root];
  while (queue.length) {
    const el = queue.shift()!;
    const overflowY = el.style.overflowY || (typeof window !== 'undefined' ? window.getComputedStyle(el).overflowY : '');
    if (overflowY === 'auto' || overflowY === 'scroll') return el;
    for (const child of Array.from(el.children)) {
      if (child instanceof HTMLElement) queue.push(child);
    }
  }
  return root;
}

export function getScrollNode(list: unknown): HTMLElement | null {
  if (!list || Platform.OS !== 'web') return null;
  const root = asDomElement(list);
  if (!root) return null;
  const node = findOverflowScroll(root);
  if (typeof node.scrollTop === 'number' && typeof node.scrollHeight === 'number') return node;
  return null;
}

export function asRectNode(value: unknown): { getBoundingClientRect: () => DOMRect } | null {
  if (!value || typeof value !== 'object') return null;
  const node = value as {
    getBoundingClientRect?: () => DOMRect;
    _nativeNode?: { getBoundingClientRect?: () => DOMRect };
    getNativeRef?: () => unknown;
    getNode?: () => unknown;
  };
  if (typeof node.getBoundingClientRect === 'function') {
    return node as { getBoundingClientRect: () => DOMRect };
  }
  if (typeof node._nativeNode?.getBoundingClientRect === 'function') {
    return node._nativeNode as { getBoundingClientRect: () => DOMRect };
  }
  const nested = node.getNativeRef?.() ?? node.getNode?.();
  if (nested && nested !== value) return asRectNode(nested);
  return null;
}
