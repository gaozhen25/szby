// ============================================================
// 聊天表情草稿：token 文本 ↔ 图文混排展示
// 底层始终用 [名称] 字符串，发送协议不变
// ============================================================
import { getAssetByID } from '@react-native/assets-registry/registry';
import { Image, PixelRatio, Platform, type ImageSourcePropType } from 'react-native';
import {
  WECHAT_EMOJI_SOURCES,
  getWechatEmojiSource,
  parseWechatEmojiText,
} from '@/core/im/wechat-emoji';

const TOKEN_AT_END_RE = /\[[^\]]+\]$/;

/** 表情名 → 可给 <img src> 用的 URI（web / native 均可用） */
const emojiUriCache = new Map<string, string>();

function pickAssetScale(scales: number[], deviceScale: number): number {
  for (let i = 0; i < scales.length; i++) {
    if (scales[i] >= deviceScale) return scales[i];
  }
  return scales[scales.length - 1] || 1;
}

function isUsableImgSrc(uri: string): boolean {
  return (
    /^https?:\/\//i.test(uri) ||
    uri.startsWith('data:') ||
    uri.startsWith('blob:') ||
    uri.startsWith('/') ||
    uri.startsWith('file:')
  );
}

/** Metro 静态资源 → 浏览器可请求的绝对路径（不能用 RN-web 把模块 id 当成 src） */
function metroAssetUri(moduleId: number): string | null {
  const asset = getAssetByID(moduleId);
  if (!asset) return null;
  const scale = pickAssetScale(asset.scales, PixelRatio.get());
  const scaleSuffix = scale === 1 ? '' : `@${scale}x`;
  const type = asset.type ? `.${asset.type}` : '';
  const location = asset.httpServerLocation.replace(/\.\.\//g, '');
  let path = `${location}/${asset.name}${scaleSuffix}${type}`;
  if (!path.startsWith('/')) path = `/${path}`;
  const sep = path.includes('?') ? '&' : '?';
  const relative = `${path}${sep}platform=web&hash=${asset.hash}`;
  if (typeof window !== 'undefined' && window.location?.origin) {
    return `${window.location.origin}${relative}`;
  }
  return relative;
}

/** 将 require() 模块 id 解析为可用的图片 URI（兼容 Web / iOS / Android） */
function resolveRequireModuleUri(moduleId: number): string | null {
  if (Platform.OS === 'web') {
    const metro = metroAssetUri(moduleId);
    if (metro) return metro;
  }

  if (typeof Image.resolveAssetSource === 'function') {
    const uri = Image.resolveAssetSource(moduleId)?.uri?.trim();
    if (uri && isUsableImgSrc(uri) && uri !== String(moduleId)) return uri;
  }
  return null;
}

function resolveImageSourceUri(source: ImageSourcePropType): string | null {
  if (typeof source === 'string') {
    return source.trim() || null;
  }
  if (typeof source === 'number') {
    return resolveRequireModuleUri(source);
  }
  if (typeof source === 'object' && source && 'uri' in source && typeof source.uri === 'string') {
    const uri = source.uri.trim();
    return uri || null;
  }
  return null;
}

export function getWechatEmojiUri(name: string): string | null {
  const cached = emojiUriCache.get(name);
  if (cached) return cached;
  const source = getWechatEmojiSource(name);
  if (!source) return null;
  const uri = resolveImageSourceUri(source);
  if (!uri) return null;
  emojiUriCache.set(name, uri);
  return uri;
}

export function buildWechatEmojiUriMap(): Record<string, string> {
  const map: Record<string, string> = {};
  for (const name of Object.keys(WECHAT_EMOJI_SOURCES)) {
    const uri = getWechatEmojiUri(name);
    if (uri) map[name] = uri;
  }
  return map;
}

/** 末尾退格：整段删除表情 token，否则删一个字符（按 Unicode code point） */
export function backspaceEmojiDraft(text: string): string {
  if (!text) return text;
  const token = text.match(TOKEN_AT_END_RE);
  if (token) return text.slice(0, text.length - token[0].length);
  return Array.from(text).slice(0, -1).join('');
}

export function appendEmojiToken(text: string, name: string): string {
  if (!getWechatEmojiSource(name)) return text;
  return `${text}[${name}]`;
}

/** 将草稿文本渲染为简易 HTML（供 WebView / 调试）；表情为 contenteditable=false 的 img */
export function emojiDraftToHtml(text: string, emojiSize = 22): string {
  if (!text) return '';
  const segments = parseWechatEmojiText(text);
  return segments
    .map((seg) => {
      if (seg.kind === 'text') {
        return escapeHtml(seg.value).replace(/\n/g, '<br>');
      }
      const uri = getWechatEmojiUri(seg.name);
      if (!uri) return escapeHtml(`[${seg.name}]`);
      return `<img data-emoji="${escapeAttr(seg.name)}" src="${escapeAttr(uri)}" class="qh-emoji" width="${emojiSize}" height="${emojiSize}" alt="[${escapeAttr(seg.name)}]" />`;
    })
    .join('');
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function escapeAttr(s: string): string {
  return escapeHtml(s).replace(/'/g, '&#39;');
}
