// ============================================================
// 定时主动触达提醒（annotation_event eventType=5）
// ============================================================
import type { IMAnnotationEventPayload, ProactiveActionHint } from '@/core/im/types';

/** 从 annotation_event 提取有效提醒（event / task_context 双端兼容） */
export function extractProactiveActionHintsFromAnnotationEvent(
  evt: Pick<IMAnnotationEventPayload, 'event' | 'task_context'>,
): ProactiveActionHint[] | undefined {
  return pickValidProactiveActionHints(
    evt.event?.proactiveActionHints ?? evt.task_context?.proactiveActionHints,
  );
}

/** 过滤有效提醒（需有 actionContent） */
export function pickValidProactiveActionHints(
  hints?: ProactiveActionHint[] | null,
): ProactiveActionHint[] | undefined {
  if (!Array.isArray(hints) || hints.length === 0) return undefined;
  const valid = hints.filter((h) => !!h?.actionContent?.trim());
  return valid.length > 0 ? valid : undefined;
}

/** 提醒条展示文案：多条用换行拼接 actionContent */
export function formatProactiveActionHintText(hints?: ProactiveActionHint[] | null): string {
  const valid = pickValidProactiveActionHints(hints);
  if (!valid?.length) return '';
  return valid.map((h) => h.actionContent.trim()).join('\n');
}

/** 判断两条主动触达提醒是否为同一条（用于发送后移除 / 合并去重） */
export function isSameProactiveActionHint(a: ProactiveActionHint, b: ProactiveActionHint): boolean {
  const aSched = a.scheduledTaskID?.trim();
  const bSched = b.scheduledTaskID?.trim();
  if (aSched && bSched && aSched === bSched) return true;
  const aOcc = a.occurrenceKey?.trim();
  const bOcc = b.occurrenceKey?.trim();
  if (aOcc && bOcc && aOcc === bOcc) return true;
  const aContent = a.actionContent?.trim();
  const bContent = b.actionContent?.trim();
  if (!aContent || !bContent || aContent !== bContent) return false;
  const aTask = a.taskName?.trim() ?? '';
  const bTask = b.taskName?.trim() ?? '';
  return aTask === bTask;
}

/** 合并新旧提醒：同 scheduledTaskID / occurrenceKey 覆盖，否则追加 */
export function mergeProactiveActionHints(
  existing: ProactiveActionHint[] | undefined,
  incoming: ProactiveActionHint[],
): ProactiveActionHint[] | undefined {
  const validIncoming = pickValidProactiveActionHints(incoming);
  if (!validIncoming?.length) return pickValidProactiveActionHints(existing);

  const merged = [...(pickValidProactiveActionHints(existing) ?? [])];
  for (const hint of validIncoming) {
    const idx = merged.findIndex((h) => isSameProactiveActionHint(h, hint));
    if (idx >= 0) merged[idx] = hint;
    else merged.push(hint);
  }
  return merged.length > 0 ? merged : undefined;
}

/** 列表项稳定 key */
export function proactiveActionHintKey(item: ProactiveActionHint, index: number): string {
  return item.scheduledTaskID?.trim() || item.occurrenceKey?.trim() || `hint-${index}`;
}
