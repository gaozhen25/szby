import { StyleSheet, Text, View } from 'react-native';
import { VideoCameraOutlined } from '@/ui/antd-icons';

type ExpoVideoModule = typeof import('expo-video');

let expoVideo: ExpoVideoModule | null = null;
try {
  // 动态加载：未重编原生包时避免 import 阶段直接白屏
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  expoVideo = require('expo-video') as ExpoVideoModule;
} catch (e) {
  console.warn('[video-preview] expo-video 原生模块不可用，请重新编译安装 App', e);
}

export function VideoPreview({
  uri,
  unavailableHint = '当前安装包未包含视频预览模块，请重新编译安装 App 后再试。',
}: {
  uri: string;
  unavailableHint?: string;
}) {
  const player = expoVideo?.useVideoPlayer?.(uri || '', (videoPlayer) => {
    if (uri) {
      videoPlayer.loop = false;
      videoPlayer.play();
    }
  });

  if (!expoVideo?.VideoView || !player) {
    return (
      <View style={s.unavailableWrap}>
        <VideoCameraOutlined size={40} color="rgba(255,255,255,0.82)" />
        <Text style={s.unavailableText}>{unavailableHint}</Text>
      </View>
    );
  }

  const VideoView = expoVideo.VideoView;
  return <VideoView player={player} style={s.video} nativeControls contentFit="contain" />;
}

const s = StyleSheet.create({
  video: {
    width: '100%',
    height: '100%',
  },
  unavailableWrap: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 24,
    gap: 12,
    backgroundColor: '#000',
  },
  unavailableText: {
    color: '#FFF',
    fontSize: 14,
    lineHeight: 22,
    textAlign: 'center',
  },
});
