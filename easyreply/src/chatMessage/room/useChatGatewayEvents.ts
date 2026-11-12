// ============================================================
// 聊天页 WS 业务下行事件路由
//
// 只处理当前聊天房事件；会话列表/缓存写入归全局 Store。
// 入参仅 roomRef：所有 setter / 消息动作 / 归属意图经 .current 调用，
// effect 依赖稳定，避免再订阅一长串回调。
// ============================================================
import { useEffect } from 'react';
import type { RefObject } from 'react';
import { getAgentId, getChatService } from '@/core/im';
import type { IMGatewayEvent, IMServerMessage } from '@/core/im';
import { buildImageMessageContent } from '@/core/im/image-message';
import { getRole } from '@/core/auth';
import { appAlert } from '@/lib/app-alert';
import { gateAfterTaskMode, gateForOwnedActive } from '@/chatMessage/room/chat-input-gate';
import { formatTransferErrorCode } from '@/features/conversations/transfer-agent';
import {
  getClaimedConversationsSnapshot,
  pickPendingAdoptionContext,
} from '@/lib/claimed-conversations-store';
import {
  discardIfStaleAiReviewRequired,
  pickConversationLastServerMsgID,
} from '@/lib/ai-review-freshness';
import type { TakeoverTaskContext } from '@/lib/supervisor-takeover';
import type { ChatRoomHandle } from '@/chatMessage/room/chat-room-handle';
import type { DisplayMessage } from '@/chatMessage/message/chat-message-model';
import {
  outboxApplySubmitResult,
  outboxDequeuePendingKey,
  outboxPatchMessage,
  outboxRemovePending,
  appendOutboxToMessages,
} from '@/chatMessage/message/chat-pending-outbox';

/** 两条我方气泡是否内容实质相同（用于同 serverMsgID 去重，避免误删文本+图片） */
function isSameOutgoingBubble(a: DisplayMessage, b: DisplayMessage): boolean {
  if (a.kind !== b.kind) return false;
  if (a.kind === 'text' && b.kind === 'text') return (a.text || '') === (b.text || '');
  if (a.kind === 'image' && b.kind === 'image') return (a.imageUrl || '') === (b.imageUrl || '');
  if (a.kind === 'voice' && b.kind === 'voice') return (a.voiceUrl || '') === (b.voiceUrl || '');
  if (a.kind === 'video' && b.kind === 'video') return (a.videoUrl || '') === (b.videoUrl || '');
  if (a.kind === 'file' && b.kind === 'file') return (a.fileUrl || '') === (b.fileUrl || '');
  if (a.kind === 'location' && b.kind === 'location') {
    return a.latitude === b.latitude && a.longitude === b.longitude && (a.description || '') === (b.description || '');
  }
  return false;
}

export function useChatGatewayEvents(roomRef: RefObject<ChatRoomHandle>) {
  useEffect(() => {
    const chat = getChatService();
    const off = chat.onGatewayEvent((evt: IMGatewayEvent) => {
      const room = roomRef.current;
      const taskID = room.taskID;

      switch (evt.type) {
        case 'annotation_event': {
          const evtTaskID = evt.task_context?.taskID ?? evt.event?.taskID;
          if (evtTaskID && evtTaskID !== taskID) return;

          const eventType = evt.event?.eventType;
          if (eventType === 2 || eventType === 3) {
            room.localOnlyHistoryRef.current = true;
            room.setInputGate({ phase: 'unavailable' });
            room.setAdoptionContext(null);
            room.setProactiveActionHints(null);
            room.setAdoptionModalOpen(false);
            break;
          }
          if (eventType === 8) {
            // 复审上下文不落缓存：仅当前聊天页内即时展示横幅（已处理水位读会话缓存）
            room.setAdoptionContext(
              pickPendingAdoptionContext(evt.event?.adoptionContext, {
                taskID,
                imConversationID: evt.task_context?.imConversationID,
              }),
            );
            break;
          }
          if (eventType === 5) {
            break;
          }
          const m = evt.event?.message;
          if (m?.serverMsgID) {
            room.mergeServerMessages([m]);
            room.persistMessagesLocally([m]);
            room.scrollToEnd();
          }
          break;
        }
        case 'ai_review_required': {
          const evtTaskID = evt.task_context?.taskID ?? evt.event?.taskID;
          if (evtTaskID && evtTaskID !== taskID) return;
          const imConversationID = evt.task_context?.imConversationID;
          const lastTriggerMsgID = evt.task_context?.lastTriggerMsgID;
          const roomLast =
            room.lastServerMessageRef.current?.serverMsgID?.trim() || null;
          const listLast = pickConversationLastServerMsgID(getClaimedConversationsSnapshot(), {
            taskID: evtTaskID ?? taskID,
            imConversationID,
          });
          if (
            discardIfStaleAiReviewRequired(
              {
                lastTriggerMsgID,
                convLastServerMsgID: roomLast || listLast,
                taskID: evtTaskID ?? taskID,
                imConversationID,
              },
              { stage: 'chat_room', eventID: evt.event?.eventID ?? null },
            )
          ) {
            return;
          }
          // 列表缓存由全局 Store 写入 adoptionContext；此处只更新当前页复审条
          room.setAdoptionContext(
            pickPendingAdoptionContext(evt.event?.adoptionContext, {
              taskID,
              imConversationID: evt.task_context?.imConversationID,
            }),
          );
          break;
        }
        case 'submit_result': {
          if (evt.taskID !== taskID) {
            outboxApplySubmitResult(evt);
            return;
          }
          room.setMessages((prev) => {
            const next = [...prev];
            const pending = room.pendingSendKeysRef.current;
            let idx = -1;
            let matchedClientMsgID: string | undefined;

            const syncOutboxFailed = (clientId: string | undefined) => {
              if (!clientId) return;
              outboxPatchMessage(taskID, clientId, { status: 'failed' });
              outboxDequeuePendingKey(taskID, clientId);
            };
            const syncOutboxSuccess = (clientId: string | undefined) => {
              if (!clientId) return;
              outboxRemovePending(taskID, clientId);
            };

            // 1) 优先用服务端回显的 clientMsgID 精准配对（必须仍是 sending）
            const evtClientMsgID = evt.clientMsgID?.trim();
            if (evtClientMsgID) {
              idx = next.findIndex(
                (x) =>
                  x.status === 'sending' &&
                  (x.clientMsgID === evtClientMsgID || x.key === evtClientMsgID),
              );
              if (idx >= 0) {
                matchedClientMsgID = evtClientMsgID;
                const pi = pending.indexOf(evtClientMsgID);
                if (pi >= 0) pending.splice(pi, 1);
              }
            }

            if (idx < 0) {
              if (evtClientMsgID) {
                outboxApplySubmitResult(evt);
              }
              return appendOutboxToMessages(taskID, next);
            }

            if (!evt.ok) {
              next[idx] = { ...next[idx], status: 'failed' };
              syncOutboxFailed(
                matchedClientMsgID ?? next[idx].clientMsgID ?? next[idx].key ?? evtClientMsgID,
              );
              return appendOutboxToMessages(taskID, next);
            }

            const serverMsgID = evt.serverMsgID?.trim() || undefined;
            const prevItem = next[idx];
            // 若已有另一条不同正文占用同一 serverMsgID，保留本地 key，避免去重误删
            const collision = serverMsgID
              ? next.find(
                  (x, i) =>
                    i !== idx && (x.key === serverMsgID || x.serverMsgID === serverMsgID),
                )
              : undefined;
            const keepLocalKey = !!collision && !isSameOutgoingBubble(collision, prevItem);

            next[idx] = {
              ...prevItem,
              status: 'sent',
              serverMsgID: serverMsgID ?? prevItem.serverMsgID,
              clientMsgID: prevItem.clientMsgID ?? matchedClientMsgID ?? evtClientMsgID,
              key: keepLocalKey ? prevItem.key : serverMsgID ?? prevItem.key,
            };
            syncOutboxSuccess(prevItem.clientMsgID ?? matchedClientMsgID ?? evtClientMsgID);

            if (serverMsgID) {
              for (let i = next.length - 1; i >= 0; i--) {
                if (i === idx) continue;
                if (next[i].key !== serverMsgID && next[i].serverMsgID !== serverMsgID) continue;
                // 仅删除真正重复的气泡；文本+图片等同 ID 时保留两条
                if (!isSameOutgoingBubble(next[i], next[idx])) continue;
                next.splice(i, 1);
              }
              room.seenRef.current.add(serverMsgID);
              const upgraded = next[idx];
              if (!upgraded) return appendOutboxToMessages(taskID, next);
              const cachedMsg: IMServerMessage = {
                serverMsgID,
                clientMsgID: upgraded.clientMsgID,
                contentType:
                  upgraded.kind === 'image'
                    ? 102
                    : upgraded.kind === 'voice'
                      ? 103
                      : upgraded.kind === 'video'
                        ? 104
                        : upgraded.kind === 'file'
                          ? 105
                          : upgraded.kind === 'location'
                            ? 109
                            : 101,
                content:
                  upgraded.kind === 'text'
                    ? upgraded.text
                    : upgraded.kind === 'image'
                      ? JSON.stringify(
                          buildImageMessageContent({
                            url: upgraded.imageUrl,
                            width: upgraded.imageWidth,
                            height: upgraded.imageHeight,
                            contentType: upgraded.isEmojiSticker ? 'emoji' : undefined,
                          }),
                        )
                    : upgraded.kind === 'voice'
                      ? JSON.stringify({
                          duration: Math.round(upgraded.duration * 1000),
                          sourceUrl: upgraded.voiceUrl,
                          dataSize: 0,
                          uuid: '',
                        })
                      : upgraded.kind === 'video'
                        ? JSON.stringify({
                            duration: Math.round(upgraded.duration * 1000),
                            snapshotUrl: upgraded.snapshotUrl,
                            snapshotWidth: upgraded.snapshotWidth || 0,
                            snapshotHeight: upgraded.snapshotHeight || 0,
                            snapshotSize: 0,
                            snapshotUUID: '',
                            videoUrl: upgraded.videoUrl,
                            videoSize: 0,
                            videoType: 'mp4',
                            videoUUID: '',
                          })
                      : upgraded.kind === 'file'
                        ? JSON.stringify({
                            fileName: upgraded.fileName,
                            fileSize: upgraded.fileSize,
                            sourceUrl: upgraded.fileUrl,
                            uuid: '',
                          })
                      : upgraded.kind === 'location'
                        ? JSON.stringify({
                            description: upgraded.description,
                            latitude: upgraded.latitude,
                            longitude: upgraded.longitude,
                          })
                      : '',
                sendTime: upgraded.time,
                direction: 1,
              };
              room.trackLastServerMessage(cachedMsg);
              room.persistMessagesLocally([cachedMsg]);
            }
            return appendOutboxToMessages(taskID, next);
          });
          break;
        }
        case 'ownership_changed': {
          const evtImId = evt.task_context?.imConversationID?.trim() || '';
          const curImId = room.ctxRef.current.conversationID?.trim() || '';
          const sameConv = !!evtImId && !!curImId && evtImId === curImId;
          const sameTask = !!evt.taskID && evt.taskID === taskID;
          if (!sameConv && !sameTask) return;
          if (room.takeoverInProgressRef.current) break;

          if (
            evt.reason === 'return_to_agent' ||
            evt.reason === 'return_to_agent_original_offline'
          ) {
            if (getRole() === 'supervisor') {
              room.enterSupervisorBrowseAfterReturn();
              break;
            }
            const mine = !!evt.currentAssigneeId && evt.currentAssigneeId === getAgentId();
            if (!mine) {
              room.setInputGate({ phase: 'locked', reason: '会话已转交，暂不可发送' });
            }
            break;
          }

          if (room.isSupervisorViewRef.current) {
            room.setInputGate({ phase: 'supervisor_browse' });
            break;
          }
          const mine = evt.currentAssigneeId && evt.currentAssigneeId === getAgentId();
          if (!mine) {
            const lockReason =
              evt.reason === 'supervisor_takeover'
                ? '会话已被主管接管，暂不可发送'
                : '会话已转交，暂不可发送';
            room.setInputGate({
              phase: 'locked',
              reason: lockReason,
              hideMoreMenu:
                evt.reason === 'supervisor_takeover' || evt.reason === 'manual_transfer',
            });
          } else {
            room.setInputGate((g) =>
              gateAfterTaskMode(g, {
                taskMode: room.taskModeRef.current,
                skillGroup: room.skillGroupRef.current,
              }),
            );
          }
          break;
        }
        case 'end_conversation_result': {
          if (evt.taskID === taskID && evt.ok) {
            room.setInputGate({ phase: 'locked', reason: '会话已结束' });
          }
          break;
        }
        case 'report_transfer_result': {
          if (evt.taskID !== taskID) return;
          if (evt.ok) break;
          room.setInputGate({
            phase: 'locked',
            reason: `上报失败：${evt.error ?? '未知错误'}`,
          });
          break;
        }
        case 'supervisor_takeover_result': {
          if (evt.taskID !== taskID) return;
          if (!evt.ok) {
            room.setInputGate({
              phase: 'locked',
              reason: `接管失败：${evt.error ?? '未知错误'}`,
            });
            break;
          }
          const mine = evt.currentAssigneeId ? evt.currentAssigneeId === getAgentId() : true;
          if (!mine) {
            room.setInputGate({ phase: 'supervisor_browse' });
            break;
          }
          void room.enterOwnerAfterTakeover(
            (evt as { task_context?: TakeoverTaskContext }).task_context,
          );
          break;
        }
        case 'supervisor_return_to_agent_result': {
          if (evt.taskID !== taskID) return;
          if (!evt.ok) {
            room.setInputGate({
              phase: 'locked',
              reason: `归还失败：${evt.error ?? '未知错误'}`,
            });
            break;
          }
          room.enterSupervisorBrowseAfterReturn();
          break;
        }
        case 'complete_task_result': {
          if (evt.taskID !== taskID) return;
          if (!evt.ok) {
            room.setInputGate({
              phase: 'locked',
              reason: `标记完成失败：${evt.error ?? '未知错误'}`,
            });
            break;
          }
          room.localOnlyHistoryRef.current = true;
          room.setInputGate({
            phase: 'locked',
            reason: '任务已标记完成',
            hideMoreMenu: true,
          });
          room.setAdoptionContext(null);
          room.setProactiveActionHints(null);
          break;
        }
        case 'set_task_mode_result': {
          if (evt.taskID !== taskID) return;
          if (!evt.ok) {
            room.setInputGate({
              phase: 'locked',
              reason: `AI托管切换失败：${evt.error ?? '未知错误'}`,
            });
            break;
          }
          if (evt.taskMode === 'human' || evt.taskMode === 'ai_assisted') {
            room.setTaskModeState(evt.taskMode);
            if (evt.taskMode === 'human') room.setAdoptionContext(null);
            room.setInputGate((g) =>
              gateAfterTaskMode(g, {
                taskMode: evt.taskMode,
                skillGroup: room.skillGroupRef.current,
              }),
            );
          }
          break;
        }
        case 'ack_pending_result': {
          if (evt.taskID !== taskID) return;
          if (!evt.ok) {
            appAlert('已处理失败', evt.error ?? '请稍后重试');
            break;
          }
          room.setCurrentHasRedDot(false);
          break;
        }
        case 'transfer_task_result': {
          if (evt.taskID !== taskID) return;
          if (!evt.ok) {
            appAlert('转移失败', formatTransferErrorCode(evt.error));
            room.setInputGate(
              gateForOwnedActive({
                taskMode: room.taskModeRef.current,
                skillGroup: room.skillGroupRef.current,
              }),
            );
            break;
          }
          room.setInputGate({
            phase: 'locked',
            reason: '会话已转交',
            hideMoreMenu: true,
          });
          break;
        }
        default:
          break;
      }
    });
    return off;
  }, [roomRef]);
}
