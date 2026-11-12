import { Modal, Platform, Pressable, StyleSheet, Text, View } from 'react-native';
import { CloseOutlined } from '@/ui/antd-icons';
import ImageViewer from 'react-native-image-zoom-viewer';
import { TransformComponent, TransformWrapper } from 'react-zoom-pan-pinch';

type Props = {
  visible: boolean;
  uri: string;
  onClose: () => void;
};

export function FullScreenImageViewer({ visible, uri, onClose }: Props) {
  if (!visible) return null;

  if (Platform.OS === 'web') {
    return (
      <Modal visible transparent animationType="fade" onRequestClose={onClose}>
        <Pressable style={s.webMask} onPress={onClose}>
          <Pressable style={s.webInner} onPress={() => {}}>
            <View style={s.webTopBar}>
              <Pressable onPress={onClose} hitSlop={10} style={s.closeBtn} accessibilityLabel="关闭图片预览">
                <CloseOutlined size={22} color="#FFF" />
              </Pressable>
              <Text style={s.webHint}>双击缩放 / 滚轮缩放 / 拖拽移动</Text>
            </View>
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
                {/* web 平台使用原生 img（非 Next.js 环境，无需 next/no-img-element 规则） */}
                <img
                  src={uri}
                  style={{
                    ...(s.webImg as any),
                    WebkitUserDrag: 'none',
                  }}
                />
              </TransformComponent>
            </TransformWrapper>
          </Pressable>
        </Pressable>
      </Modal>
    );
  }

  return (
    <Modal visible transparent animationType="fade" onRequestClose={onClose}>
      <ImageViewer
        imageUrls={[{ url: uri }]}
        index={0}
        enableSwipeDown
        onCancel={onClose}
        onClick={() => onClose()}
        backgroundColor="rgba(0,0,0,0.92)"
        saveToLocalByLongPress={false}
      />
    </Modal>
  );
}

const s = StyleSheet.create({
  webMask: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.92)',
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 24,
  },
  webInner: {
    width: '100%',
    maxWidth: 980,
    height: '100%',
    maxHeight: 720,
    borderRadius: 14,
    overflow: 'hidden',
  },
  webTopBar: {
    height: 48,
    paddingHorizontal: 10,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: 'rgba(0,0,0,0.28)',
  },
  closeBtn: { width: 40, height: 40, justifyContent: 'center', alignItems: 'center' },
  webHint: { color: 'rgba(255,255,255,0.75)', fontSize: 12 },
  webWrapper: { width: '100%', height: '100%', backgroundColor: 'transparent' },
  webContent: { width: '100%', height: '100%', justifyContent: 'center', alignItems: 'center' },
  webImg: {
    maxWidth: '100%',
    maxHeight: '100%',
    objectFit: 'contain',
    userSelect: 'none',
  },
});
