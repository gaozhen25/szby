/** contentType=109 位置消息 content（与下行 location 结构对齐） */
export type LocationMessageContent = {
  description: string;
  latitude: number;
  longitude: number;
};

export function parseLocationMessageContent(
  raw: unknown,
): LocationMessageContent | null {
  try {
    const parsed = typeof raw === 'string' ? JSON.parse(raw) : raw;
    if (!parsed || typeof parsed !== 'object') return null;
    const latitude = Number((parsed as { latitude?: unknown }).latitude);
    const longitude = Number((parsed as { longitude?: unknown }).longitude);
    if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return null;
    if (Math.abs(latitude) > 90 || Math.abs(longitude) > 180) return null;
    const description =
      typeof (parsed as { description?: unknown }).description === 'string'
        ? (parsed as { description: string }).description.trim()
        : '';
    return { description, latitude, longitude };
  } catch {
    return null;
  }
}

/** 构造 contentType=109 的位置消息 content（客服侧发送时用） */
export function buildLocationMessageContent(params: {
  description?: string;
  latitude: number;
  longitude: number;
}): LocationMessageContent {
  return {
    description: (params.description || '').trim(),
    latitude: params.latitude,
    longitude: params.longitude,
  };
}

/** 列表预览：有地址文案时带上短摘要 */
export function formatLocationPreview(content: LocationMessageContent): string {
  const desc = content.description.trim();
  if (!desc) return '[位置]';
  const short = desc.length > 24 ? `${desc.slice(0, 24)}…` : desc;
  return `[位置] ${short}`;
}

/** 气泡副文案：带经纬度标识 */
export function formatLocationCoordLabel(latitude: number, longitude: number): string {
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return '';
  return `纬度 ${latitude.toFixed(5)}，经度 ${longitude.toFixed(5)}`;
}
