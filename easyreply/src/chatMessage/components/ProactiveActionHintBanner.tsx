// ============================================================
// 定时主动触达提醒面板（紧凑悬浮条）
// ============================================================
import { useEffect, useRef, useState } from 'react';
import {
  Animated,
  Easing,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { BellOutlined, CheckOutlined, CloseOutlined, CopyOutlined, SendOutlined } from '@/ui/antd-icons';

import { useTheme } from '@/design/theme-context';
import { Tokens } from '@/design/tokens';
import type { ProactiveActionHint } from '@/core/im/types';
import {
  pickValidProactiveActionHints,
  proactiveActionHintKey,
} from '@/lib/proactive-action-hints';
import { copyText } from '@/lib/clipboard';

type Props = {
  visible: boolean;
  hints: ProactiveActionHint[] | null | undefined;
  canQuickSend?: boolean;
  onDismiss: () => void;
  onQuickSend?: (hint: ProactiveActionHint, index: number) => void;
  /** 有发送权限时，点击提醒文案填入下方输入框 */
  onFillDraft?: (text: string) => void;
};

const ENTER_MS = 260;
const EXIT_MS = 200;
const MAX_BODY_HEIGHT = 168;

function HintItem({
  item,
  index,
  total,
  multi,
  canQuickSend,
  onQuickSend,
  onFillDraft,
  theme,
}: {
  item: ProactiveActionHint;
  index: number;
  total: number;
  multi: boolean;
  canQuickSend: boolean;
  onQuickSend?: (hint: ProactiveActionHint, index: number) => void;
  onFillDraft?: (text: string) => void;
  theme: ReturnType<typeof useTheme>;
}) {
  const taskName = item.taskName?.trim();
  const content = item.actionContent.trim();
  const [copied, setCopied] = useState(false);
  /** 与「发送」同门禁：可人工发送时才允许点文案填入输入框 */
  const canFill = canQuickSend && !!onFillDraft;

  const handleCopy = async () => {
    const ok = await copyText(content);
    if (!ok) return;
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const handleFillDraft = (text: string) => {
    const value = text.trim();
    if (!canFill || !value) return;
    onFillDraft(value);
  };

  return (
    <View
      style={[
        styles.item,
        index < total - 1 && {
          borderBottomWidth: StyleSheet.hairlineWidth,
          borderBottomColor: theme.divider,
        },
      ]}
    >
      <View style={styles.itemMain}>
        {multi ? (
          <View style={[styles.indexDot, { backgroundColor: theme.primarySoft }]}>
            <Text style={[styles.indexText, { color: theme.primary }]}>{index + 1}</Text>
          </View>
        ) : null}

        <View style={styles.itemTextCol}>
          {taskName ? (
            canFill ? (
              <Pressable
                onPress={() => handleFillDraft(taskName)}
                style={({ pressed }) => pressed && { opacity: 0.7 }}
                accessibilityRole="button"
                accessibilityLabel="填入输入框"
              >
                <Text style={[styles.taskName, { color: theme.text }]} numberOfLines={1}>
                  {taskName}
                </Text>
              </Pressable>
            ) : (
              <Text style={[styles.taskName, { color: theme.text }]} numberOfLines={1}>
                {taskName}
              </Text>
            )
          ) : null}
          <View style={styles.contentRow}>
            {canFill && content ? (
              <Pressable
                onPress={() => handleFillDraft(content)}
                style={({ pressed }) => [
                  styles.fillableContent,
                  pressed && { opacity: 0.7 },
                ]}
                accessibilityRole="button"
                accessibilityLabel="填入输入框"
              >
                <Text
                  style={[styles.actionContent, { color: theme.textMuted }]}
                  numberOfLines={multi ? 2 : 3}
                >
                  {content}
                </Text>
              </Pressable>
            ) : (
              <Text
                style={[styles.actionContent, { color: theme.textMuted }]}
                numberOfLines={multi ? 2 : 3}
              >
                {content}
              </Text>
            )}
            <Pressable
              onPress={() => void handleCopy()}
              hitSlop={6}
              style={({ pressed }) => [
                styles.copyIconBtn,
                copied && { backgroundColor: theme.primarySoft },
                pressed && { opacity: 0.55 },
              ]}
              accessibilityRole="button"
              accessibilityLabel={copied ? '已复制' : '复制内容'}
            >
              {copied ? (
                <CheckOutlined size={12} color={theme.primary} />
              ) : (
                <CopyOutlined size={12} color={theme.textSubtle} />
              )}
            </Pressable>
          </View>
        </View>

        {canQuickSend && onQuickSend ? (
          <Pressable
            onPress={() => onQuickSend(item, index)}
            style={({ pressed }) => [
              styles.actionChip,
              styles.sendChip,
              { backgroundColor: theme.primary, opacity: pressed ? 0.85 : 1 },
            ]}
            accessibilityRole="button"
            accessibilityLabel={multi ? `发送第${index + 1}条` : '发送此消息'}
          >
            <SendOutlined size={10} color="#FFF" />
            <Text style={styles.sendChipText}>发送</Text>
          </Pressable>
        ) : null}
      </View>
    </View>
  );
}

export function ProactiveActionHintBanner({
  visible,
  hints,
  canQuickSend = true,
  onDismiss,
  onQuickSend,
  onFillDraft,
}: Props) {
  const theme = useTheme();
  const items = pickValidProactiveActionHints(hints) ?? [];
  const shouldShow = visible && items.length > 0;
  const multi = items.length > 1;

  const [mounted, setMounted] = useState(shouldShow);
  const opacity = useRef(new Animated.Value(0)).current;
  const translateY = useRef(new Animated.Value(-8)).current;
  const exitingRef = useRef(false);

  useEffect(() => {
    if (shouldShow) {
      exitingRef.current = false;
      setMounted(true);
      opacity.setValue(0);
      translateY.setValue(-8);
      Animated.parallel([
        Animated.timing(opacity, {
          toValue: 1,
          duration: ENTER_MS,
          easing: Easing.out(Easing.cubic),
          useNativeDriver: true,
        }),
        Animated.timing(translateY, {
          toValue: 0,
          duration: ENTER_MS,
          easing: Easing.out(Easing.cubic),
          useNativeDriver: true,
        }),
      ]).start();
      return;
    }

    if (!mounted || exitingRef.current) return;
    exitingRef.current = true;
    Animated.parallel([
      Animated.timing(opacity, {
        toValue: 0,
        duration: EXIT_MS,
        easing: Easing.in(Easing.cubic),
        useNativeDriver: true,
      }),
      Animated.timing(translateY, {
        toValue: -6,
        duration: EXIT_MS,
        easing: Easing.in(Easing.cubic),
        useNativeDriver: true,
      }),
    ]).start(({ finished }) => {
      if (finished) {
        setMounted(false);
        exitingRef.current = false;
      }
    });
  }, [shouldShow, mounted, opacity, translateY]);

  const runExit = (afterExit: () => void) => {
    if (exitingRef.current) return;
    exitingRef.current = true;
    Animated.parallel([
      Animated.timing(opacity, {
        toValue: 0,
        duration: EXIT_MS,
        easing: Easing.in(Easing.cubic),
        useNativeDriver: true,
      }),
      Animated.timing(translateY, {
        toValue: -6,
        duration: EXIT_MS,
        easing: Easing.in(Easing.cubic),
        useNativeDriver: true,
      }),
    ]).start(({ finished }) => {
      if (!finished) return;
      setMounted(false);
      exitingRef.current = false;
      afterExit();
    });
  };

  if (!mounted) return null;

  return (
    <Animated.View
      style={[styles.host, { opacity, transform: [{ translateY }] }]}
      pointerEvents="box-none"
    >
      <View
        style={[
          styles.card,
          { backgroundColor: theme.surface, borderColor: theme.border },
          Tokens.shadow.card,
        ]}
      >
        {/* 顶栏 */}
        <View style={styles.header}>
          <BellOutlined size={15} color={theme.warning} />
          <Text style={[styles.headerTitle, { color: theme.text }]}>新的消息提醒</Text>
          {multi ? (
            <View style={[styles.countPill, { backgroundColor: theme.warningSoft }]}>
              <Text style={[styles.countText, { color: theme.warning }]}>{items.length}</Text>
            </View>
          ) : null}
          <View style={styles.headerSpacer} />
          <Pressable
            onPress={() => runExit(onDismiss)}
            hitSlop={6}
            style={({ pressed }) => pressed && { opacity: 0.5 }}
            accessibilityRole="button"
            accessibilityLabel="关闭提醒"
          >
            <CloseOutlined size={18} color={theme.textSubtle} />
          </Pressable>
        </View>

        {/* 列表 */}
        <ScrollView
          style={styles.bodyScroll}
          contentContainerStyle={styles.bodyContent}
          nestedScrollEnabled
          showsVerticalScrollIndicator={multi}
        >
          {items.map((item, index) => (
            <HintItem
              key={proactiveActionHintKey(item, index)}
              item={item}
              index={index}
              total={items.length}
              multi={multi}
              canQuickSend={canQuickSend}
              onQuickSend={onQuickSend}
              onFillDraft={onFillDraft}
              theme={theme}
            />
          ))}
        </ScrollView>
      </View>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  host: {
    position: 'absolute',
    top: Tokens.spacing[2],
    left: Tokens.spacing[3],
    right: Tokens.spacing[3],
    zIndex: 20,
    elevation: 6,
  },
  card: {
    borderRadius: Tokens.radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    overflow: 'hidden',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: Tokens.spacing[3],
    paddingVertical: 8,
  },
  headerTitle: {
    fontSize: 13,
    fontWeight: '700',
  },
  countPill: {
    minWidth: 18,
    height: 18,
    borderRadius: 9,
    paddingHorizontal: 5,
    alignItems: 'center',
    justifyContent: 'center',
  },
  countText: {
    fontSize: 11,
    fontWeight: '700',
  },
  headerSpacer: {
    flex: 1,
  },
  bodyScroll: {
    maxHeight: MAX_BODY_HEIGHT,
  },
  bodyContent: {
    paddingHorizontal: Tokens.spacing[3],
    paddingBottom: Tokens.spacing[2],
  },
  item: {
    paddingVertical: 8,
  },
  itemMain: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 8,
  },
  indexDot: {
    width: 18,
    height: 18,
    borderRadius: 9,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 1,
  },
  indexText: {
    fontSize: 11,
    fontWeight: '700',
  },
  itemTextCol: {
    flex: 1,
    minWidth: 0,
    gap: 2,
  },
  taskName: {
    fontSize: 13,
    fontWeight: '600',
    lineHeight: 18,
  },
  actionContent: {
    flexShrink: 1,
    fontSize: 13,
    lineHeight: 18,
  },
  fillableContent: {
    flexShrink: 1,
    minWidth: 0,
  },
  contentRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
    columnGap: 4,
    rowGap: 2,
  },
  copyIconBtn: {
    padding: 1,
    borderRadius: 4,
    flexShrink: 0,
  },
  actionChip: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 2,
    paddingHorizontal: 6,
    paddingVertical: 3,
    borderRadius: 6,
    borderWidth: StyleSheet.hairlineWidth,
  },
  sendChip: {
    borderWidth: 0,
  },
  sendChipText: {
    color: '#FFF',
    fontSize: 10,
    fontWeight: '600',
  },
});
