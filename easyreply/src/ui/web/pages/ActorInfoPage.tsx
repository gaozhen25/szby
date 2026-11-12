import { useCallback, useMemo, useState } from 'react';
import { Avatar, Button, Card, Descriptions, Flex, Input, Modal } from 'antd';
import { router, useLocalSearchParams } from 'expo-router';
import { updateAudiencePlatformRemark } from '@/api/actors';
import { appAlert } from '@/lib/app-alert';
import { resolveAudienceApiPlatform } from '@/core/im';
import { ensureClaimedConversationsHydrated, getClaimedConversationsSnapshot } from '@/lib/claimed-conversations-store';
import { PageFrame } from '@/ui/web/PageFrame';
import { webLayout, webPageBg } from '@/ui/web/theme';

function platformLabel(platform: string): string {
  const p = platform.trim().toLowerCase();
  if (p === 'wecom') return '企业微信';
  if (p === 'wechat' || p === 'weixin') return '微信';
  if (p === 'douyin') return '抖音';
  if (p === '微信' || p === '抖音') return p;
  return platform.trim() || '未知平台';
}

export default function ActorInfoPage() {
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
  const conv = useMemo(() => {
    void ensureClaimedConversationsHydrated();
    return getClaimedConversationsSnapshot().find((c) => c.id === taskID);
  }, [taskID]);

  const audiencePlatformId = paramAudienceId || conv?.audiencePlatformID?.trim() || '';
  const platform = resolveAudienceApiPlatform({
    platform: typeof params.platform === 'string' ? params.platform : conv?.platform,
    imConversationID: conv?.imConversationID,
    audiencePlatformID: audiencePlatformId,
  });
  const nickname =
    (typeof params.nickname === 'string' ? params.nickname.trim() : '') ||
    conv?.audiencePlatformNickname?.trim() ||
    conv?.to?.trim() ||
    '对方';
  const avatarUrl = (typeof params.avatar === 'string' ? params.avatar : '') || conv?.audiencePlatformFaceURL?.trim() || '';
  const [remark, setRemark] = useState(typeof params.remark === 'string' ? params.remark : '');
  const [editOpen, setEditOpen] = useState(false);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);

  const handleSave = useCallback(async () => {
    if (!audiencePlatformId) {
      appAlert('无法保存', '缺少对方平台账号标识');
      return;
    }
    setSaving(true);
    try {
      await updateAudiencePlatformRemark({
        platform,
        audience_platform_id: audiencePlatformId,
        remark: draft.trim(),
      });
      setRemark(draft.trim());
      setEditOpen(false);
    } catch (e) {
      appAlert('保存失败', e instanceof Error ? e.message : '请稍后重试');
    } finally {
      setSaving(false);
    }
  }, [audiencePlatformId, draft, platform]);

  return (
    <PageFrame title="资料">
      <Flex vertical align="center" style={{ ...webLayout.pageBody, padding: 24, background: webPageBg.actorInfo }} gap={16}>
        <Card style={{ width: 480 }}>
          <Flex vertical align="center" gap={12}>
            <Avatar size={72} src={avatarUrl || undefined}>
              {nickname.charAt(0)}
            </Avatar>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="昵称">{nickname}</Descriptions.Item>
              <Descriptions.Item label="平台">{platformLabel(platform)}</Descriptions.Item>
              <Descriptions.Item label="备注">{remark || '—'}</Descriptions.Item>
            </Descriptions>
            <Button onClick={() => { setDraft(remark); setEditOpen(true); }}>修改备注</Button>
            <Button type="link" onClick={() => router.back()}>返回聊天</Button>
          </Flex>
        </Card>
      </Flex>
      <Modal
        open={editOpen}
        title="修改备注"
        confirmLoading={saving}
        onCancel={() => setEditOpen(false)}
        onOk={() => void handleSave()}
      >
        <Input.TextArea rows={3} value={draft} onChange={(e) => setDraft(e.target.value)} />
      </Modal>
    </PageFrame>
  );
}
