import { webLayout } from '@/ui/web/theme';

export type PaneKey = 'sider' | 'actor' | 'conv';

const STORAGE_KEY = 'qh.web.paneWidths';
const CSS_VAR: Record<PaneKey, string> = {
  sider: '--qh-pane-sider',
  actor: '--qh-pane-actor',
  conv: '--qh-pane-conv',
};

const BOUNDS: Record<PaneKey, { min: number; max: number }> = {
  sider: { min: webLayout.paneSiderMin, max: webLayout.paneSiderMax },
  actor: { min: webLayout.paneActorMin, max: webLayout.paneActorMax },
  conv: { min: webLayout.paneConvMin, max: webLayout.paneConvMax },
};

type Stored = Partial<Record<PaneKey, number>>;

function clamp(n: number, min: number, max: number) {
  return Math.round(Math.min(max, Math.max(min, n)));
}

function readStored(): Stored {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Stored;
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

function writeStored(next: Stored) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    /* ignore quota */
  }
}

function applyVars(stored: Stored) {
  if (typeof document === 'undefined') return;
  const root = document.documentElement.style;
  (Object.keys(CSS_VAR) as PaneKey[]).forEach((key) => {
    const v = stored[key];
    if (typeof v === 'number' && Number.isFinite(v)) {
      root.setProperty(CSS_VAR[key], `${v}px`);
    }
  });
}

function measure(selector: string): number {
  const el = document.querySelector(selector);
  if (!(el instanceof HTMLElement)) return 0;
  return el.getBoundingClientRect().width;
}

function measureFirst(...selectors: string[]): number {
  for (const selector of selectors) {
    const w = measure(selector);
    if (w) return w;
  }
  return 0;
}

function actorMin(): number {
  if (typeof document !== 'undefined' && document.querySelector('.qh-annotator-list-pane')) {
    return webLayout.paneAnnotatorMin;
  }
  return webLayout.paneActorMin;
}

function maxFor(key: PaneKey, next: number): number {
  const { min, max } = BOUNDS[key];
  const low = key === 'actor' ? actorMin() : min;
  if (key === 'sider') return clamp(next, low, max);

  const win = window.innerWidth;
  const sider = measure('.qh-web-shell .ant-layout-sider') || webLayout.siderWidth;
  const actor = measureFirst('.qh-actor-list-pane', '.qh-annotator-list-pane');
  const conv = measureFirst(
    '.qh-chat-list-pane',
    '.qh-annotator-split--with-chat .qh-annotator-detail-pane',
  );
  const hasChat = !!(
    document.querySelector('.qh-chat-room-pane') || document.querySelector('.qh-annotator-chat-pane')
  );
  const chrome = 20;
  const rest = win - sider - chrome - (hasChat ? webLayout.paneChatMin : 0);
  if (key === 'actor') {
    const other = hasChat ? conv || webLayout.chatListWidth : 0;
    return clamp(next, low, Math.min(max, Math.max(low, rest - other)));
  }
  const other = actor;
  return clamp(next, min, Math.min(max, Math.max(min, rest - other)));
}

/** 启动时把上次拖动的宽度写到 CSS 变量 */
export function initPaneWidths(): void {
  if (typeof document === 'undefined') return;
  applyVars(readStored());
}

export function resizePane(key: PaneKey, nextWidth: number): number {
  const width = maxFor(key, nextWidth);
  const stored = { ...readStored(), [key]: width };
  writeStored(stored);
  applyVars(stored);
  return width;
}
