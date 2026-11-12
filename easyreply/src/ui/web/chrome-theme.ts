import { useSyncExternalStore } from 'react';
import { webColor } from '@/ui/web/theme';

/**
 * 桌面四栏工作台皮肤。飞书 = 当前实现抽取；微信 = 产品给定色值。
 * 页面不要再写死这些 hex，统一走 CSS 变量 / chromeCssVars。
 */
export type ChromeThemeId = 'feishu' | 'wechat';

export type ChromeThemeTokens = {
  /** 第一栏背景 */
  siderBg: string;
  /** 第二栏（Actor / 标注员列表）背景 */
  actorPaneBg: string;
  /** 第三栏（Audience / 会话列表）背景 */
  convPaneBg: string;
  /** 第四栏（聊天室）背景 */
  chatPaneBg: string;
  /** 二三四栏间隙 */
  paneGap: string;
  /** 二三四栏自身圆角（飞书四角相同；微信第二栏左、第四栏右） */
  actorPaneRadius: string;
  convPaneRadius: string;
  chatPaneRadius: string;
  /** 二三四栏父级圆角 */
  splitRadius: string;
  /** 二三四栏父级内边距 */
  splitPadding: string;
  /** 用户头像圆角：圆形用 50% */
  avatarRadius: string;
  /** Actor / Audience 默认底（未选中且未悬停） */
  rowIdleBg: string;
  /** Actor / Audience 鼠标扫过未选中行 */
  rowHoverBg: string;
  /** Actor / Audience 选中底 */
  rowSelectedBg: string;
  /** Actor / Audience 未选中 name */
  rowIdleNameFg: string;
  /** Actor / Audience 未选中 sublabel */
  rowIdleSubFg: string;
  /** Actor / Audience 选中 name */
  rowSelectedNameFg: string;
  /** Actor / Audience 选中 sublabel */
  rowSelectedSubFg: string;
  /** Actor / Audience 未选中时间 */
  rowIdleTimeFg: string;
  /** Actor / Audience 选中时间 */
  rowSelectedTimeFg: string;
  /** 聊天页时间 */
  chatTimeFg: string;
  /** 我方气泡底 */
  mineBubbleBg: string;
  /** 我方气泡文字 */
  mineBubbleFg: string;
  /** 我方气泡悬停底 */
  mineBubbleHoverBg: string;
  /** 对方气泡底 */
  peerBubbleBg: string;
  /** 搜索框内部底 */
  searchBg: string;
  /** 搜索框圆角 */
  searchRadius: string;
  /** Actor / Audience cell 分割线；飞书为 transparent */
  rowDivider: string;
  /** Actor / Audience 选中 / 悬停底圆角 */
  rowRadius: string;
};

export const CHROME_THEME_OPTIONS: { id: ChromeThemeId; label: string }[] = [
  { id: 'feishu', label: '飞书' },
  { id: 'wechat', label: '微信' },
];

/** 飞书：从现网 theme.ts / setup-viewport 分栏 CSS 抽出 */
export const FEISHU_CHROME_THEME: ChromeThemeTokens = {
  siderBg: webColor.sidebar,
  actorPaneBg: webColor.pane,
  convPaneBg: webColor.pane,
  chatPaneBg: webColor.chatBg,
  /** .qh-chat-split gap */
  paneGap: '5px',
  actorPaneRadius: '10px',
  convPaneRadius: '10px',
  chatPaneRadius: '10px',
  splitRadius: '0px',
  splitPadding: '5px',
  avatarRadius: '50%',
  rowIdleBg: 'transparent',
  rowHoverBg: webColor.convHover,
  rowSelectedBg: webColor.convSelected,
  rowIdleNameFg: webColor.nameLabel,
  rowIdleSubFg: webColor.subLabel,
  rowSelectedNameFg: webColor.nameLabel,
  rowSelectedSubFg: webColor.subLabel,
  rowIdleTimeFg: webColor.timestamp,
  rowSelectedTimeFg: webColor.timestamp,
  chatTimeFg: webColor.timestamp,
  mineBubbleBg: webColor.primary,
  mineBubbleFg: webColor.onPrimary,
  mineBubbleHoverBg: webColor.primaryPressed,
  peerBubbleBg: webColor.peerBubble,
  searchBg: webColor.search,
  searchRadius: '18px',
  rowDivider: 'transparent',
  rowRadius: '10px',
};

/** 微信：产品给定 */
export const WECHAT_CHROME_THEME: ChromeThemeTokens = {
  siderBg: '#E2E5E6',
  actorPaneBg: '#EEEEF0',
  convPaneBg: '#EEEEF0',
  chatPaneBg: '#FAFAFA',
  paneGap: '1px',
  actorPaneRadius: '5px 0 0 5px',
  convPaneRadius: '0px',
  chatPaneRadius: '0 5px 5px 0',
  splitRadius: '0px',
  splitPadding: '3px',
  avatarRadius: '8px',
  rowIdleBg: 'transparent',
  rowHoverBg: '#E2E2E4',
  rowSelectedBg: '#50A976',
  rowIdleNameFg: '#1A1A1B',
  rowIdleSubFg: '#A0A0A6',
  rowSelectedNameFg: '#EBF6F1',
  rowSelectedSubFg: '#C2E5D5',
  rowIdleTimeFg: '#9F9FA5',
  rowSelectedTimeFg: '#C2E5D5',
  chatTimeFg: '#9F9FA5',
  mineBubbleBg: '#B0F0A7',
  mineBubbleFg: webColor.text,
  mineBubbleHoverBg: '#9FE396',
  peerBubbleBg: '#EEEEF0',
  searchBg: '#FFFFFF',
  searchRadius: '8px',
  rowDivider: '#E7E7E8',
  rowRadius: '5px',
};

export const CHROME_THEMES: Record<ChromeThemeId, ChromeThemeTokens> = {
  feishu: FEISHU_CHROME_THEME,
  wechat: WECHAT_CHROME_THEME,
};

export const chromeCssVars = {
  siderBg: 'var(--qh-sider-bg)',
  actorPaneBg: 'var(--qh-actor-pane-bg)',
  convPaneBg: 'var(--qh-conv-pane-bg)',
  chatPaneBg: 'var(--qh-chat-pane-bg)',
  paneGap: 'var(--qh-pane-gap)',
  actorPaneRadius: 'var(--qh-actor-pane-radius)',
  convPaneRadius: 'var(--qh-conv-pane-radius)',
  chatPaneRadius: 'var(--qh-chat-pane-radius)',
  splitRadius: 'var(--qh-split-radius)',
  splitPadding: 'var(--qh-split-padding)',
  avatarRadius: 'var(--qh-avatar-radius)',
  rowIdleBg: 'var(--qh-row-idle-bg)',
  rowHoverBg: 'var(--qh-row-hover-bg)',
  rowSelectedBg: 'var(--qh-row-selected-bg)',
  rowIdleNameFg: 'var(--qh-row-idle-name)',
  rowIdleSubFg: 'var(--qh-row-idle-sub)',
  rowSelectedNameFg: 'var(--qh-row-selected-name)',
  rowSelectedSubFg: 'var(--qh-row-selected-sub)',
  rowNameFg: 'var(--qh-row-name)',
  rowSubFg: 'var(--qh-row-sub)',
  rowTimeFg: 'var(--qh-row-time)',
  chatTimeFg: 'var(--qh-chat-time)',
  mineBubbleBg: 'var(--qh-mine-bubble)',
  mineBubbleFg: 'var(--qh-mine-bubble-fg)',
  mineBubbleHoverBg: 'var(--qh-mine-bubble-hover)',
  peerBubbleBg: 'var(--qh-peer-bubble)',
  searchBg: 'var(--qh-search-bg)',
  searchRadius: 'var(--qh-search-radius)',
  rowDivider: 'var(--qh-row-divider)',
  rowRadius: 'var(--qh-row-radius)',
} as const;

const STORAGE_KEY = 'qh.web.chromeTheme';

const listeners = new Set<() => void>();

function isChromeThemeId(value: string): value is ChromeThemeId {
  return value === 'feishu' || value === 'wechat';
}

function notify() {
  listeners.forEach((fn) => fn());
}

export function chromeThemeCssVars(tokens: ChromeThemeTokens): Record<string, string> {
  return {
    '--qh-sider-bg': tokens.siderBg,
    '--qh-actor-pane-bg': tokens.actorPaneBg,
    '--qh-conv-pane-bg': tokens.convPaneBg,
    '--qh-chat-pane-bg': tokens.chatPaneBg,
    '--qh-pane-gap': tokens.paneGap,
    '--qh-actor-pane-radius': tokens.actorPaneRadius,
    '--qh-conv-pane-radius': tokens.convPaneRadius,
    '--qh-chat-pane-radius': tokens.chatPaneRadius,
    '--qh-split-radius': tokens.splitRadius,
    '--qh-split-padding': tokens.splitPadding,
    '--qh-avatar-radius': tokens.avatarRadius,
    '--qh-row-idle-bg': tokens.rowIdleBg,
    '--qh-row-hover-bg': tokens.rowHoverBg,
    '--qh-row-selected-bg': tokens.rowSelectedBg,
    '--qh-row-idle-name': tokens.rowIdleNameFg,
    '--qh-row-idle-sub': tokens.rowIdleSubFg,
    '--qh-row-selected-name': tokens.rowSelectedNameFg,
    '--qh-row-selected-sub': tokens.rowSelectedSubFg,
    '--qh-row-idle-time': tokens.rowIdleTimeFg,
    '--qh-row-selected-time': tokens.rowSelectedTimeFg,
    '--qh-chat-time': tokens.chatTimeFg,
    '--qh-mine-bubble': tokens.mineBubbleBg,
    '--qh-mine-bubble-fg': tokens.mineBubbleFg,
    '--qh-mine-bubble-hover': tokens.mineBubbleHoverBg,
    '--qh-peer-bubble': tokens.peerBubbleBg,
    '--qh-search-bg': tokens.searchBg,
    '--qh-search-radius': tokens.searchRadius,
    '--qh-row-divider': tokens.rowDivider,
    '--qh-row-radius': tokens.rowRadius,
  };
}

export function chromeThemeRootCss(tokens: ChromeThemeTokens = FEISHU_CHROME_THEME): string {
  return Object.entries(chromeThemeCssVars(tokens))
    .map(([key, value]) => `${key}: ${value};`)
    .join('\n      ');
}

export function getChromeThemeId(): ChromeThemeId {
  if (typeof localStorage === 'undefined') return 'feishu';
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw && isChromeThemeId(raw)) return raw;
  } catch {
    /* ignore */
  }
  return 'feishu';
}

export function getChromeTheme(): ChromeThemeTokens {
  return CHROME_THEMES[getChromeThemeId()];
}

export function applyChromeTheme(id: ChromeThemeId = getChromeThemeId()): void {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  root.dataset.qhChrome = id;
  Object.entries(chromeThemeCssVars(CHROME_THEMES[id])).forEach(([key, value]) => {
    root.style.setProperty(key, value);
  });
}

export function setChromeThemeId(id: ChromeThemeId): void {
  if (typeof localStorage !== 'undefined') {
    try {
      localStorage.setItem(STORAGE_KEY, id);
    } catch {
      /* ignore quota */
    }
  }
  applyChromeTheme(id);
  notify();
}

export function subscribeChromeTheme(onStoreChange: () => void): () => void {
  listeners.add(onStoreChange);
  return () => {
    listeners.delete(onStoreChange);
  };
}

export function useChromeThemeId(): ChromeThemeId {
  return useSyncExternalStore(subscribeChromeTheme, getChromeThemeId, () => 'feishu');
}
