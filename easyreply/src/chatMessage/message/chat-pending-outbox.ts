// ============================================================
// 跨会话切换保留「发送中 / 失败」乐观消息（Outbox）
// 切走再回来时尚未 submit_result 的气泡仍应展示；后台发送继续写 outbox。
// ============================================================
import type { DisplayMessage } from '@/chatMessage/message/chat-message-model';

type TaskOutbox = {
  messages: Map<string, DisplayMessage>;
  pendingKeys: string[];
};

const outboxes = new Map<string, TaskOutbox>();

function getOrCreate(taskID: string): TaskOutbox {
  const id = taskID.trim();
  let box = outboxes.get(id);
  if (!box) {
    box = { messages: new Map(), pendingKeys: [] };
    outboxes.set(id, box);
  }
  return box;
}

function findOutboxMessage(box: TaskOutbox, localKey: string): DisplayMessage | undefined {
  const direct = box.messages.get(localKey);
  if (direct) return direct;
  for (const m of box.messages.values()) {
    if (m.clientMsgID === localKey || m.key === localKey) return m;
  }
  return undefined;
}

function pruneEmpty(taskID: string, box: TaskOutbox) {
  if (box.messages.size === 0 && box.pendingKeys.length === 0) {
    outboxes.delete(taskID.trim());
  }
}

/** 登记乐观消息 + clientMsgID 队列项 */
export function outboxTrackPendingMessage(
  taskID: string,
  message: DisplayMessage,
  localKey: string,
): void {
  const id = taskID.trim();
  if (!id) return;
  const box = getOrCreate(id);
  box.messages.set(message.key, message);
  const key = localKey.trim();
  if (key && !box.pendingKeys.includes(key)) box.pendingKeys.push(key);
}

export function outboxPatchMessage(
  taskID: string,
  localKey: string,
  patch: Partial<DisplayMessage> | ((message: DisplayMessage) => DisplayMessage),
): DisplayMessage | null {
  const id = taskID.trim();
  const box = outboxes.get(id);
  if (!box) return null;
  const prev = findOutboxMessage(box, localKey);
  if (!prev) return null;
  const next = (
    typeof patch === 'function'
      ? patch(prev)
      : {
          ...prev,
          ...patch,
        }
  ) as DisplayMessage;
  box.messages.delete(prev.key);
  box.messages.set(next.key, next);
  return next;
}

export function outboxRemovePending(taskID: string, localKey: string): void {
  const id = taskID.trim();
  const box = outboxes.get(id);
  if (!box) return;
  const target = findOutboxMessage(box, localKey.trim());
  if (target) box.messages.delete(target.key);
  outboxDequeuePendingKey(id, localKey);
  pruneEmpty(id, box);
}

/** 发送失败或已收到 submit_result 后，从 FIFO 队列移除（消息本体可仍保留为 failed） */
export function outboxDequeuePendingKey(taskID: string, localKey: string): void {
  const id = taskID.trim();
  const box = outboxes.get(id);
  if (!box) return;
  const pi = box.pendingKeys.indexOf(localKey.trim());
  if (pi >= 0) box.pendingKeys.splice(pi, 1);
}

/** 当前不在该会话页时，仍根据 submit_result 更新 outbox */
export function outboxApplySubmitResult(evt: {
  taskID?: string | null;
  ok?: boolean;
  clientMsgID?: string | null;
}): void {
  const taskID = evt.taskID?.trim();
  if (!taskID) return;
  const box = outboxes.get(taskID);
  if (!box?.messages.size) return;

  let localKey = evt.clientMsgID?.trim();
  if (localKey) {
    if (!findOutboxMessage(box, localKey)) return;
    outboxDequeuePendingKey(taskID, localKey);
  } else {
    const sending = [...box.messages.values()].filter((m) => m.status === 'sending');
    if (sending.length !== 1) return;
    localKey = sending[0].clientMsgID || sending[0].key;
    outboxDequeuePendingKey(taskID, localKey);
  }

  if (!localKey) return;

  if (!evt.ok) {
    outboxPatchMessage(taskID, localKey, { status: 'failed' });
    outboxDequeuePendingKey(taskID, localKey);
    return;
  }

  outboxRemovePending(taskID, localKey);
}

export function outboxGetPendingMessages(taskID: string): DisplayMessage[] {
  const box = outboxes.get(taskID.trim());
  if (!box?.messages.size) return [];
  return [...box.messages.values()].sort((a, b) => a.time - b.time);
}

export function outboxGetPendingKeys(taskID: string): string[] {
  return [...(outboxes.get(taskID.trim())?.pendingKeys ?? [])];
}

export function outboxHasPendingSend(
  taskID: string,
  kind?: DisplayMessage['kind'],
): boolean {
  return outboxGetPendingMessages(taskID).some(
    (m) => m.status === 'sending' && (kind == null || m.kind === kind),
  );
}

/** 远端/缓存列表合并 outbox：补全缺失项，并用 outbox 纠正 UI 上错位的 sending/failed 状态 */
export function appendOutboxToMessages(
  taskID: string,
  messages: DisplayMessage[],
): DisplayMessage[] {
  const pending = outboxGetPendingMessages(taskID);
  if (!pending.length) return messages;

  const byKey = new Map<string, DisplayMessage>();
  for (const p of pending) {
    byKey.set(p.key, p);
    if (p.clientMsgID) byKey.set(p.clientMsgID, p);
  }

  let changed = false;
  const merged = messages.map((m) => {
    const ob = byKey.get(m.key) ?? (m.clientMsgID ? byKey.get(m.clientMsgID) : undefined);
    if (!ob) return m;
    if (ob.status !== 'sending' && ob.status !== 'failed') return m;
    if (m.status === ob.status && m.key === ob.key) return m;
    changed = true;
    return { ...m, ...ob, status: ob.status };
  });

  const seen = new Set<string>();
  for (const m of merged) {
    if (m.key) seen.add(m.key);
    if (m.clientMsgID) seen.add(m.clientMsgID);
    if (m.serverMsgID) seen.add(m.serverMsgID);
  }

  const extra = pending.filter((p) => {
    if (seen.has(p.key)) return false;
    if (p.clientMsgID && seen.has(p.clientMsgID)) return false;
    return true;
  });
  if (!extra.length && !changed) return messages;

  return [...merged, ...extra].sort((a, b) => a.time - b.time);
}
