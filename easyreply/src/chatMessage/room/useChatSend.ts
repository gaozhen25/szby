import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type RefObject,
  type SetStateAction,
} from 'react';
import { Platform } from 'react-native';
import * as DocumentPicker from 'expo-document-picker';
import * as ImagePicker from 'expo-image-picker';
import { Image as ExpoImage } from 'expo-image';
import { appAlert } from '@/lib/app-alert';
import { getChatService } from '@/core/im';
import type { AdoptionContext, IMServerMessage, ProactiveActionHint } from '@/core/im';
import { imLog, imWarn } from '@/core/im/utils';
import { ackTaskMessage } from '@/api/tasks';
import {
  CHAT_UPLOAD_OVERSIZE_MESSAGE,
  isChatUploadOverSize,
  uploadFileAsset,
  uploadImageAsset,
  uploadVideoAsset,
  uploadVoiceAsset,
} from '@/api/assets';
import { getHttpErrorMessage } from '@/lib/http';
import { buildFileMessageContent } from '@/core/im/file-message';
import { buildImageMessageContent, parseImageMessageContent } from '@/core/im/image-message';
import { buildVideoMessageContent, normalizeVideoDurationSec } from '@/core/im/video-message';
import { buildVoiceMessageContent } from '@/core/im/voice-message';
import { getFileExtension, inferAttachmentPreviewKind } from '@/chatMessage/message/attachment-mime';
import { emitConversationProcessed } from '@/lib/conversation-processed-bus';
import {
  clearConversationProactiveActionHints,
  getClaimedConversationsSnapshot,
  markConversationAdoptionHandled,
  updateConversationProactiveActionHints,
} from '@/lib/claimed-conversations-store';
import { pickValidAdoptionContext } from '@/lib/annotation-event-list';
import { isSameProactiveActionHint, pickValidProactiveActionHints } from '@/lib/proactive-action-hints';
import { isChatInputOpen, type ChatInputGate } from '@/chatMessage/room/chat-input-gate';
import type { DisplayMessage } from '@/chatMessage/message/chat-message-model';
import {
  appendOutboxToMessages,
  outboxGetPendingKeys,
  outboxHasPendingSend,
  outboxDequeuePendingKey,
  outboxPatchMessage,
  outboxTrackPendingMessage,
} from '@/chatMessage/message/chat-pending-outbox';
import type { VoiceRecorderResult } from '@/chatMessage/message/voice-recorder';
import { prepareVoiceForUpload } from '@/chatMessage/message/prepare-voice-upload';
import { createVideoThumbnail } from '@/chatMessage/message/create-video-thumbnail';
import type { AdoptionDraftItem } from '@/chatMessage/components/AdoptionReviewSheet';
import type { ChatInputAreaHandle } from '@/chatMessage/components/ChatInputArea';
import type { CustomSticker } from '@/chatMessage/stickerPack';
import { ensureCustomStickerSendMeta } from '@/chatMessage/stickerPack';

/**
 * 聊天页所有「往外发」的动作：文本 / 图片 / 视频 / 文件 / 主动提示快捷发送 / AI 复审提交。
 * 共同套路：先乐观插入本地消息 → 滚到底 → emitConversationProcessed 清红点 → 上行 send_message，
 * 失败则把该条本地消息标记为 failed。
 */
export function useChatSend(opts: {
  taskID: string;
  ctxRef: RefObject<{ conversationID: string }>;
  inputGate: ChatInputGate;
  isSupervisorView: boolean;
  /** 草稿在外部 store，这里按需读取，避免把输入变成 handleSend 的依赖导致整页重渲染 */
  getDraft: () => string;
  setDraft: (next: string | ((prev: string) => string)) => void;
  setMessages: Dispatch<SetStateAction<DisplayMessage[]>>;
  scrollToEnd: () => void;
  inputAreaRef: RefObject<ChatInputAreaHandle | null>;
  lastServerMessageRef: RefObject<IMServerMessage | null>;
  /** 本地发出中的 clientMsgID 队列（与 submit_result FIFO 配对） */
  pendingSendKeysRef: RefObject<string[]>;
  /** 当前待复审上下文（提交后按 adoptionID 记「已处理」水位） */
  adoptionContext: AdoptionContext | null;
  setAdoptionContext: Dispatch<SetStateAction<AdoptionContext | null>>;
  setAdoptionModalOpen: Dispatch<SetStateAction<boolean>>;
  setProactiveActionHints: Dispatch<SetStateAction<ProactiveActionHint[] | null>>;
  /** 复审「确定 / 已处理」后结束 90s AI 回复提示窗口 */
  releaseAiReplyCooldown?: () => void;
}) {
  const {
    taskID,
    ctxRef,
    inputGate,
    isSupervisorView,
    getDraft,
    setDraft,
    setMessages,
    scrollToEnd,
    inputAreaRef,
    lastServerMessageRef,
    pendingSendKeysRef,
    adoptionContext,
    setAdoptionContext,
    setAdoptionModalOpen,
    setProactiveActionHints,
    releaseAiReplyCooldown,
  } = opts;

  const [sendingImage, setSendingImage] = useState(false);
  const [sendingVoice, setSendingVoice] = useState(false);
  const [sendingFile, setSendingFile] = useState(false);
  const [sendingVideo, setSendingVideo] = useState(false);
  const [adoptionSubmitting, setAdoptionSubmitting] = useState(false);

  const taskIDRef = useRef(taskID);
  taskIDRef.current = taskID;

  const syncSendingFlags = useCallback((sendTaskID: string) => {
    if (taskIDRef.current !== sendTaskID) return;
    setSendingFile(outboxHasPendingSend(sendTaskID, 'file'));
    setSendingImage(outboxHasPendingSend(sendTaskID, 'image'));
    setSendingVideo(outboxHasPendingSend(sendTaskID, 'video'));
    setSendingVoice(outboxHasPendingSend(sendTaskID, 'voice'));
  }, []);

  useEffect(() => {
    pendingSendKeysRef.current = outboxGetPendingKeys(taskID);
    syncSendingFlags(taskID);
  }, [taskID, pendingSendKeysRef, syncSendingFlags]);

  /** 乐观插入：写入 outbox；仅当前会话页时从 outbox 合并到 React 列表 */
  const appendOptimistic = useCallback(
    (sendTaskID: string, localKey: string, message: DisplayMessage) => {
      outboxTrackPendingMessage(sendTaskID, message, localKey);
      if (taskIDRef.current === sendTaskID) {
        if (!pendingSendKeysRef.current.includes(localKey)) {
          pendingSendKeysRef.current.push(localKey);
        }
        setMessages((prev) => appendOutboxToMessages(sendTaskID, prev));
        scrollToEnd();
      }
    },
    [setMessages, pendingSendKeysRef, scrollToEnd],
  );

  /** 上传过程中更新乐观气泡（缩略图 / 远程 URL 等） */
  const patchOptimistic = useCallback(
    (
      sendTaskID: string,
      localKey: string,
      patch: Partial<DisplayMessage> | ((message: DisplayMessage) => DisplayMessage),
    ) => {
      outboxPatchMessage(sendTaskID, localKey, patch);
      if (taskIDRef.current !== sendTaskID) return;
      setMessages((prev) => {
        const mapped = prev.map((m) => {
          if (m.key !== localKey && m.clientMsgID !== localKey) return m;
          return (
            typeof patch === 'function' ? patch(m) : { ...m, ...patch }
          ) as DisplayMessage;
        });
        return appendOutboxToMessages(sendTaskID, mapped);
      });
    },
    [setMessages],
  );

  const trackOptimisticBatch = useCallback(
    (sendTaskID: string, items: DisplayMessage[]) => {
      if (!items.length) return;
      for (const item of items) {
        const key = item.clientMsgID || item.key;
        outboxTrackPendingMessage(sendTaskID, item, key);
        if (taskIDRef.current === sendTaskID) {
          pendingSendKeysRef.current.push(key);
        }
      }
      if (taskIDRef.current === sendTaskID) {
        setMessages((prev) => [...prev, ...items]);
        scrollToEnd();
      }
    },
    [setMessages, pendingSendKeysRef, scrollToEnd],
  );

  /** 把某条本地消息标记为发送失败，并从待配对队列移除 */
  const markLocalFailed = useCallback(
    (localKey: string, sendTaskID: string = taskIDRef.current) => {
      outboxPatchMessage(sendTaskID, localKey, { status: 'failed' });
      outboxDequeuePendingKey(sendTaskID, localKey);
      if (taskIDRef.current === sendTaskID) {
        const q = pendingSendKeysRef.current;
        const i = q.indexOf(localKey);
        if (i >= 0) q.splice(i, 1);
        setMessages((prev) =>
          prev.map((m) =>
            m.key === localKey || m.clientMsgID === localKey ? { ...m, status: 'failed' } : m,
          ),
        );
      }
    },
    [setMessages, pendingSendKeysRef],
  );

  /**
   * 人工调用 send_message（文本/表情/图/视频/文件/语音等）时：
   * 若有待复审横幅，等同弃用本次 AI 复审（审核不通过）——
   * 清空本地 adoptionContext、写入 handledAdoptionID，并向服务端对候选发 drop。
   */
  const dismissPendingAdoptionOnHumanSend = useCallback(async () => {
    const adoption = pickValidAdoptionContext(adoptionContext);
    if (!adoption) return;

    const imConversationID = ctxRef.current.conversationID || undefined;
    const adoptionID = adoption.adoptionID?.trim();
    const candidates = adoption.candidates ?? [];
    const candidateIDs = candidates
      .map((c) => c.candidateID?.trim())
      .filter((id): id is string => !!id);

    imLog('AI复审', '人工发送消息，弃用待复审 adoption（等同审核不通过）', {
      reason: 'human_send_drop',
      taskID,
      imConversationID,
      adoptionID: adoptionID || null,
      candidateCount: candidates.length,
      candidateIDs,
    });

    // 先清 UI / 本地水位，横幅立刻消失
    setAdoptionContext(null);
    setAdoptionModalOpen(false);
    releaseAiReplyCooldown?.();
    try {
      await markConversationAdoptionHandled({
        taskID,
        imConversationID,
        adoptionID,
      });
      imLog('AI复审', '人工发送弃用：已写入 handledAdoptionID 并清空本地 adoptionContext', {
        reason: 'human_send_drop',
        taskID,
        imConversationID,
        adoptionID: adoptionID || null,
      });
    } catch (e) {
      imWarn('AI复审', '人工发送弃用：写入 handledAdoptionID 失败', {
        reason: 'human_send_drop',
        taskID,
        imConversationID,
        adoptionID: adoptionID || null,
        error: e instanceof Error ? e.message : e,
      });
    }

    // 服务端弃用候选（失败不阻断人工消息）
    const chat = getChatService();
    let droppedOk = 0;
    let droppedFail = 0;
    for (const c of candidates) {
      const candidateID = c.candidateID?.trim();
      if (!candidateID) continue;
      const contentType = (c.contentType === 102 ? 102 : 101) as 101 | 102;
      try {
        await chat.sendMessage(taskID, undefined, contentType, {
          candidateID,
          humanAction: 'drop',
        });
        droppedOk += 1;
      } catch (e) {
        droppedFail += 1;
        imWarn('AI复审', '人工发送弃用：drop 候选失败', {
          reason: 'human_send_drop',
          taskID,
          imConversationID,
          adoptionID: adoptionID || null,
          candidateID,
          contentType,
          error: e instanceof Error ? e.message : e,
        });
      }
    }
    imLog('AI复审', '人工发送弃用：服务端 drop 完成', {
      reason: 'human_send_drop',
      taskID,
      imConversationID,
      adoptionID: adoptionID || null,
      droppedOk,
      droppedFail,
    });
  }, [
    adoptionContext,
    taskID,
    ctxRef,
    setAdoptionContext,
    setAdoptionModalOpen,
    releaseAiReplyCooldown,
  ]);

  const handleSend = useCallback((textOverride?: string) => {
    const text = (textOverride ?? getDraft()).trim();
    if (!text || !isChatInputOpen(inputGate)) return;
    const sendTaskID = taskID;
    const localKey = `local-${Date.now()}`;
    appendOptimistic(sendTaskID, localKey, {
      key: localKey,
      clientMsgID: localKey,
      mine: true,
      kind: 'text',
      text,
      time: Date.now(),
      status: 'sending',
    });
    setDraft('');
    // 客服回复即视为已处理，清除会话列表红点
    emitConversationProcessed({ taskID: sendTaskID, imConversationID: ctxRef.current.conversationID });
    void (async () => {
      try {
        await getChatService().sendMessage(sendTaskID, text, 101, { clientMsgID: localKey });
        await dismissPendingAdoptionOnHumanSend();
      } catch {
        markLocalFailed(localKey, sendTaskID);
      }
    })();
  }, [
    getDraft,
    inputGate,
    taskID,
    ctxRef,
    setDraft,
    markLocalFailed,
    appendOptimistic,
    dismissPendingAdoptionOnHumanSend,
  ]);

  const sendPickedImage = useCallback(
    async (asset: ImagePicker.ImagePickerAsset) => {
      const sendTaskID = taskID;
      const localKey = `local-${Date.now()}`;
      appendOptimistic(sendTaskID, localKey, {
        key: localKey,
        clientMsgID: localKey,
        mine: true,
        kind: 'image',
        imageUrl: asset.uri,
        imageWidth: asset.width,
        imageHeight: asset.height,
        time: Date.now(),
        status: 'sending',
      });
      syncSendingFlags(sendTaskID);

      try {
        const pickerFile =
          asset.file && typeof Blob !== 'undefined' && asset.file instanceof Blob
            ? asset.file
            : undefined;
        const uploaded = await uploadImageAsset({
          uri: asset.uri,
          fileName:
            asset.fileName ||
            (pickerFile && 'name' in pickerFile
              ? String((pickerFile as File).name || '')
              : undefined),
          mimeType: asset.mimeType || pickerFile?.type,
          blob: pickerFile,
          width: asset.width,
          height: asset.height,
        });
        const content = buildImageMessageContent({
          url: uploaded.url,
          objectKey: uploaded.objectKey,
          width: asset.width,
          height: asset.height,
          contentType:
            asset.mimeType === 'image/gif' || pickerFile?.type === 'image/gif'
              ? 'image/gif'
              : uploaded.contentType || asset.mimeType || pickerFile?.type,
        });
        // 上传成功后立刻换成远端 URL；否则文件选择路径会 revoke blob:，气泡会裂图
        const remoteRaw = uploaded.objectKey || uploaded.url;
        const base = (process.env.EXPO_PUBLIC_OSS_BASE_URL || '').replace(/\/+$/, '');
        const remoteUrl =
          remoteRaw && !/^https?:\/\//i.test(remoteRaw) && base
            ? `${base}/${remoteRaw.replace(/^\/+/, '')}`
            : remoteRaw || asset.uri;
        patchOptimistic(sendTaskID, localKey, (m) =>
          m.kind === 'image' ? { ...m, imageUrl: remoteUrl } : m,
        );
        await getChatService().sendMessage(sendTaskID, content, 102, { clientMsgID: localKey });
        await dismissPendingAdoptionOnHumanSend();
        emitConversationProcessed({ taskID: sendTaskID, imConversationID: ctxRef.current.conversationID });
      } catch (e) {
        markLocalFailed(localKey, sendTaskID);
        appAlert('图片发送失败', getHttpErrorMessage(e));
      } finally {
        syncSendingFlags(sendTaskID);
      }
    },
    [
      taskID,
      ctxRef,
      markLocalFailed,
      appendOptimistic,
      patchOptimistic,
      syncSendingFlags,
      dismissPendingAdoptionOnHumanSend,
    ],
  );

  const handlePickImage = useCallback(async () => {
    if (!isChatInputOpen(inputGate)) return;
    inputAreaRef.current?.closeAttachPanel();

    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) {
      appAlert('需要相册权限', '请在系统设置中允许访问相册');
      return;
    }

    const picked = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      // 避免系统把 GIF 转码成兼容静态图（JPEG）
      quality: 1,
      allowsEditing: false,
      preferredAssetRepresentationMode:
        ImagePicker.UIImagePickerPreferredAssetRepresentationMode.Current,
    });
    console.log('[chat] pick image raw', picked);
    if (picked.canceled || !picked.assets?.[0]) return;
    await sendPickedImage(picked.assets[0]);
  }, [inputGate, sendPickedImage, inputAreaRef]);

  /** 发送本地/后台表情（URL 已就绪，picture.type=emoji） */
  const handleSendSticker = useCallback(
    async (sticker: CustomSticker) => {
      if (!isChatInputOpen(inputGate)) return;
      const url = sticker.url?.trim();
      if (!url) return;

      let ready = sticker;
      const hasSize =
        typeof sticker.width === 'number' &&
        sticker.width > 0 &&
        typeof sticker.height === 'number' &&
        sticker.height > 0;
      // 后台表情已带宽高时跳过 hydrate/loadAsync，避免 Web 跨域探测报错
      if (!hasSize || !sticker.id.startsWith('remote-')) {
        try {
          ready = await ensureCustomStickerSendMeta(sticker);
        } catch {
          ready = {
            ...sticker,
            width: sticker.width && sticker.width > 0 ? sticker.width : 300,
            height: sticker.height && sticker.height > 0 ? sticker.height : 300,
          };
        }
      }

      const sendTaskID = taskID;
      const localKey = `local-sticker-${Date.now()}`;
      appendOptimistic(sendTaskID, localKey, {
        key: localKey,
        clientMsgID: localKey,
        mine: true,
        kind: 'image',
        imageUrl: url,
        imageWidth: ready.width,
        imageHeight: ready.height,
        isEmojiSticker: true,
        time: Date.now(),
        status: 'sending',
      });
      syncSendingFlags(sendTaskID);
      emitConversationProcessed({ taskID: sendTaskID, imConversationID: ctxRef.current.conversationID });

      try {
        const content = buildImageMessageContent({
          url,
          objectKey: ready.objectKey,
          width: ready.width,
          height: ready.height,
          contentType: 'emoji',
        });
        await getChatService().sendMessage(sendTaskID, content, 102, { clientMsgID: localKey });
        await dismissPendingAdoptionOnHumanSend();
      } catch {
        markLocalFailed(localKey, sendTaskID);
        appAlert('表情发送失败', '请稍后重试');
      } finally {
        syncSendingFlags(sendTaskID);
      }
    },
    [
      inputGate,
      taskID,
      ctxRef,
      markLocalFailed,
      appendOptimistic,
      syncSendingFlags,
      dismissPendingAdoptionOnHumanSend,
    ],
  );

  const handleTakePhoto = useCallback(async () => {
    if (!isChatInputOpen(inputGate)) return;
    inputAreaRef.current?.closeAttachPanel();

    if (Platform.OS === 'web') {
      appAlert('提示', 'Web 端暂不支持拍照，请使用上传图片');
      return;
    }

    const perm = await ImagePicker.requestCameraPermissionsAsync();
    if (!perm.granted) {
      appAlert('需要相机权限', '请在系统设置中允许访问相机');
      return;
    }

    const picked = await ImagePicker.launchCameraAsync({
      mediaTypes: ['images'],
      quality: 1,
      allowsEditing: false,
    });
    if (picked.canceled || !picked.assets?.[0]) return;
    await sendPickedImage(picked.assets[0]);
  }, [inputGate, sendPickedImage, inputAreaRef]);

  /** 判断选中的文件是否应按视频消息（104）发送 */
  const isVideoFileSelection = useCallback((params: { fileName?: string; mimeType?: string }) => {
    const mime = (params.mimeType || '').trim().toLowerCase();
    if (mime.startsWith('video/')) return true;
    const name = (params.fileName || '').trim().toLowerCase();
    const ext = name.includes('.') ? name.split('.').pop() || '' : '';
    return [
      'mp4',
      'mov',
      'm4v',
      'webm',
      'avi',
      'mkv',
      '3gp',
      '3gpp',
      'mpeg',
      'mpg',
      'wmv',
      'flv',
      'ts',
    ].includes(ext);
  }, []);

  const isImageFileSelection = useCallback((params: { fileName?: string; mimeType?: string }) => {
    const mime = (params.mimeType || '').trim().toLowerCase();
    if (mime.startsWith('image/')) return true;
    return inferAttachmentPreviewKind(params.fileName) === 'image';
  }, []);

  const sendImageDocument = useCallback(
    async (params: {
      uri: string;
      fileName: string;
      mimeType?: string | null;
      blob?: Blob | null;
    }) => {
      const ref = await ExpoImage.loadAsync(params.uri);
      const width = ref.width || 0;
      const height = ref.height || 0;
      if (width <= 0 || height <= 0) {
        throw new Error('无法识别图片尺寸');
      }

      await sendPickedImage({
        uri: params.uri,
        width,
        height,
        fileName: params.fileName,
        mimeType: params.mimeType || undefined,
        fileSize: undefined,
        type: 'image',
        exif: null,
        base64: null,
        duration: null,
        file: params.blob ?? null,
        pairedVideoAsset: null,
        assetId: null,
      } as unknown as ImagePicker.ImagePickerAsset);
    },
    [sendPickedImage],
  );

  const resolveVideoUploadMeta = useCallback((params: { fileName?: string | null; mimeType?: string | null }) => {
    const mime = (params.mimeType || '').trim().toLowerCase();
    const ext = getFileExtension(params.fileName || undefined);

    if (mime === 'video/quicktime' || ext === 'mov') {
      const baseName = ((params.fileName || '').trim() || `video-${Date.now()}`).replace(/\.[^.]+$/, '');
      return {
        fileName: `${baseName}.mov`,
        mimeType: 'video/quicktime' as const,
        videoType: 'mov',
      };
    }

    if (
      mime === 'video/mp4'
      || ext === 'mp4'
      || ext === 'm4v'
      || !mime
    ) {
      const baseName = ((params.fileName || '').trim() || `video-${Date.now()}`).replace(/\.[^.]+$/, '');
      return {
        fileName: `${baseName}.mp4`,
        mimeType: 'video/mp4' as const,
        videoType: 'mp4',
      };
    }

    return null;
  }, []);

  /** 上传并发送视频消息 contentType=104（相册选视频 / 文件里选视频共用） */
  const sendVideoMessage = useCallback(
    async (params: {
      uri: string;
      fileName?: string | null;
      fileSize?: number | null;
      durationRaw?: number | null;
      width?: number | null;
      height?: number | null;
      blob?: Blob;
      mimeType?: string | null;
    }) => {
      if (!isChatInputOpen(inputGate)) return;
      if (isChatUploadOverSize(params.fileSize) || isChatUploadOverSize(params.blob?.size)) {
        appAlert('文件过大', CHAT_UPLOAD_OVERSIZE_MESSAGE);
        return;
      }
      const sendTaskID = taskID;
      const localKey = `local-${Date.now()}`;
      const durationSec = normalizeVideoDurationSec(params.durationRaw ?? 1);

      appendOptimistic(sendTaskID, localKey, {
        key: localKey,
        clientMsgID: localKey,
        mine: true,
        kind: 'video',
        videoUrl: params.uri,
        snapshotUrl: params.uri,
        snapshotWidth: params.width || undefined,
        snapshotHeight: params.height || undefined,
        duration: durationSec,
        time: Date.now(),
        status: 'sending',
      });
      syncSendingFlags(sendTaskID);

      try {
        const thumb = await createVideoThumbnail(params.uri);
        patchOptimistic(sendTaskID, localKey, (m) =>
          m.kind === 'video'
            ? {
                ...m,
                snapshotUrl: thumb.uri,
                snapshotWidth: thumb.width,
                snapshotHeight: thumb.height,
              }
            : m,
        );

        let videoBlob = params.blob;
        if (Platform.OS === 'web' && !videoBlob) {
          const res = await fetch(params.uri);
          videoBlob = await res.blob();
        }

        const videoMeta = resolveVideoUploadMeta({
          fileName: params.fileName,
          mimeType: params.mimeType || videoBlob?.type || null,
        });
        if (!videoMeta) {
          throw new Error('当前仅支持上传 mp4 或 mov 视频');
        }
        const uploadedVideo = await uploadVideoAsset({
          uri: params.uri,
          fileName: videoMeta.fileName,
          mimeType: videoMeta.mimeType,
          blob: videoBlob,
        });

        const uploadedSnap = await uploadImageAsset({
          uri: thumb.uri,
          fileName: `video-cover-${Date.now()}.jpg`,
          mimeType: 'image/jpeg',
          blob: thumb.blob,
          width: thumb.width,
          height: thumb.height,
        });

        const content = buildVideoMessageContent({
          videoUrl: uploadedVideo.url,
          videoObjectKey: uploadedVideo.objectKey,
          videoSize: uploadedVideo.size || videoBlob?.size || params.fileSize || 0,
          videoType: videoMeta.videoType,
          durationSec,
          snapshotUrl: uploadedSnap.url,
          snapshotObjectKey: uploadedSnap.objectKey,
          snapshotWidth: thumb.width,
          snapshotHeight: thumb.height,
          snapshotSize: uploadedSnap.size || thumb.blob?.size || 0,
        });

        const base = (process.env.EXPO_PUBLIC_OSS_BASE_URL || '').replace(/\/+$/, '');
        const toAbs = (raw: string) =>
          raw && !/^https?:\/\//i.test(raw) && base
            ? `${base}/${raw.replace(/^\/+/, '')}`
            : raw;
        const remoteVideo = toAbs(uploadedVideo.objectKey || uploadedVideo.url) || params.uri;
        const remoteSnap = toAbs(uploadedSnap.objectKey || uploadedSnap.url) || thumb.uri;
        patchOptimistic(sendTaskID, localKey, (m) =>
          m.kind === 'video' ? { ...m, videoUrl: remoteVideo, snapshotUrl: remoteSnap } : m,
        );

        await getChatService().sendMessage(sendTaskID, content, 104, { clientMsgID: localKey });
        await dismissPendingAdoptionOnHumanSend();
        emitConversationProcessed({ taskID: sendTaskID, imConversationID: ctxRef.current.conversationID });
      } catch (e) {
        markLocalFailed(localKey, sendTaskID);
        appAlert('视频发送失败', getHttpErrorMessage(e));
      } finally {
        syncSendingFlags(sendTaskID);
      }
    },
    [
      inputGate,
      resolveVideoUploadMeta,
      taskID,
      ctxRef,
      markLocalFailed,
      appendOptimistic,
      patchOptimistic,
      syncSendingFlags,
      dismissPendingAdoptionOnHumanSend,
    ],
  );

  /** 视频：相册选视频 → contentType=104 */
  const handlePickVideo = useCallback(async () => {
    if (!isChatInputOpen(inputGate)) return;
    inputAreaRef.current?.closeAttachPanel();

    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) {
      appAlert('需要相册权限', '请在系统设置中允许访问相册');
      return;
    }

    const picked = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['videos'],
      quality: 1,
      allowsEditing: false,
      videoMaxDuration: 60,
    });
    console.log('[chat] pick video raw', picked);
    if (picked.canceled || !picked.assets?.[0]) return;

    const asset = picked.assets[0];
    let blob: Blob | undefined;
    if (Platform.OS === 'web' && asset.file) {
      blob = asset.file;
    }
    await sendVideoMessage({
      uri: asset.uri,
      fileName: asset.fileName,
      fileSize: asset.fileSize,
      durationRaw: asset.duration,
      width: asset.width,
      height: asset.height,
      blob,
      mimeType: asset.mimeType,
    });
  }, [inputGate, sendVideoMessage, inputAreaRef]);

  /** 文件：选文件 → 若是视频则走 104，否则 contentType=105 */
  const sendPickedFileAsset = useCallback(
    async (asset: {
      uri: string;
      fileName: string;
      fileSize: number;
      mimeType: string;
      blob?: Blob | null;
    }) => {
      const fileName = (asset.fileName || `file-${Date.now()}`).trim() || `file-${Date.now()}`;
      const fileSize =
        typeof asset.fileSize === 'number' && Number.isFinite(asset.fileSize) ? asset.fileSize : 0;
      const mimeType = asset.mimeType || 'application/octet-stream';
      const revokeUri = asset.uri.startsWith('blob:') ? asset.uri : null;

      console.log('[Chat][File] 选中文件', {
        platform: Platform.OS,
        uri: asset.uri,
        resolvedFileName: fileName,
        resolvedMimeType: mimeType,
        resolvedFileSize: fileSize,
        asImage: isImageFileSelection({ fileName, mimeType }),
        asVideo: isVideoFileSelection({ fileName, mimeType }),
      });

      try {
        if (isChatUploadOverSize(fileSize)) {
          appAlert('文件过大', CHAT_UPLOAD_OVERSIZE_MESSAGE);
          return;
        }

        if (isImageFileSelection({ fileName, mimeType })) {
          let imageBlob = asset.blob ?? undefined;
          if (!imageBlob && Platform.OS === 'web') {
            const res = await fetch(asset.uri);
            imageBlob = await res.blob();
          }
          await sendImageDocument({
            uri: asset.uri,
            fileName,
            mimeType,
            blob: imageBlob,
          });
          return;
        }

        if (isVideoFileSelection({ fileName, mimeType })) {
          let blob = asset.blob ?? undefined;
          if (!blob && Platform.OS === 'web') {
            const res = await fetch(asset.uri);
            blob = await res.blob();
          }
          await sendVideoMessage({
            uri: asset.uri,
            fileName,
            fileSize,
            durationRaw: null,
            blob,
            mimeType,
          });
          return;
        }

        const sendTaskID = taskID;
        const localKey = `local-${Date.now()}`;

        appendOptimistic(sendTaskID, localKey, {
          key: localKey,
          clientMsgID: localKey,
          mine: true,
          kind: 'file',
          fileName,
          fileSize,
          fileUrl: asset.uri,
          time: Date.now(),
          status: 'sending',
        });
        syncSendingFlags(sendTaskID);

        try {
          let blob = asset.blob ?? undefined;
          if (!blob && Platform.OS === 'web') {
            const res = await fetch(asset.uri);
            blob = await res.blob();
          }
          const uploaded = await uploadFileAsset({
            uri: asset.uri,
            fileName,
            mimeType,
            blob,
          });
          const content = buildFileMessageContent({
            fileName,
            fileSize: uploaded.size || fileSize || blob?.size || 0,
            sourceUrl: uploaded.url,
            objectKey: uploaded.objectKey,
          });
          const remoteUrl = uploaded.objectKey || uploaded.url;
          const base = (process.env.EXPO_PUBLIC_OSS_BASE_URL || '').replace(/\/+$/, '');
          const openUrl =
            remoteUrl && !/^https?:\/\//i.test(remoteUrl) && base
              ? `${base}/${remoteUrl.replace(/^\/+/, '')}`
              : remoteUrl || asset.uri;
          patchOptimistic(sendTaskID, localKey, (m) =>
            m.kind === 'file'
              ? { ...m, fileUrl: openUrl, fileSize: content.fileSize }
              : m,
          );
          await getChatService().sendMessage(sendTaskID, content, 105, { clientMsgID: localKey });
          await dismissPendingAdoptionOnHumanSend();
          emitConversationProcessed({ taskID: sendTaskID, imConversationID: ctxRef.current.conversationID });
        } catch (e) {
          markLocalFailed(localKey, sendTaskID);
          appAlert('文件发送失败', getHttpErrorMessage(e));
        } finally {
          syncSendingFlags(sendTaskID);
        }
      } finally {
        if (revokeUri) URL.revokeObjectURL(revokeUri);
      }
    },
    [
      isImageFileSelection,
      isVideoFileSelection,
      sendImageDocument,
      sendVideoMessage,
      taskID,
      ctxRef,
      markLocalFailed,
      appendOptimistic,
      patchOptimistic,
      syncSendingFlags,
      dismissPendingAdoptionOnHumanSend,
    ],
  );

  const handleSendPickedFile = useCallback(
    async (file: File) => {
      console.log('[chat] pick file raw', file, {
        name: file.name,
        size: file.size,
        type: file.type,
        lastModified: file.lastModified,
      });
      if (!isChatInputOpen(inputGate)) return;
      await sendPickedFileAsset({
        uri: URL.createObjectURL(file),
        fileName: file.name,
        fileSize: file.size,
        mimeType: file.type || 'application/octet-stream',
        blob: file,
      });
    },
    [inputGate, sendPickedFileAsset],
  );

  const handlePickFile = useCallback(async () => {
    if (!isChatInputOpen(inputGate)) return;
    inputAreaRef.current?.closeAttachPanel();

    if (Platform.OS === 'web') {
      // Web 端由 WebChatComposer 的 Upload 直接传入 File，避免二次弹文件选择器
      return;
    }

    try {
      const picked = await DocumentPicker.getDocumentAsync({
        copyToCacheDirectory: true,
        multiple: false,
      });
      if (picked.canceled || !picked.assets?.[0]) return;

      const asset = picked.assets[0];
      await sendPickedFileAsset({
        uri: asset.uri,
        fileName: (asset.name || `file-${Date.now()}`).trim() || `file-${Date.now()}`,
        fileSize: typeof asset.size === 'number' && Number.isFinite(asset.size) ? asset.size : 0,
        mimeType: asset.mimeType || 'application/octet-stream',
      });
    } catch (e) {
      appAlert('选择文件失败', e instanceof Error ? e.message : '请稍后重试');
    }
  }, [
    inputGate,
    sendPickedFileAsset,
    inputAreaRef,
  ]);

  /** 语音：先上传音频，再 send_message contentType=103 */
  const handleSendVoice = useCallback(
    async (result: VoiceRecorderResult) => {
      if (!isChatInputOpen(inputGate) || sendingVoice) return;
      const sendTaskID = taskID;
      const localKey = `local-${Date.now()}`;
      const duration = Math.max(1, Math.round(result.durationSec));
      appendOptimistic(sendTaskID, localKey, {
        key: localKey,
        clientMsgID: localKey,
        mine: true,
        kind: 'voice',
        voiceUrl: result.uri,
        duration,
        time: Date.now(),
        status: 'sending',
      });
      syncSendingFlags(sendTaskID);

      try {
        const prepared = await prepareVoiceForUpload(result);
        const uploaded = await uploadVoiceAsset({
          uri: prepared.uri,
          fileName: prepared.fileName,
          mimeType: prepared.mimeType,
          blob: prepared.blob,
        });
        const content = buildVoiceMessageContent({
          sourceUrl: uploaded.url,
          objectKey: uploaded.objectKey,
          dataSize: uploaded.size || prepared.size,
          durationSec: result.durationSec,
        });
        const remoteUrl = uploaded.objectKey || uploaded.url;
        const base = (process.env.EXPO_PUBLIC_OSS_BASE_URL || '').replace(/\/+$/, '');
        const playUrl =
          remoteUrl && !/^https?:\/\//i.test(remoteUrl) && base
            ? `${base}/${remoteUrl.replace(/^\/+/, '')}`
            : remoteUrl || prepared.uri;
        patchOptimistic(sendTaskID, localKey, (m) =>
          m.kind === 'voice' ? { ...m, voiceUrl: playUrl } : m,
        );
        await getChatService().sendMessage(sendTaskID, content, 103, { clientMsgID: localKey });
        await dismissPendingAdoptionOnHumanSend();
        emitConversationProcessed({ taskID: sendTaskID, imConversationID: ctxRef.current.conversationID });
      } catch (e) {
        markLocalFailed(localKey, sendTaskID);
        appAlert('语音发送失败', getHttpErrorMessage(e));
      } finally {
        syncSendingFlags(sendTaskID);
      }
    },
    [
      inputGate,
      sendingVoice,
      taskID,
      ctxRef,
      markLocalFailed,
      appendOptimistic,
      patchOptimistic,
      syncSendingFlags,
      dismissPendingAdoptionOnHumanSend,
    ],
  );

  const handleAdoptionSubmit = useCallback((
    drafts: AdoptionDraftItem[],
    mode: 'confirm' | 'drop' | 'rewrite',
    submitOpts?: { rewriteContent?: string; droppedDrafts?: AdoptionDraftItem[] },
  ) => {
    if (adoptionSubmitting) return;
    if (mode !== 'rewrite' && !drafts.length) return;
    if (mode === 'rewrite' && !(submitOpts?.rewriteContent ?? '').trim()) return;

    void (async () => {
      setAdoptionSubmitting(true);
      try {
        const chat = getChatService();
        const imConversationID = ctxRef.current.conversationID || undefined;
        const dropped = submitOpts?.droppedDrafts ?? [];

        const dropCandidates = async (items: AdoptionDraftItem[]) => {
          for (const d of items) {
            if (!d.candidateID) continue;
            const contentType = (d.contentType === 102 ? 102 : 101) as 101 | 102;
            await chat.sendMessage(taskID, undefined, contentType, {
              candidateID: d.candidateID,
              humanAction: 'drop',
            });
          }
        };

        // 确定发送：先把正文乐观插入本地消息列表，再上行 send_message
        if (mode === 'confirm') {
          const baseTs = Date.now();
          const localItems: DisplayMessage[] = [];
          // 文本候选与上行顺序对齐：每条登记独立 clientMsgID，避免 submit_result 错绑到第一条
          const sendPlan: Array<{
            candidateID: string;
            contentType: 101 | 102;
            content: string | object;
            humanAction: 'approve_original' | 'edit';
            localKey?: string;
          }> = [];

          drafts.forEach((d, i) => {
            if (!d.candidateID) return;
            const contentType = (d.contentType === 102 ? 102 : 101) as 101 | 102;
            const edited = d.content.trim();
            if (!edited) return;
            const humanAction =
              edited === (d.originalContent || '').trim() ? 'approve_original' : 'edit';
            const localKey = `local-adoption-${baseTs}-${i}`;

            if (contentType === 102) {
              const parsed = parseImageMessageContent(edited);
              localItems.push({
                key: localKey,
                clientMsgID: localKey,
                mine: true,
                kind: 'image',
                imageUrl: parsed?.imageUrl || '',
                imageWidth: parsed?.imageWidth,
                imageHeight: parsed?.imageHeight,
                isEmojiSticker: parsed?.isEmojiSticker,
                time: baseTs + i,
                status: 'sending',
              });
              let wireContent: string | object = edited;
              try {
                const obj = JSON.parse(edited);
                if (obj && typeof obj === 'object') wireContent = obj;
              } catch {
                // 保持原字符串
              }
              sendPlan.push({
                candidateID: d.candidateID,
                contentType,
                content: wireContent,
                humanAction,
                localKey,
              });
              return;
            }

            localItems.push({
              key: localKey,
              clientMsgID: localKey,
              mine: true,
              kind: 'text',
              text: edited,
              time: baseTs + i,
              status: 'sending',
            });
            sendPlan.push({
              candidateID: d.candidateID,
              contentType,
              content: edited,
              humanAction,
              localKey,
            });
          });
          if (localItems.length > 0) {
            for (const item of localItems) {
              const key = item.clientMsgID || item.key;
              outboxTrackPendingMessage(taskID, item, key);
              if (taskIDRef.current === taskID) {
                pendingSendKeysRef.current.push(key);
              }
            }
            // 先让乐观气泡入列再上行，避免 submit_result 早到抽空 pending / 错绑只留一条
            const applyOptimistic = () => {
              if (taskIDRef.current === taskID) {
                setMessages((prev) => [...prev, ...localItems]);
              }
            };
            if (Platform.OS === 'web') {
              try {
                const { flushSync } = require('react-dom') as typeof import('react-dom');
                flushSync(applyOptimistic);
              } catch {
                applyOptimistic();
                await new Promise<void>((resolve) => setTimeout(resolve, 0));
              }
            } else {
              applyOptimistic();
              await new Promise<void>((resolve) => setTimeout(resolve, 0));
            }
            if (taskIDRef.current === taskID) scrollToEnd();
            emitConversationProcessed({ taskID, imConversationID });
          }

          // 复审提交前先确保 OPEN；半开/断线会先拉起重连再发，避免 [IM] WebSocket is not open
          await chat.ensureConnected();
          for (const item of sendPlan) {
            await chat.sendMessage(taskID, item.content, item.contentType, {
              candidateID: item.candidateID,
              humanAction: item.humanAction,
              clientMsgID: item.localKey,
            });
          }
          // 列表里删掉的候选：drop，不发送
          await dropCandidates(dropped);
        } else if (mode === 'rewrite') {
          const text = (submitOpts?.rewriteContent ?? '').trim();
          const anchor = drafts.find((d) => d.candidateID) ?? drafts[0];
          const candidateID = anchor?.candidateID;
          if (!text || !candidateID) {
            appAlert('无法发送', '缺少候选 ID 或自定义内容为空');
            return;
          }
          const localKey = `local-adoption-rewrite-${Date.now()}`;
          appendOptimistic(taskID, localKey, {
            key: localKey,
            clientMsgID: localKey,
            mine: true,
            kind: 'text',
            text,
            time: Date.now(),
            status: 'sending',
          });
          emitConversationProcessed({ taskID, imConversationID });
          await chat.sendMessage(taskID, text, 101, {
            candidateID,
            humanAction: 'rewrite',
            clientMsgID: localKey,
          });
          // 自定义重写时，其余未用到的候选（含已删）一并 drop
          await dropCandidates([
            ...drafts.filter((d) => d.candidateID && d.candidateID !== candidateID),
            ...dropped,
          ]);
        } else {
          // 已处理：对保留 + 已删候选都发 drop
          await dropCandidates([...drafts, ...dropped]);
        }

        // 确定发送 / 已处理 / 自定义重写：按当前会话最后一条消息 ack（失败不阻断已提交的复审）
        const serverMsgID =
          lastServerMessageRef.current?.serverMsgID?.trim() ||
          getClaimedConversationsSnapshot().find((c) => c.id === taskID)?.lastMessage?.serverMsgID?.trim() ||
          '';
        if (serverMsgID) {
          try {
            await ackTaskMessage(taskID, serverMsgID);
          } catch (e) {
            console.warn('[Chat] ack_task_message 失败', {
              taskID,
              serverMsgID,
              mode,
              error: e instanceof Error ? e.message : e,
            });
          }
        } else {
          console.warn('[Chat] AI 复审后无法 ack_task_message：缺少 serverMsgID', { taskID, mode });
        }

        // 记下已复审的 adoptionID，并清除缓存中的 adoptionContext
        await markConversationAdoptionHandled({
          taskID,
          imConversationID,
          adoptionID: adoptionContext?.adoptionID,
        });
        setAdoptionContext(null);
        setAdoptionModalOpen(false);
        releaseAiReplyCooldown?.();
      } catch (e) {
        const raw = e instanceof Error ? e.message : '请稍后重试';
        const friendly =
          /not open|timed out|Network offline|manually closed/i.test(raw)
            ? '连接未就绪，请检查网络后重试'
            : raw;
        appAlert('复审提交失败', friendly);
      } finally {
        setAdoptionSubmitting(false);
      }
    })();
  }, [
    adoptionSubmitting,
    taskID,
    scrollToEnd,
    ctxRef,
    lastServerMessageRef,
    setMessages,
    pendingSendKeysRef,
    adoptionContext,
    setAdoptionContext,
    setAdoptionModalOpen,
    releaseAiReplyCooldown,
    appendOptimistic,
  ]);

  const handleDismissProactiveHint = useCallback(() => {
    const imConversationID = ctxRef.current.conversationID?.trim() || undefined;
    setProactiveActionHints(null);
    clearConversationProactiveActionHints({ taskID, imConversationID });
  }, [taskID, ctxRef, setProactiveActionHints]);

  const handleQuickSendProactiveHint = useCallback(
    (hint: ProactiveActionHint, index: number) => {
      if (isSupervisorView) return;
      const text = hint.actionContent?.trim();
      if (!text) return;

      const sendTaskID = taskID;
      const localKey = `local-${Date.now()}`;
      appendOptimistic(sendTaskID, localKey, {
        key: localKey,
        clientMsgID: localKey,
        mine: true,
        kind: 'text',
        text,
        time: Date.now(),
        status: 'sending',
      });
      emitConversationProcessed({ taskID: sendTaskID, imConversationID: ctxRef.current.conversationID });

      void (async () => {
        try {
          await getChatService().sendMessage(sendTaskID, text, 101, { clientMsgID: localKey });
          await dismissPendingAdoptionOnHumanSend();
        } catch {
          markLocalFailed(localKey, sendTaskID);
          return;
        }

        const imConversationID = ctxRef.current.conversationID?.trim() || undefined;
        setProactiveActionHints((prev) => {
          const items = pickValidProactiveActionHints(prev) ?? [];
          const next = items.filter((h, i) => i !== index && !isSameProactiveActionHint(h, hint));
          if (next.length === 0) {
            clearConversationProactiveActionHints({ taskID, imConversationID });
            return null;
          }
          updateConversationProactiveActionHints({ taskID, imConversationID, hints: next });
          return next;
        });
      })();
    },
    [
      taskID,
      isSupervisorView,
      ctxRef,
      setProactiveActionHints,
      markLocalFailed,
      appendOptimistic,
      dismissPendingAdoptionOnHumanSend,
    ],
  );

  return {
    sendingImage,
    sendingVoice,
    sendingFile,
    sendingVideo,
    adoptionSubmitting,
    handleSend,
    handlePickImage,
    handleTakePhoto,
    handlePickFile,
    handleSendPickedFile,
    handlePickVideo,
    handleSendVoice,
    handleSendSticker,
    handleAdoptionSubmit,
    handleDismissProactiveHint,
    handleQuickSendProactiveHint,
  };
}
