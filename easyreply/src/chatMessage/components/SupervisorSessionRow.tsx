// ============================================================
// 主管查看标注员会话行（无最新消息预览）
// ============================================================
import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { CachedImage } from '@/chatMessage/components/CachedImage';
import { useTheme } from '@/design/theme-context';
import { Tokens } from '@/design/tokens';
import type { TaskSessionRow } from '@/lib/task-session-list';
import type { ChatPlatform } from '@/mock/data';

const PLATFORM_STYLE: Record<ChatPlatform, { bg: string; text: string }> = {
  微信: { bg: '#E6F6EC', text: '#15803D' },
  抖音: { bg: '#FFE8EC', text: '#C41E3A' },
};

function PlatformTag({ platform }: { platform: ChatPlatform }) {
  const style = PLATFORM_STYLE[platform];
  return (
    <View style={[styles.platformTag, { backgroundColor: style.bg }]}>
      <Text style={[styles.platformText, { color: style.text }]}>{platform}</Text>
    </View>
  );
}

type Props = {
  item: TaskSessionRow;
  onPress: (taskId: string) => void;
};

function SessionAvatar({
  url,
  color,
  fallbackText,
}: {
  url?: string;
  color: string;
  /** 无头像图时展示的文字（取 audiencePlatformNickname 首字） */
  fallbackText?: string;
}) {
  const [failed, setFailed] = useState(false);
  const avatarUrl = url?.trim();
  const showImage = !!avatarUrl && !failed;
  const letter = (fallbackText ?? '').trim().charAt(0);

  return (
    <View style={[styles.avatar, { backgroundColor: color, overflow: 'hidden' }]}>
      {showImage ? (
        <CachedImage
          source={{ uri: avatarUrl }}
          style={styles.avatarImage}
          contentFit="cover"
          onError={() => setFailed(true)}
        />
      ) : letter ? (
        <View style={styles.avatarFallback}>
          <Text style={styles.avatarFallbackText}>{letter}</Text>
        </View>
      ) : null}
    </View>
  );
}

export function SupervisorSessionRow({ item, onPress }: Props) {
  const theme = useTheme();
  const avatarLetter =
    item.audiencePlatformNickname?.trim() || item.to?.trim() || '';

  return (
    <Pressable
      style={[styles.row, { borderBottomColor: theme.divider }]}
      onPress={() => onPress(item.id)}
    >
      <SessionAvatar
        url={item.audiencePlatformFaceURL}
        color={item.avatarColor}
        fallbackText={avatarLetter}
      />
      <View style={styles.body}>
        <View style={styles.titleRow}>
          <Text
            style={[styles.title, { color: theme.text }]}
            numberOfLines={1}
            ellipsizeMode="middle"
          >
            {item.from} → {item.to}
          </Text>
          {/* <PlatformTag platform={item.platform} /> */}
        </View>
      </View>
      {item.time ? (
        <Text style={[styles.time, { color: theme.textSubtle }]}>{item.time}</Text>
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: Tokens.spacing[4],
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  avatar: {
    width: 48,
    height: 48,
    borderRadius: 24,
    marginRight: Tokens.spacing[3],
  },
  avatarImage: {
    width: '100%',
    height: '100%',
  },
  avatarFallback: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarFallbackText: {
    color: '#FFF',
    fontSize: 18,
    fontWeight: '600',
  },
  body: {
    flex: 1,
    marginRight: Tokens.spacing[2],
    minWidth: 0,
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Tokens.spacing[2],
  },
  title: {
    fontSize: 16,
    fontWeight: '600',
    flex: 1,
    minWidth: 0,
    flexShrink: 1,
  },
  platformTag: {
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: Tokens.radius.sm,
  },
  platformText: {
    fontSize: 11,
    fontWeight: '600',
  },
  time: {
    fontSize: 12,
    alignSelf: 'flex-start',
    marginTop: 2,
  },
});
