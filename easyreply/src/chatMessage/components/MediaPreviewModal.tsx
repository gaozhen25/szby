import { useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { CloseOutlined, DownloadOutlined, ExportOutlined } from '@/ui/antd-icons';
import ImageViewer from 'react-native-image-zoom-viewer';
import { TransformComponent, TransformWrapper } from 'react-zoom-pan-pinch';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { InAppModal } from '@/components/UI/InAppModal';
import { appAlert } from '@/lib/app-alert';
import { resolveBottomInset } from '@/lib/safe-area-bottom';
import { VideoPreview } from '@/chatMessage/components/VideoPreview';
import { saveAttachment } from '@/chatMessage/message/save-attachment';
import { openChatFileAttachment } from '@/chatMessage/message/open-attachment';

export type MediaPreviewState =
  | { visible: false }
  | {
      visible: true;
      kind: 'image';
      uri: string;
      fileName?: string;
    }
  | {
      visible: true;
      kind: 'video';
      uri: string;
      fileName?: string;
    };

type Props = {
  state: MediaPreviewState;
  onClose: () => void;
};

function TopBar({
  title,
  onClose,
  onSave,
  onOpenExternal,
  saving,
  topInset,
}: {
  title: string;
  onClose: () => void;
  onSave: () => void;
  onOpenExternal: () => void;
  saving: boolean;
  topInset: number;
}) {
  return (
    <View style={[s.topBar, { paddingTop: topInset, height: 52 + topInset }]}>
      <Pressable onPress={onClose} hitSlop={10} style={s.topBtn} accessibilityLabel="关闭预览">
        <CloseOutlined size={22} color="#FFF" />
      </Pressable>
      <Text style={s.title} numberOfLines={1}>{title}</Text>
      <View style={s.topActions}>
        <Pressable onPress={onSave} hitSlop={10} style={s.topBtn} accessibilityLabel="保存">
          {saving ? <ActivityIndicator color="#FFF" size="small" /> : <DownloadOutlined size={20} color="#FFF" />}
        </Pressable>
        <Pressable onPress={onOpenExternal} hitSlop={10} style={s.topBtn} accessibilityLabel="其他应用打开">
          <ExportOutlined size={20} color="#FFF" />
        </Pressable>
      </View>
    </View>
  );
}

function NativeActions({
  onClose,
  onSave,
  onOpenExternal,
  saving,
  bottomInset,
  /** 额外上抬，避免挡住视频原生进度条 */
  lift = 0,
}: {
  onClose: () => void;
  onSave: () => void;
  onOpenExternal: () => void;
  saving: boolean;
  bottomInset: number;
  lift?: number;
}) {
  return (
    <View style={[s.nativeActions, { right: 12, bottom: Math.max(bottomInset, 12) + lift }]}>
      <Pressable onPress={onSave} hitSlop={10} style={s.nativeActionBtn} accessibilityLabel="保存">
        {saving ? (
          <ActivityIndicator color="#111827" size="small" />
        ) : (
          <DownloadOutlined size={20} color="#111827" />
        )}
      </Pressable>
      <Pressable onPress={onOpenExternal} hitSlop={10} style={s.nativeActionBtn} accessibilityLabel="其他应用打开">
        <ExportOutlined size={20} color="#111827" />
      </Pressable>
      <Pressable onPress={onClose} hitSlop={10} style={s.nativeActionBtn} accessibilityLabel="关闭预览">
        <CloseOutlined size={22} color="#111827" />
      </Pressable>
    </View>
  );
}

function WebImagePreview({ uri }: { uri: string }) {
  return (
    <TransformWrapper
      initialScale={1}
      minScale={1}
      maxScale={5}
      doubleClick={{ disabled: false, mode: 'zoomIn' }}
      wheel={{ step: 0.12 }}
      panning={{ velocityDisabled: true }}
      pinch={{ step: 5 }}
    >
      <TransformComponent wrapperStyle={s.webWrapper} contentStyle={s.webContent}>
        <img
          src={uri}
          style={s.webImg as unknown as Record<string, unknown>}
          draggable={false}
        />
      </TransformComponent>
    </TransformWrapper>
  );
}

export function MediaPreviewModal({ state, onClose }: Props) {
  const [saving, setSaving] = useState(false);
  const insets = useSafeAreaInsets();

  const title = state.visible ? state.fileName || '预览' : '';
  const inferredSaveName = useMemo(() => {
    if (!state.visible) return 'attachment';
    if (state.fileName && state.fileName.includes('.')) return state.fileName;
    if (state.kind === 'image') return 'image.jpg';
    return 'video.mp4';
  }, [state]);

  const handleSave = async () => {
    if (!state.visible) return;
    try {
      setSaving(true);
      await saveAttachment({
        url: state.uri,
        fileName: inferredSaveName,
      });
    } catch (e) {
      appAlert('保存失败', e instanceof Error ? e.message : '请稍后重试');
    } finally {
      setSaving(false);
    }
  };

  const handleOpenExternal = async () => {
    if (!state.visible) return;
    try {
      await openChatFileAttachment({
        url: state.uri,
        fileName: state.fileName || inferredSaveName,
      });
    } catch (e) {
      appAlert('打开失败', e instanceof Error ? e.message : '请稍后重试');
    }
  };

  if (!state.visible) return null;

  if (state.kind === 'image') {
    if (Platform.OS === 'web') {
      return (
        <InAppModal visible transparent animationType="fade" onRequestClose={onClose}>
          <View style={s.mask}>
            <View style={s.inner}>
              <TopBar
                title={title || '图片预览'}
                onClose={onClose}
                onSave={handleSave}
                onOpenExternal={handleOpenExternal}
                saving={saving}
                topInset={insets.top}
              />
              <WebImagePreview uri={state.uri} />
            </View>
          </View>
        </InAppModal>
      );
    }

    return (
      <InAppModal visible transparent animationType="fade" onRequestClose={onClose}>
        <View style={s.nativeMask}>
          <ImageViewer
            imageUrls={[{ url: state.uri }]}
            index={0}
            enableSwipeDown
            onCancel={onClose}
            onClick={() => onClose()}
            backgroundColor="rgba(0,0,0,0.92)"
            saveToLocalByLongPress={false}
          />
          <NativeActions
            onClose={onClose}
            onSave={handleSave}
            onOpenExternal={handleOpenExternal}
            saving={saving}
            bottomInset={insets.bottom}
          />
        </View>
      </InAppModal>
    );
  }

  return (
    <InAppModal visible transparent animationType="fade" onRequestClose={onClose}>
      <View style={s.mask}>
        <View style={s.inner}>
          {/* Android edge-to-edge：底部留出系统导航条高度，避免进度条信息被挡住 */}
          <View style={[s.videoWrap, { paddingBottom: resolveBottomInset(insets.bottom) }]}>
            <VideoPreview uri={state.uri} />
          </View>
          <NativeActions
            onClose={onClose}
            onSave={handleSave}
            onOpenExternal={handleOpenExternal}
            saving={saving}
            bottomInset={resolveBottomInset(insets.bottom)}
            lift={72}
          />
        </View>
      </View>
    </InAppModal>
  );
}

const s = StyleSheet.create({
  mask: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(0,0,0,0.92)',
  },
  nativeMask: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(0,0,0,0.92)',
  },
  overlayTop: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
  },
  inner: {
    width: '100%',
    height: '100%',
    maxWidth: undefined,
    maxHeight: undefined,
    borderRadius: 0,
    overflow: 'hidden',
    backgroundColor: '#111',
  },
  topBar: {
    height: 52,
    paddingHorizontal: 10,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: 'rgba(0,0,0,0.35)',
  },
  title: {
    flex: 1,
    marginHorizontal: 12,
    color: '#FFF',
    fontSize: 14,
    fontWeight: '600',
  },
  topActions: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  topBtn: {
    width: 40,
    height: 40,
    alignItems: 'center',
    justifyContent: 'center',
  },
  nativeActions: {
    position: 'absolute',
    flexDirection: 'row',
    gap: 12,
    alignItems: 'center',
  },
  nativeActionBtn: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#D1D5DB',
  },
  webWrapper: {
    width: '100%',
    height: '100%',
    backgroundColor: 'transparent',
  },
  webContent: {
    width: '100%',
    height: '100%',
    justifyContent: 'center',
    alignItems: 'center',
  },
  webImg: {
    maxWidth: '100%',
    maxHeight: '100%',
    objectFit: 'contain',
    userSelect: 'none',
  },
  videoWrap: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#000',
  },
});
