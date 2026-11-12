// ============================================================
// 应用内新消息横幅
// - Web 桌面：右上角 DOM 卡片（避免 RN 被全屏 overlay 纵向撑开）
// - 原生 / Web 手机端：状态栏下方居中宽卡片（与 App 一致）
// ============================================================
import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { createPortal } from 'react-dom';
import {
  Animated,
  Easing,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { router, type Href } from 'expo-router';

import { CachedImage } from '@/chatMessage/components/CachedImage';
import { EmojiText } from '@/chatMessage/components/EmojiText';
import { useTheme } from '@/design/theme-context';
import { Tokens } from '@/design/tokens';
import {
  dismissIncomingBanner,
  subscribeIncomingBanner,
  type IncomingBannerPayload,
} from '@/core/push/incoming-banner';
import { useIsDesktopWeb } from '@/lib/web-desktop';

const SLIDE_MS = 220;
const AVATAR_NATIVE = 36;
/** 横幅左右留白（越小越宽） */
const BANNER_SIDE_INSET = Tokens.spacing[3];

function openChatFromPayload(payload: IncomingBannerPayload): void {
  const id = payload.taskID?.trim();
  dismissIncomingBanner();
  if (!id) {
    router.push('/(tabs)/chat' as Href);
    return;
  }
  router.push({ pathname: '/chat/[id]', params: { id } } as unknown as Href);
}

/** Web 桌面：右上角窄通知条 */
function WebDesktopIncomingBannerCard({ payload }: { payload: IncomingBannerPayload }) {
  const [avatarFailed, setAvatarFailed] = useState(false);
  const letter = payload.title.trim().charAt(0) || '新';
  const showImage = !!payload.avatarUrl && !avatarFailed;

  const wrap: CSSProperties = {
    position: 'fixed',
    top: 16,
    right: 20,
    zIndex: 100010,
    pointerEvents: 'none',
  };

  const card: CSSProperties = {
    pointerEvents: 'auto',
    display: 'flex',
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    boxSizing: 'border-box',
    margin: 0,
    padding: '10px 14px',
    height: 'fit-content',
    width: 300,
    // maxWidth: 200,
    // minWidth: 200,
    borderRadius: 20,
    border: '1px solid rgba(26, 21, 16, 0.08)',
    background: Tokens.color.surface,
    boxShadow: '0 6px 20px rgba(26, 21, 16, 0.12)',
    cursor: 'pointer',
    fontFamily: 'inherit',
    textAlign: 'left',
    appearance: 'none',
    lineHeight: 1.2,
    minHeight: 'unset',
  };

  const avatar: CSSProperties = {
    width: 36,
    height: 36,
    borderRadius: 18,
    overflow: 'hidden',
    flexShrink: 0,
    background: Tokens.color.primary,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  };

  const body: CSSProperties = {
    display: 'flex',
    flexDirection: 'column',
    justifyContent: 'center',
    gap: 2,
    minWidth: 0,
    maxWidth: 126,
  };

  const title: CSSProperties = {
    margin: 0,
    padding: 0,
    fontSize: 15,
    lineHeight: '20px',
    fontWeight: 700,
    color: Tokens.color.text,
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  };

  const preview: CSSProperties = {
    margin: 0,
    padding: 0,
    fontSize: 13,
    lineHeight: '18px',
    fontWeight: 400,
    color: Tokens.color.textMuted,
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  };

  return createPortal(
    <div style={wrap}>
      <button
        type="button"
        style={card}
        onClick={() => openChatFromPayload(payload)}
        aria-label={`${payload.title}发来新消息`}
      >
        <span style={avatar}>
          {showImage ? (
            <img
              src={payload.avatarUrl}
              alt=""
              width={36}
              height={36}
              style={{ width: 36, height: 36, objectFit: 'cover', display: 'block' }}
              onError={() => setAvatarFailed(true)}
            />
          ) : (
            <span
              style={{
                color: '#FFF',
                fontSize: 14,
                fontWeight: 700,
                lineHeight: '36px',
              }}
            >
              {letter}
            </span>
          )}
        </span>
        <span style={body}>
          <span style={title}>{payload.title}</span>
          <span style={preview}>{payload.body}</span>
        </span>
      </button>
    </div>,
    document.body,
  );
}

function NativeIncomingBannerCard({ payload }: { payload: IncomingBannerPayload }) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const { width: windowWidth } = useWindowDimensions();
  const [avatarFailed, setAvatarFailed] = useState(false);
  const slide = useRef(new Animated.Value(0)).current;
  const bannerWidth = windowWidth - BANNER_SIDE_INSET * 2;

  useEffect(() => {
    slide.setValue(0);
    Animated.timing(slide, {
      toValue: 1,
      duration: SLIDE_MS,
      easing: Easing.out(Easing.cubic),
      useNativeDriver: true,
    }).start();
  }, [payload.id, slide]);

  const letter = payload.title.trim().charAt(0);
  const showImage = !!payload.avatarUrl && !avatarFailed;
  const translateY = slide.interpolate({
    inputRange: [0, 1],
    outputRange: [-16, 0],
  });

  return (
    <View
      style={[styles.host, { paddingTop: insets.top + Tokens.spacing[2] }]}
      pointerEvents="box-none"
    >
      <Animated.View
        style={[
          styles.card,
          {
            width: bannerWidth,
            backgroundColor: Tokens.color.surface,
            borderColor: 'rgba(26, 21, 16, 0.08)',
            opacity: slide,
            transform: [{ translateY }],
          },
        ]}
      >
        <Pressable
          onPress={() => openChatFromPayload(payload)}
          style={({ pressed }) => [styles.press, pressed && { opacity: 0.9 }]}
          accessibilityRole="button"
          accessibilityLabel={`${payload.title}发来新消息`}
        >
          <View style={[styles.avatar, { backgroundColor: theme.primary }]}>
            {showImage ? (
              <CachedImage
                source={{ uri: payload.avatarUrl }}
                style={styles.avatarImage}
                contentFit="cover"
                onError={() => setAvatarFailed(true)}
              />
            ) : (
              <Text style={styles.avatarLetter}>{letter || '新'}</Text>
            )}
          </View>
          <View style={styles.body}>
            <Text style={[styles.title, { color: Tokens.color.text }]} numberOfLines={1}>
              {payload.title}
            </Text>
            <EmojiText
              text={payload.body}
              color={Tokens.color.textMuted}
              textStyle={styles.preview}
              variant="preview"
            />
          </View>
        </Pressable>
      </Animated.View>
    </View>
  );
}

export function IncomingBannerHost() {
  const [payload, setPayload] = useState<IncomingBannerPayload | null>(null);
  const isDesktopWeb = useIsDesktopWeb();

  useEffect(() => {
    return subscribeIncomingBanner((next) => {
      setPayload(next);
    });
  }, []);

  if (!payload) return null;

  if (Platform.OS === 'web' && isDesktopWeb && typeof document !== 'undefined') {
    return <WebDesktopIncomingBannerCard payload={payload} />;
  }
  return <NativeIncomingBannerCard payload={payload} />;
}

const styles = StyleSheet.create({
  host: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    zIndex: 100010,
    alignItems: 'center',
  },
  card: {
    borderRadius: 18,
    borderWidth: StyleSheet.hairlineWidth,
    overflow: 'hidden',
    ...Platform.select({
      ios: {
        shadowColor: '#1A1510',
        shadowOpacity: 0.12,
        shadowRadius: 16,
        shadowOffset: { width: 0, height: 6 },
      },
      android: {
        elevation: 5,
      },
      web: {
        boxShadow: '0 6px 20px rgba(26, 21, 16, 0.12)',
      },
      default: {
        elevation: 5,
      },
    }),
  },
  press: {
    flexDirection: 'row',
    alignItems: 'center',
    width: '100%',
    paddingVertical: 10,
    paddingHorizontal: 12,
    gap: 10,
  },
  avatar: {
    width: AVATAR_NATIVE,
    height: AVATAR_NATIVE,
    borderRadius: AVATAR_NATIVE / 2,
    overflow: 'hidden',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },
  avatarImage: {
    width: AVATAR_NATIVE,
    height: AVATAR_NATIVE,
  },
  avatarLetter: {
    color: '#FFF',
    fontSize: 14,
    fontWeight: '700',
  },
  body: {
    flex: 1,
    minWidth: 0,
    justifyContent: 'center',
  },
  title: {
    fontSize: 15,
    lineHeight: 20,
    fontWeight: '700',
  },
  preview: {
    marginTop: 1,
    fontSize: 13,
    lineHeight: 18,
  },
});
