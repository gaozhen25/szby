// ============================================================
// 后台表情包（/api/app/stickers/*）
// - options：筛选面板分类/标签
// - list / tag-group/list：分页浏览
// - search：关键词 + 标签检索
// ============================================================
import { get, post } from '@/lib/http';

export type StickerTag = {
  code: string;
  name: string;
};

export type StickerOptionGroup = {
  /** 分类编码，供 tag-group/list 的 group_code */
  code: string;
  name: string;
  tags: StickerTag[];
};

export type StickerBoundTag = {
  groupName: string;
  name: string;
};

export type StickerItem = {
  uuid: string;
  name: string;
  file_url: string;
  file_type?: string;
  width?: number;
  height?: number;
  description?: string;
  usage_guide?: string;
  avoid_guide?: string;
  tags?: StickerBoundTag[];
};

export type StickerPage = {
  page_no: number;
  page_size: number;
  total: number;
  has_next: boolean;
  items: StickerItem[];
};

type OkData<T> = { ok?: boolean; data?: T; message?: string; detail?: string };

function unwrapOkData<T>(body: OkData<T>, fallbackMsg: string): T {
  if (body && (body.ok === true || body.data !== undefined)) {
    return body.data as T;
  }
  throw new Error(
    (typeof body?.detail === 'string' && body.detail) ||
      (typeof body?.message === 'string' && body.message) ||
      fallbackMsg,
  );
}

function pickOptionalText(
  o: Record<string, unknown>,
  snake: string,
  camel: string,
): string | undefined {
  if (snake in o || camel in o) {
    const v = snake in o ? o[snake] : o[camel];
    if (typeof v === 'string') return v.trim();
    if (v == null) return '';
  }
  return undefined;
}

function normalizeBoundTags(raw: unknown): StickerBoundTag[] | undefined {
  if (raw === undefined) return undefined;
  if (!Array.isArray(raw)) return [];
  const out: StickerBoundTag[] = [];
  for (const t of raw) {
    if (!t || typeof t !== 'object') continue;
    const o = t as Record<string, unknown>;
    const name = typeof o.name === 'string' ? o.name.trim() : '';
    const groupObj = o.group && typeof o.group === 'object' ? (o.group as Record<string, unknown>) : null;
    const groupName =
      (typeof o.group_name === 'string' && o.group_name.trim()) ||
      (typeof o.groupName === 'string' && o.groupName.trim()) ||
      (groupObj && typeof groupObj.name === 'string' && groupObj.name.trim()) ||
      '';
    if (!name && !groupName) continue;
    out.push({ groupName, name: name || groupName });
  }
  return out;
}

function normalizeStickerItem(raw: unknown): StickerItem | null {
  if (!raw || typeof raw !== 'object') return null;
  const o = raw as Record<string, unknown>;
  const uuid = typeof o.uuid === 'string' ? o.uuid.trim() : '';
  const file_url =
    (typeof o.file_url === 'string' && o.file_url.trim()) ||
    (typeof o.fileUrl === 'string' && o.fileUrl.trim()) ||
    (typeof o.url === 'string' && o.url.trim()) ||
    '';
  if (!uuid || !file_url) return null;
  const tags = normalizeBoundTags(o.tags ?? o.tag_list ?? o.tagList);
  return {
    uuid,
    name: typeof o.name === 'string' ? o.name : '',
    file_url,
    file_type: typeof o.file_type === 'string' ? o.file_type : undefined,
    width: typeof o.width === 'number' && o.width > 0 ? o.width : undefined,
    height: typeof o.height === 'number' && o.height > 0 ? o.height : undefined,
    description: pickOptionalText(o, 'description', 'description'),
    usage_guide: pickOptionalText(o, 'usage_guide', 'usageGuide'),
    avoid_guide: pickOptionalText(o, 'avoid_guide', 'avoidGuide'),
    tags,
  };
}

export function stickerHasDetail(item: StickerItem): boolean {
  return (
    item.description !== undefined &&
    item.usage_guide !== undefined &&
    item.avoid_guide !== undefined &&
    item.tags !== undefined
  );
}

function asPageNum(value: unknown, fallback: number): number {
  if (typeof value === 'number' && Number.isFinite(value) && value > 0) return value;
  if (typeof value === 'string' && value.trim()) {
    const n = Number(value);
    if (Number.isFinite(n) && n > 0) return n;
  }
  return fallback;
}

function asNonNegInt(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value) && value >= 0) return value;
  if (typeof value === 'string' && value.trim()) {
    const n = Number(value);
    if (Number.isFinite(n) && n >= 0) return n;
  }
  return null;
}

function parseBoolish(value: unknown): boolean | null {
  if (value === true || value === 1 || value === '1' || value === 'true') return true;
  if (value === false || value === 0 || value === '0' || value === 'false') return false;
  return null;
}

function normalizePage(raw: unknown): StickerPage {
  const o = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>;
  const itemsRaw = Array.isArray(o.items)
    ? o.items
    : Array.isArray(o.list)
      ? o.list
      : [];
  const items = itemsRaw
    .map(normalizeStickerItem)
    .filter((x): x is StickerItem => !!x);
  const page_no = asPageNum(o.page_no ?? o.pageNo ?? o.page, 1);
  const page_size = asPageNum(o.page_size ?? o.pageSize, items.length || 20);
  const totalKnown = asNonNegInt(o.total);
  const totalPages = asPageNum(o.total_pages ?? o.totalPages, 0);
  const explicitNext = parseBoolish(o.has_next ?? o.hasNext);
  const has_next =
    explicitNext !== null
      ? explicitNext
      : totalPages > 0
        ? page_no < totalPages
        : totalKnown !== null
          ? page_no * page_size < totalKnown
          : items.length >= page_size;
  return {
    page_no,
    page_size,
    total: totalKnown ?? items.length,
    has_next,
    items,
  };
}

function normalizeOptions(raw: unknown): StickerOptionGroup[] {
  if (!Array.isArray(raw)) return [];
  const out: StickerOptionGroup[] = [];
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue;
    const o = item as Record<string, unknown>;
    const code = typeof o.code === 'string' ? o.code.trim() : '';
    const name = typeof o.name === 'string' ? o.name.trim() : code;
    if (!code) continue;
    const tagsRaw = Array.isArray(o.tags) ? o.tags : [];
    const tags: StickerTag[] = [];
    for (const t of tagsRaw) {
      if (!t || typeof t !== 'object') continue;
      const to = t as Record<string, unknown>;
      const tCode = typeof to.code === 'string' ? to.code.trim() : '';
      const tName = typeof to.name === 'string' ? to.name.trim() : tCode;
      if (tCode) tags.push({ code: tCode, name: tName || tCode });
    }
    out.push({ code, name: name || code, tags });
  }
  return out;
}

/** GET /api/app/stickers/options */
export async function fetchStickerOptions(): Promise<StickerOptionGroup[]> {
  const body = await get<OkData<unknown>>('/api/app/stickers/options');
  return normalizeOptions(unwrapOkData(body, '获取表情分类失败'));
}

/** POST /api/app/stickers/list */
export async function fetchStickerList(params?: {
  page_no?: number;
  page_size?: number;
}): Promise<StickerPage> {
  const body = await post<OkData<unknown>>('/api/app/stickers/list', {
    page_no: params?.page_no ?? 1,
    page_size: params?.page_size ?? 20,
  });
  return normalizePage(unwrapOkData(body, '获取表情包失败'));
}

/** POST /api/app/stickers/tag-group/list —— group_code 为 options 外层分类 code */
export async function fetchStickerTagGroupList(params: {
  group_code: string;
  page_no?: number;
  page_size?: number;
}): Promise<StickerPage> {
  const group_code = params.group_code.trim();
  if (!group_code) throw new Error('缺少分类编码');
  const body = await post<OkData<unknown>>('/api/app/stickers/tag-group/list', {
    group_code,
    page_no: params.page_no ?? 1,
    page_size: params.page_size ?? 20,
  });
  return normalizePage(unwrapOkData(body, '获取分类表情包失败'));
}

const SEARCH_LIMIT_MAX = 100;

/** POST /api/app/stickers/search —— tag_codes 为具体标签 code */
export async function searchStickers(params: {
  keyword?: string;
  tag_codes?: string[];
  tag_match?: 'all' | 'any';
  limit?: number;
}): Promise<StickerItem[]> {
  const keyword = params.keyword?.trim() || '';
  const tag_codes = (params.tag_codes || []).map((c) => c.trim()).filter(Boolean);
  if (!keyword && tag_codes.length === 0) return [];

  const limit = Math.min(
    SEARCH_LIMIT_MAX,
    Math.max(1, params.limit ?? SEARCH_LIMIT_MAX),
  );
  const body = await post<OkData<unknown>>('/api/app/stickers/search', {
    keyword,
    tag_codes,
    tag_match: params.tag_match ?? 'all',
    limit,
  });
  const data = unwrapOkData(body, '搜索表情包失败');
  if (!Array.isArray(data)) return [];
  return data.map(normalizeStickerItem).filter((x): x is StickerItem => !!x);
}

/** GET /api/app/stickers/{uuid} */
export async function fetchStickerDetail(uuid: string): Promise<StickerItem> {
  const id = uuid.trim();
  if (!id) throw new Error('缺少表情包 id');
  const body = await get<OkData<unknown>>(`/api/app/stickers/${encodeURIComponent(id)}`);
  const item = normalizeStickerItem(unwrapOkData(body, '获取表情详情失败'));
  if (!item) throw new Error('表情详情无效');
  return item;
}

/** 将后台表情映射为发送用结构（不写入本地自定义表情缓存） */
export function stickerItemToSendable(item: StickerItem): {
  id: string;
  url: string;
  objectKey?: string;
  width?: number;
  height?: number;
  createdAt: number;
} {
  const url = item.file_url.trim();
  let objectKey: string | undefined;
  try {
    if (/^https?:\/\//i.test(url)) {
      const path = new URL(url).pathname.replace(/^\//, '');
      // IM 要求相对 key：edge/... 或 stickers/...（不能发 https 绝对地址）
      if (path.startsWith('edge/') || path.startsWith('stickers/')) objectKey = path;
    } else {
      const key = url.replace(/^\//, '');
      if (key.startsWith('edge/') || key.startsWith('stickers/')) objectKey = key;
    }
  } catch {
    // ignore
  }
  const width = item.width && item.width > 0 ? item.width : 240;
  const height = item.height && item.height > 0 ? item.height : 240;
  return {
    id: `remote-${item.uuid}`,
    url,
    objectKey,
    width,
    height,
    createdAt: 0,
  };
}
