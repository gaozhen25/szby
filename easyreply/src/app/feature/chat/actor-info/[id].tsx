// ============================================================
// 对方资料页 — 聊天页点击对方头像进入，可修改备注
// ============================================================
import { useCallback, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Image,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { router, useLocalSearchParams } from 'expo-router';

import { CustomNavBar } from '@/components/UI/CustomNavBar';
import { ScreenCanvas } from '@/components/UI/ScreenCanvas';
import { useTheme } from '@/design/theme-context';
import { Tokens } from '@/design/tokens';
import { EditOutlined } from '@/ui/antd-icons';
import { updateAudiencePlatformRemark } from '@/api/actors';
import { appAlert } from '@/lib/app-alert';
import { resolveAudienceApiPlatform } from '@/core/im';
import { ensureClaimedConversationsHydrated, getClaimedConversationsSnapshot } from '@/lib/claimed-conversations-store';

function platformLabel(platform: string): string {
  const p = platform.trim().toLowerCase();
  if (p === 'wecom') return '企业微信';
  if (p === 'wechat' || p === 'weixin') return '微信';
  if (p === 'douyin') return '抖音';
  if (p === '微信' || p === '抖音') return p;
  return platform.trim() || '未知平台';
}

function AudienceAvatar({
  url,
  name,
}: {
  url?: string;
  name: string;
}) {
  const theme = useTheme();
  const [failed, setFailed] = useState(false);
  const avatarUrl = url?.trim();
  const showImage = !!avatarUrl && !failed;
  const letter = name.trim().charAt(0) || '用';

  return (
    <View style={[styles.avatar, { backgroundColor: theme.primary, overflow: 'hidden' }]}>
      {showImage ? (
        <Image
          source={{ uri: avatarUrl }}
          style={styles.avatarImage}
          onError={() => setFailed(true)}
        />
      ) : (
        <Text style={styles.avatarText}>{letter}</Text>
      )}
    </View>
  );
}

export default function ActorInfoScreen() {
  const theme = useTheme();
  const params = useLocalSearchParams<{
    id: string;
    audiencePlatformId?: string;
    platform?: string;
    nickname?: string;
    avatar?: string;
    remark?: string;
  }>();

  const taskID = typeof params.id === 'string' ? params.id : '';
  const paramAudienceId =
    typeof params.audiencePlatformId === 'string' ? params.audiencePlatformId.trim() : '';
  const paramPlatform = typeof params.platform === 'string' ? params.platform.trim() : '';
  const paramNickname = typeof params.nickname === 'string' ? params.nickname.trim() : '';
  const paramAvatar = typeof params.avatar === 'string' ? params.avatar.trim() : '';
  const paramRemark = typeof params.remark === 'string' ? params.remark : '';

  const conv = useMemo(() => {
    void ensureClaimedConversationsHydrated();
    return getClaimedConversationsSnapshot().find((c) => c.id === taskID);
  }, [taskID]);

  const audiencePlatformId =
    paramAudienceId || conv?.audiencePlatformID?.trim() || '';
  const platform = resolveAudienceApiPlatform({
    platform: paramPlatform || (typeof conv?.platform === 'string' ? conv.platform : undefined),
    imConversationID: conv?.imConversationID,
    audiencePlatformID: audiencePlatformId,
  });
  const nickname =
    paramNickname ||
    conv?.audiencePlatformNickname?.trim() ||
    conv?.to?.trim() ||
    '对方';
  const avatarUrl =
    paramAvatar || conv?.audiencePlatformFaceURL?.trim() || '';

  const [remark, setRemark] = useState(paramRemark);
  const [editOpen, setEditOpen] = useState(false);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);

  const openEdit = useCallback(() => {
    setDraft(remark);
    setEditOpen(true);
  }, [remark]);

  const handleSaveRemark = useCallback(async () => {
    const next = draft.trim();
    if (!audiencePlatformId) {
      appAlert('无法保存', '缺少对方平台账号标识');
      return;
    }
    setSaving(true);
    try {
      await updateAudiencePlatformRemark({
        platform,
        audience_platform_id: audiencePlatformId,
        remark: next,
      });
      setRemark(next);
      setEditOpen(false);
    } catch (e) {
      appAlert('保存失败', e instanceof Error ? e.message : '请稍后重试');
    } finally {
      setSaving(false);
    }
  }, [draft, audiencePlatformId, platform]);

  return (
    <ScreenCanvas safeAreaTop={false}>
      <StatusBar style="dark" />
      <CustomNavBar title="资料" onBack={() => router.back()} />

      <ScrollView
        style={styles.page}
        contentContainerStyle={styles.pageContent}
        showsVerticalScrollIndicator={false}
        keyboardShouldPersistTaps="handled"
      >
        <View
          style={[
            styles.profileCard,
            { backgroundColor: theme.surface, borderColor: theme.border },
            Tokens.shadow.card,
          ]}
        >
          <View pointerEvents="none" style={StyleSheet.absoluteFill}>
            <View style={[styles.wash, { backgroundColor: theme.primarySoft, opacity: 0.45 }]} />
          </View>

          <View style={styles.identity}>
            <AudienceAvatar url={avatarUrl} name={nickname} />
            <View style={styles.identityText}>
              <Text style={[styles.name, { color: theme.text }]} numberOfLines={1}>
                {nickname}
              </Text>
              <Text style={[styles.subtitle, { color: theme.textMuted }]} numberOfLines={1}>
                {platformLabel(platform)}
              </Text>
            </View>
          </View>

          <View style={[styles.divider, { backgroundColor: theme.divider }]} />

          <View style={styles.remarkHeader}>
            <Text style={[styles.fieldLabel, { color: theme.textSubtle }]}>备注</Text>
            <Pressable
              onPress={openEdit}
              hitSlop={8}
              style={({ pressed }) => [
                styles.editBtn,
                { backgroundColor: theme.primarySoft, opacity: pressed ? 0.7 : 1 },
              ]}
              accessibilityRole="button"
              accessibilityLabel="修改备注"
            >
              <EditOutlined size={14} color={theme.primary} />
              <Text style={[styles.editBtnText, { color: theme.primary }]}>修改</Text>
            </Pressable>
          </View>
          <Text
            style={[
              styles.remark,
              { color: remark.trim() ? theme.text : theme.textSubtle },
            ]}
          >
            {remark.trim() || '暂无备注'}
          </Text>
        </View>
      </ScrollView>

      <Modal
        visible={editOpen}
        transparent
        animationType="fade"
        onRequestClose={() => !saving && setEditOpen(false)}
      >
        <Pressable style={styles.modalOverlay} onPress={() => !saving && setEditOpen(false)}>
          <Pressable
            style={[styles.modalCard, { backgroundColor: theme.surface, borderColor: theme.border }]}
            onPress={(e) => e.stopPropagation()}
          >
            <Text style={[styles.modalTitle, { color: theme.text }]}>修改备注</Text>
            <TextInput
              style={[
                styles.remarkInput,
                {
                  color: theme.text,
                  backgroundColor: theme.surface2,
                  borderColor: theme.border,
                },
              ]}
              value={draft}
              onChangeText={setDraft}
              placeholder="输入备注信息"
              placeholderTextColor={theme.placeholder}
              multiline
              maxLength={200}
              textAlignVertical="top"
              editable={!saving}
              autoFocus={Platform.OS !== 'web'}
            />
            <View style={styles.modalActions}>
              <Pressable
                style={[styles.modalBtn, { backgroundColor: theme.surface2 }]}
                onPress={() => setEditOpen(false)}
                disabled={saving}
              >
                <Text style={[styles.modalBtnText, { color: theme.textMuted }]}>取消</Text>
              </Pressable>
              <Pressable
                style={[styles.modalBtn, { backgroundColor: theme.primary, opacity: saving ? 0.7 : 1 }]}
                onPress={() => void handleSaveRemark()}
                disabled={saving}
              >
                {saving ? (
                  <ActivityIndicator size="small" color="#FFF" />
                ) : (
                  <Text style={[styles.modalBtnText, { color: '#FFF' }]}>保存</Text>
                )}
              </Pressable>
            </View>
          </Pressable>
        </Pressable>
      </Modal>
    </ScreenCanvas>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1 },
  pageContent: {
    paddingHorizontal: Tokens.spacing[4],
    paddingTop: Tokens.spacing[3],
    paddingBottom: Tokens.spacing[9],
  },
  profileCard: {
    borderRadius: Tokens.radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    padding: Tokens.spacing[4],
    overflow: 'hidden',
    gap: Tokens.spacing[4],
  },
  wash: {
    position: 'absolute',
    top: -60,
    right: -40,
    width: 160,
    height: 160,
    borderRadius: 80,
  },
  identity: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Tokens.spacing[4],
  },
  avatar: {
    width: 64,
    height: 64,
    borderRadius: 32,
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarImage: {
    width: '100%',
    height: '100%',
  },
  avatarText: {
    fontSize: 26,
    fontWeight: '700',
    color: '#FFF',
  },
  identityText: {
    flex: 1,
    gap: 4,
  },
  name: {
    fontSize: 22,
    fontWeight: '700',
    letterSpacing: -0.3,
  },
  subtitle: {
    fontSize: 15,
    fontWeight: '500',
  },
  divider: {
    height: StyleSheet.hairlineWidth,
  },
  remarkHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  fieldLabel: {
    fontSize: 14,
    lineHeight: 22,
  },
  editBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: Tokens.radius.pill,
  },
  editBtnText: {
    fontSize: 13,
    fontWeight: '600',
  },
  remark: {
    fontSize: 15,
    lineHeight: 22,
    fontWeight: '500',
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.4)',
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: Tokens.spacing[5],
  },
  modalCard: {
    width: '100%',
    maxWidth: 400,
    borderRadius: Tokens.radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    padding: Tokens.spacing[5],
    gap: Tokens.spacing[4],
  },
  modalTitle: {
    fontSize: 17,
    fontWeight: '700',
  },
  remarkInput: {
    minHeight: 100,
    borderRadius: Tokens.radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: Tokens.spacing[3],
    paddingVertical: Tokens.spacing[3],
    fontSize: 15,
    lineHeight: 22,
  },
  modalActions: {
    flexDirection: 'row',
    gap: Tokens.spacing[3],
  },
  modalBtn: {
    flex: 1,
    height: 44,
    borderRadius: Tokens.radius.md,
    alignItems: 'center',
    justifyContent: 'center',
  },
  modalBtnText: {
    fontSize: 15,
    fontWeight: '600',
  },
});
