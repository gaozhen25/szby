// ============================================================
// 会话列表行（活跃 / 历史共用）
// ============================================================
import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';

import { CachedImage } from '@/components/UI/CachedImage';
import { useTheme } from '@/design/theme-context';
import { Tokens } from '@/design/tokens';
import {
  hasConversationAdoptionReview,
  hasConversationProactiveHint,
  type MockConversation,
} from '@/mock/data';
import { conversationPairLabel } from '@/features/conversations/conversation-actors';

const PROACTIVE_HINT_DOT = '#FACC15';
const ADOPTION_REVIEW_COLOR = '#0B6E4F';

/** FlatList 唯一 key：优先 imConversationID，兜底 taskID */
export function conversationRowKey(conv: MockConversation): string {
  return (conv.imConversationID?.trim() || conv.id || '').trim();
}

function ConversationAvatar({
  url,
  color,
  muted,
  fallbackText,
}: {
  url?: string;
  color: string;
  muted?: boolean;
  fallbackText?: string;
}) {
  const [failed, setFailed] = useState(false);
  const avatarUrl = url?.trim();
  const showImage = !!avatarUrl && !failed;
  const letter = (fallbackText ?? '').trim().charAt(0);

  return (
    <View
      style={[
        styles.avatar,
        { backgroundColor: color, overflow: 'hidden' },
        muted && { opacity: 0.45 },
      ]}
    >
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

function ConversationStatusDots({
  hasRedDot,
  hasProactiveHint,
  muted,
}: {
  hasRedDot: boolean;
  hasProactiveHint: boolean;
  muted: boolean;
}) {
  const theme = useTheme();
  if (muted) return null;

  const red = hasRedDot;
  const yellow = hasProactiveHint;
  if (!red && !yellow) return null;

  if (red && yellow) {
    return (
      <View style={styles.dotRow}>
        <View style={[styles.dotCircle, { backgroundColor: PROACTIVE_HINT_DOT }]} />
        <View
          style={[
            styles.dotCircle,
            styles.dotCircleOverlap,
            { backgroundColor: theme.danger },
          ]}
        />
      </View>
    );
  }

  return (
    <View
      style={[
        styles.dotCircle,
        { backgroundColor: red ? theme.danger : PROACTIVE_HINT_DOT },
      ]}
    />
  );
}

export function ConversationListItem({
  item,
  favorited,
  onPress,
}: {
  item: MockConversation;
  favorited?: boolean;
  onPress: () => void;
}) {
  const theme = useTheme();
  const muted = item.inactive;
  const avatarLetter =
    item.audiencePlatformNickname?.trim() || item.to?.trim() || '';
  const hasProactiveHint = hasConversationProactiveHint(item);
  const hasAdoptionReview = hasConversationAdoptionReview(item);

  return (
    <Pressable
      style={[
        styles.convItem,
        { borderBottomColor: theme.divider, backgroundColor: theme.bg },
      ]}
      onPress={onPress}
    >
      <View style={[styles.convItemInner, muted && styles.convItemInnerMuted]}>
        <View style={styles.avatarWrap}>
          <ConversationAvatar
            url={item.audiencePlatformFaceURL}
            color={item.avatarColor}
            muted={muted}
            fallbackText={avatarLetter}
          />
          {item.unread > 0 ? (
            <View style={[styles.badge, { backgroundColor: theme.danger }]}>
              <Text style={styles.badgeText}>{item.unread}</Text>
            </View>
          ) : null}
        </View>

        <View style={styles.convBody}>
          <View style={styles.convTitleRow}>
            <Text
              style={[styles.convTitle, { color: muted ? theme.placeholder : theme.text }]}
              numberOfLines={1}
              ellipsizeMode="middle"
            >
              {conversationPairLabel(item) || '会话'}
            </Text>
            {favorited && !muted ? (
              <Ionicons name="star" size={14} color="#F5A623" style={styles.favoriteStar} />
            ) : null}
          </View>
          <Text
            style={[styles.convPreview, { color: muted ? theme.placeholder : theme.textSubtle }]}
            numberOfLines={1}
          >
            {item.preview}
          </Text>
        </View>

        <View style={styles.convMeta}>
          <Text style={[styles.convTime, { color: muted ? theme.placeholder : theme.textSubtle }]}>
            {item.time}
          </Text>
          {!muted && hasAdoptionReview ? (
            <Text style={styles.adoptionReviewBadge}>AI复审</Text>
          ) : null}
          <ConversationStatusDots
            hasRedDot={!!item.hasRedDot}
            hasProactiveHint={hasProactiveHint}
            muted={!!muted}
          />
        </View>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  convItem: {
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  convItemInner: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: Tokens.spacing[4],
    paddingVertical: 12,
    gap: Tokens.spacing[3],
  },
  convItemInnerMuted: {
    opacity: 0.72,
  },
  avatarWrap: {
    position: 'relative',
  },
  avatar: {
    width: 48,
    height: 48,
    borderRadius: 24,
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarImage: {
    width: 48,
    height: 48,
  },
  avatarFallback: {
    ...StyleSheet.absoluteFillObject,
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarFallbackText: {
    color: '#FFF',
    fontSize: 18,
    fontWeight: '700',
  },
  badge: {
    position: 'absolute',
    top: -4,
    right: -4,
    minWidth: 18,
    height: 18,
    borderRadius: 9,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 4,
  },
  badgeText: {
    color: '#FFF',
    fontSize: 11,
    fontWeight: '700',
  },
  convBody: {
    flex: 1,
    minWidth: 0,
    marginRight: Tokens.spacing[2],
  },
  convTitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Tokens.spacing[2],
    marginBottom: 4,
  },
  convTitle: {
    flexShrink: 1,
    fontSize: 15,
    fontWeight: '600',
  },
  favoriteStar: {
    flexShrink: 0,
  },
  convPreview: {
    fontSize: 13,
  },
  convTime: {
    flexShrink: 0,
    fontSize: 12,
    alignSelf: 'flex-end',
    marginTop: 2,
  },
  adoptionReviewBadge: {
    fontSize: 11,
    fontWeight: '600',
    color: ADOPTION_REVIEW_COLOR,
    lineHeight: 14,
  },
  convMeta: {
    flexShrink: 0,
    alignItems: 'flex-end',
    minWidth: 24,
    gap: 6,
  },
  dotRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'flex-end',
  },
  dotCircle: {
    width: 16,
    height: 16,
    borderRadius: 8,
    borderWidth: 2,
    borderColor: '#fff',
  },
  dotCircleOverlap: {
    marginLeft: -Math.round(16 / 3),
    zIndex: 1,
  },
});
