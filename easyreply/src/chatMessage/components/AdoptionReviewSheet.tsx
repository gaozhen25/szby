// ============================================================
// AI 托管候选消息人工复审
// - 输入框上方遮罩提示
// - 弹窗：编辑候选内容后确定，经 send_message(candidateID + humanAction) 提交
// - 右侧「自定义」：切换为人工重写输入框，确定时 humanAction=rewrite
// - contentType=102 图片/表情包：解析 JSON 展示缩略图，提交仍用原始 content
// - 确定 / 已处理后额外调用 actions/ack_task_message
// ============================================================
import { useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { Image as ExpoImage } from 'expo-image';
import { Ionicons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { InAppModal } from '@/components/UI/InAppModal';
import { useTheme } from '@/design/theme-context';
import { Tokens } from '@/design/tokens';
import type { AdoptionCandidate, AdoptionContext } from '@/core/im';
import {
  looksLikeImageMessageContent,
  parseImageMessageContent,
} from '@/core/im/image-message';
import { FullScreenImageViewer } from '@/chatMessage/components/FullScreenImageViewer';

export type AdoptionDraftItem = {
  candidateID: string;
  index: number;
  content: string;
  contentType: number;
  originalContent: string;
};

export type AdoptionSubmitMode = 'confirm' | 'drop' | 'rewrite';

function resolveCandidateContentType(c: AdoptionCandidate): number {
  if (c.contentType === 102) return 102;
  const raw = c.editedContent || c.finalContent || c.originalContent || '';
  if (looksLikeImageMessageContent(raw)) return 102;
  return c.contentType || 101;
}

function isImageDraft(d: Pick<AdoptionDraftItem, 'contentType' | 'content'>): boolean {
  return d.contentType === 102 || looksLikeImageMessageContent(d.content);
}

function toDrafts(candidates: AdoptionCandidate[]): AdoptionDraftItem[] {
  return [...candidates]
    .sort((a, b) => (a.index ?? 0) - (b.index ?? 0))
    .map((c) => {
      const original = c.originalContent || '';
      const content = (c.editedContent || c.finalContent || original || '').length
        ? (c.editedContent || c.finalContent || original)
        : original;
      return {
        candidateID: c.candidateID,
        index: c.index ?? 0,
        content,
        contentType: resolveCandidateContentType(c),
        originalContent: original,
      };
    });
}

const ADOPTION_THUMB_SIZE = 70;

function AdoptionImagePreview({ content }: { content: string }) {
  const theme = useTheme();
  const parsed = useMemo(() => parseImageMessageContent(content), [content]);
  const [viewerUri, setViewerUri] = useState<string | null>(null);

  if (!parsed?.imageUrl) {
    return (
      <Text style={[styles.imageFallback, { color: theme.textMuted }]}>[图片]</Text>
    );
  }

  return (
    <View style={styles.imageWrap}>
      <Pressable
        onPress={() => setViewerUri(parsed.imageUrl)}
        accessibilityRole="imagebutton"
        accessibilityLabel="查看大图"
        style={({ pressed }) => [pressed && { opacity: 0.85 }]}
      >
        <ExpoImage
          source={{ uri: parsed.imageUrl }}
          style={styles.imageThumb}
          contentFit="cover"
          recyclingKey={parsed.imageUrl}
        />
      </Pressable>
      <FullScreenImageViewer
        visible={!!viewerUri}
        uri={viewerUri || ''}
        onClose={() => setViewerUri(null)}
      />
    </View>
  );
}

type BannerProps = {
  visible: boolean;
  onPress: () => void;
};

/** 盖在输入框上方的复审提示条 */
export function AdoptionReviewBanner({ visible, onPress }: BannerProps) {
  const theme = useTheme();
  if (!visible) return null;

  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [
        styles.banner,
        {
          backgroundColor: theme.warningSoft,
          borderTopColor: theme.warning + '40',
        },
        pressed && { opacity: 0.85 },
      ]}
      accessibilityRole="button"
      accessibilityLabel="有AI消息需要复审"
    >
      <Text style={[styles.bannerTitle, { color: theme.warning, flex: 1 }]}>有AI消息需要复审</Text>
      <Text style={[styles.bannerAction, { color: theme.primary }]}>去处理</Text>
    </Pressable>
  );
}

type ModalProps = {
  visible: boolean;
  adoption: AdoptionContext | null;
  submitting?: boolean;
  onClose: () => void;
  /**
   * confirm：候选 approve_original/edit；opts.droppedDrafts 对已删项发 drop
   * drop：已处理 humanAction=drop，省略 content（含已从列表删除的项）
   * rewrite：自定义重写，humanAction=rewrite
   */
  onSubmit: (
    drafts: AdoptionDraftItem[],
    mode: AdoptionSubmitMode,
    opts?: { rewriteContent?: string; droppedDrafts?: AdoptionDraftItem[] },
  ) => void;
};

export function AdoptionReviewModal({
  visible,
  adoption,
  submitting = false,
  onClose,
  onSubmit,
}: ModalProps) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const candidates = adoption?.candidates ?? [];
  const [drafts, setDrafts] = useState<AdoptionDraftItem[]>(() => toDrafts(candidates));
  const [removedDrafts, setRemovedDrafts] = useState<AdoptionDraftItem[]>([]);
  const [customMode, setCustomMode] = useState(false);
  const [rewriteContent, setRewriteContent] = useState('');

  useEffect(() => {
    if (visible) {
      setDrafts(toDrafts(adoption?.candidates ?? []));
      setRemovedDrafts([]);
      setCustomMode(false);
      setRewriteContent('');
    }
  }, [visible, adoption]);

  const canSubmit = useMemo(() => {
    if (customMode) return rewriteContent.trim().length > 0;
    return drafts.length > 0 && drafts.every((d) => d.content.trim().length > 0);
  }, [customMode, rewriteContent, drafts]);

  const canRemove = drafts.length > 1 && !submitting;

  const updateContent = (candidateID: string, content: string) => {
    setDrafts((prev) => prev.map((d) => (d.candidateID === candidateID ? { ...d, content } : d)));
  };

  const removeDraft = (candidateID: string) => {
    if (!canRemove) return;
    const item = drafts.find((d) => d.candidateID === candidateID);
    if (!item) return;
    setRemovedDrafts((prev) => [...prev, item]);
    setDrafts((prev) => prev.filter((d) => d.candidateID !== candidateID));
  };

  const toggleCustomMode = () => {
    if (submitting) return;
    if (customMode) {
      setCustomMode(false);
      setRewriteContent('');
    } else {
      setCustomMode(true);
    }
  };

  const handleConfirm = () => {
    if (customMode) {
      onSubmit(drafts, 'rewrite', {
        rewriteContent: rewriteContent.trim(),
        droppedDrafts: removedDrafts,
      });
      return;
    }
    onSubmit(drafts, 'confirm', { droppedDrafts: removedDrafts });
  };

  const handleDrop = () => {
    onSubmit(drafts, 'drop', { droppedDrafts: removedDrafts });
  };

  return (
    <InAppModal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <View style={styles.mask}>
        <View
          style={[
            styles.card,
            {
              backgroundColor: theme.surface,
              paddingBottom: Math.max(insets.bottom, 16),
            },
          ]}
        >
          <View style={styles.titleRow}>
            <Text style={[styles.title, { color: theme.text }]}>AI消息复审</Text>
            <Pressable
              onPress={toggleCustomMode}
              disabled={submitting}
              hitSlop={8}
              style={({ pressed }) => [pressed && { opacity: 0.7 }]}
              accessibilityRole="button"
              accessibilityLabel={customMode ? '取消自定义' : '自定义'}
            >
              <Text style={[styles.customToggle, { color: theme.primary }]}>
                {customMode ? '取消自定义' : '自定义'}
              </Text>
            </Pressable>
          </View>

          {customMode ? (
            <View
              style={[
                styles.item,
                styles.customBox,
                { borderColor: theme.border, backgroundColor: theme.surface2 },
              ]}
            >
              <Text style={[styles.itemLabel, { color: theme.textMuted }]}>自定义消息</Text>
              <TextInput
                style={[styles.itemInput, styles.customInput, { color: theme.text, borderColor: theme.border }]}
                value={rewriteContent}
                onChangeText={setRewriteContent}
                multiline
                editable={!submitting}
                autoFocus
                placeholder="输入要发送的消息内容"
                placeholderTextColor={theme.placeholder}
              />
            </View>
          ) : (
            <ScrollView style={styles.list} keyboardShouldPersistTaps="handled">
              {drafts.map((item, i) => {
                const image = isImageDraft(item);
                return (
                  <View
                    key={item.candidateID}
                    style={[styles.item, { borderColor: theme.border, backgroundColor: theme.surface2 }]}
                  >
                    <View style={styles.itemHeader}>
                      <Text style={[styles.itemLabel, { color: theme.textMuted, flex: 1 }]}>
                        候选 {i + 1}
                        {image ? ' · 图片 · 点击放大' : ''}
                      </Text>
                      <Pressable
                        onPress={() => removeDraft(item.candidateID)}
                        disabled={!canRemove}
                        hitSlop={8}
                        accessibilityRole="button"
                        accessibilityLabel="删除该候选"
                        style={({ pressed }) => [
                          styles.removeBtn,
                          !canRemove && { opacity: 0.35 },
                          pressed && canRemove && { opacity: 0.7 },
                        ]}
                      >
                        <Ionicons
                          name="trash-outline"
                          size={18}
                          color={canRemove ? theme.danger : theme.placeholder}
                        />
                      </Pressable>
                    </View>
                    {image ? (
                      <AdoptionImagePreview content={item.content || item.originalContent} />
                    ) : (
                      <TextInput
                        style={[styles.itemInput, { color: theme.text, borderColor: theme.border }]}
                        value={item.content}
                        onChangeText={(t) => updateContent(item.candidateID, t)}
                        multiline
                        editable={!submitting}
                        placeholder="待复审内容"
                        placeholderTextColor={theme.placeholder}
                      />
                    )}
                  </View>
                );
              })}
            </ScrollView>
          )}

          <View style={styles.actionsRow}>
            <Pressable
              style={({ pressed }) => [
                styles.btn,
                styles.btnHalf,
                { backgroundColor: theme.surface2 },
                pressed && { opacity: 0.75 },
              ]}
              disabled={submitting}
              onPress={onClose}
            >
              <Text style={[styles.btnText, { color: theme.textMuted }]}>取消</Text>
            </Pressable>
            <Pressable
              style={({ pressed }) => [
                styles.btn,
                styles.btnHalf,
                { backgroundColor: theme.warningSoft },
                (submitting || !drafts.length) && { opacity: 0.5 },
                pressed && { opacity: 0.75 },
              ]}
              disabled={submitting || !drafts.length}
              onPress={handleDrop}
            >
              <Text style={[styles.btnText, { color: theme.warning }]}>已处理</Text>
            </Pressable>
          </View>

          <View style={styles.actionsRow}>
            <Pressable
              style={({ pressed }) => [
                styles.btn,
                { flex: 1, backgroundColor: theme.primary },
                (submitting || !canSubmit) && { opacity: 0.5 },
                pressed && { opacity: 0.75 },
              ]}
              disabled={submitting || !canSubmit}
              onPress={handleConfirm}
            >
              {submitting ? (
                <ActivityIndicator size="small" color="#FFF" />
              ) : (
                <Text style={[styles.btnText, { color: '#FFF' }]}>确定</Text>
              )}
            </Pressable>
          </View>
        </View>
      </View>
    </InAppModal>
  );
}

const styles = StyleSheet.create({
  banner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  bannerTitle: {
    fontSize: 13,
    fontWeight: '700',
    flexShrink: 0,
  },
  bannerAction: {
    fontSize: 13,
    fontWeight: '600',
    flexShrink: 0,
  },
  mask: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(0,0,0,0.45)',
    justifyContent: 'flex-end',
  },
  card: {
    borderTopLeftRadius: 16,
    borderTopRightRadius: 16,
    paddingHorizontal: 16,
    paddingTop: 16,
    maxHeight: '82%',
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
  },
  title: {
    fontSize: 17,
    fontWeight: '700',
    flexShrink: 1,
  },
  customToggle: {
    fontSize: 14,
    fontWeight: '600',
    flexShrink: 0,
  },
  list: {
    marginTop: 12,
    marginBottom: 8,
  },
  customBox: {
    marginTop: 12,
    marginBottom: 8,
  },
  item: {
    borderRadius: 12,
    borderWidth: StyleSheet.hairlineWidth,
    padding: 12,
    marginBottom: 10,
  },
  itemHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 6,
  },
  itemLabel: {
    fontSize: 12,
    fontWeight: '600',
  },
  removeBtn: {
    padding: 2,
    flexShrink: 0,
  },
  itemInput: {
    minHeight: 64,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: 10,
    padding: 10,
    fontSize: 15,
    textAlignVertical: 'top',
  },
  customInput: {
    minHeight: 100,
  },
  imageWrap: {
    alignItems: 'flex-start',
    gap: 6,
  },
  imageThumb: {
    width: ADOPTION_THUMB_SIZE,
    height: ADOPTION_THUMB_SIZE,
    borderRadius: 8,
  },
  imageFallback: {
    fontSize: 14,
    paddingVertical: 8,
  },
  actionsRow: {
    flexDirection: 'row',
    gap: Tokens.spacing[3],
    marginTop: 8,
  },
  btn: {
    height: 44,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  btnHalf: {
    flex: 1,
  },
  btnText: {
    fontSize: 15,
    fontWeight: '600',
  },
});
