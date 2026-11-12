import { useCallback, useEffect, useMemo, useState } from 'react';
import { Avatar, Button, Descriptions, Flex, Input, Modal } from 'antd';
import { updateAudiencePlatformRemark } from '@/api/actors';
import { resolveAudienceApiPlatform } from '@/core/im';
import { appAlert } from '@/lib/app-alert';
import {
  ensureClaimedConversationsHydrated,
  getClaimedConversationsSnapshot,
} from '@/lib/claimed-conversations-store';
import { webColor, webModalCloseStyle, webType } from '@/ui/web/theme';

function platformLabel(platform: string): string {
  const p = platform.trim().toLowerCase();
  if (p === 'wecom') return '企业微信';
  if (p === 'wechat' || p === 'weixin') return '微信';
  if (p === 'douyin') return '抖音';
  if (p === '微信' || p === '抖音') return p;
  return platform.trim() || '未知平台';
}

export type WebAudienceProfileModalProps = {
  open: boolean;
  taskID: string;
  nickname?: string;
  avatarUrl?: string;
  onClose: () => void;
};

export function WebAudienceProfileModal({
  open,
  taskID,
  nickname: nicknameProp,
  avatarUrl: avatarProp,
  onClose,
}: WebAudienceProfileModalProps) {
  const conv = useMemo(() => {
    if (!open || !taskID) return undefined;
    void ensureClaimedConversationsHydrated();
    return getClaimedConversationsSnapshot().find((c) => c.id === taskID);
  }, [open, taskID]);

  const audiencePlatformId = conv?.audiencePlatformID?.trim() || '';
  const platform = resolveAudienceApiPlatform({
    platform: typeof conv?.platform === 'string' ? conv.platform : undefined,
    imConversationID: conv?.imConversationID,
    audiencePlatformID: audiencePlatformId,
  });
  const nickname =
    nicknameProp?.trim() ||
    conv?.audiencePlatformNickname?.trim() ||
    conv?.to?.trim() ||
    '对方';
  const avatarUrl = avatarProp?.trim() || conv?.audiencePlatformFaceURL?.trim() || '';

  const [remark, setRemark] = useState('');
  const [editOpen, setEditOpen] = useState(false);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) {
      setEditOpen(false);
      setDraft('');
      setSaving(false);
      return;
    }
    setRemark('');
  }, [open, taskID]);

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
    <>
      <Modal
        open={open}
        title="资料"
        mask={{ closable: false }}
        onCancel={onClose}
        styles={{ title: webType.modalTitle, close: webModalCloseStyle }}
        footer={[
          <Button key="close" type="primary" onClick={onClose}>
            关闭
          </Button>,
        ]}
        width={420}
        destroyOnHidden
      >
        <Flex vertical align="center" gap={14} style={{ paddingTop: 4 }}>
          <Avatar
            size={72}
            src={avatarUrl || undefined}
            style={{ background: webColor.primarySoft, color: webColor.primary, fontWeight: 600 }}
          >
            {nickname.charAt(0) || '对'}
          </Avatar>
          <Descriptions column={1} size="small" style={{ width: '100%' }}>
            <Descriptions.Item label="昵称">{nickname}</Descriptions.Item>
            <Descriptions.Item label="平台">{platformLabel(platform)}</Descriptions.Item>
            <Descriptions.Item label="备注">{remark || '—'}</Descriptions.Item>
          </Descriptions>
          <Button
            onClick={() => {
              setDraft(remark);
              setEditOpen(true);
            }}
          >
            修改备注
          </Button>
        </Flex>
      </Modal>

      <Modal
        open={editOpen}
        title="修改备注"
        mask={{ closable: false }}
        confirmLoading={saving}
        onCancel={() => setEditOpen(false)}
        onOk={() => void handleSave()}
        styles={{ title: webType.modalTitle, close: webModalCloseStyle }}
        destroyOnHidden
      >
        <Input.TextArea
          rows={3}
          maxLength={200}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="请输入备注"
        />
      </Modal>
    </>
  );
}
