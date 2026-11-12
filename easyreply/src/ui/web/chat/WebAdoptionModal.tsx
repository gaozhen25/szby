import { useEffect, useMemo, useState } from 'react';
import { Button, Flex, Image, Input, Modal, Typography } from 'antd';
import { DeleteOutlined } from '@/ui/web/antd-icons';
import type { AdoptionCandidate, AdoptionContext } from '@/core/im';
import {
  looksLikeImageMessageContent,
  parseImageMessageContent,
} from '@/core/im/image-message';
import type { AdoptionDraftItem, AdoptionSubmitMode } from '@/chatMessage/components/AdoptionReviewSheet';
import { webColor, webFontSize, webType } from '@/ui/web/theme';

const ADOPTION_THUMB_SIZE = 70;

function resolveCandidateContentType(c: AdoptionCandidate): number {
  if (c.contentType === 102) return 102;
  const raw = c.editedContent || c.finalContent || c.originalContent || '';
  if (looksLikeImageMessageContent(raw)) return 102;
  return c.contentType || 101;
}

function isImageDraft(d: Pick<AdoptionDraftItem, 'contentType' | 'content'>): boolean {
  return d.contentType === 102 || looksLikeImageMessageContent(d.content);
}

function toDrafts(candidates: AdoptionCandidate[] | undefined): AdoptionDraftItem[] {
  return [...(candidates ?? [])]
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

function AdoptionImagePreview({ content }: { content: string }) {
  const parsed = useMemo(() => parseImageMessageContent(content), [content]);
  if (!parsed?.imageUrl) {
    return (
      <Typography.Text type="secondary" style={{ fontSize: webFontSize.md }}>
        [图片]
      </Typography.Text>
    );
  }
  return (
    <Image
      src={parsed.imageUrl}
      alt="候选图片"
      width={ADOPTION_THUMB_SIZE}
      height={ADOPTION_THUMB_SIZE}
      style={{ borderRadius: 8, objectFit: 'cover' }}
      preview={{ mask: '查看大图' }}
    />
  );
}

const cardStyle = {
  borderRadius: 12,
  border: `1px solid ${webColor.separator}`,
  background: webColor.bg,
  padding: 12,
} as const;

export function WebAdoptionModal({
  open,
  adoption,
  submitting,
  onClose,
  onSubmit,
}: {
  open: boolean;
  adoption: AdoptionContext | null;
  submitting: boolean;
  onClose: () => void;
  onSubmit: (
    drafts: AdoptionDraftItem[],
    mode: AdoptionSubmitMode,
    opts?: { rewriteContent?: string; droppedDrafts?: AdoptionDraftItem[] },
  ) => void;
}) {
  const candidates = adoption?.candidates ?? [];
  const [drafts, setDrafts] = useState<AdoptionDraftItem[]>(() => toDrafts(candidates));
  const [removedDrafts, setRemovedDrafts] = useState<AdoptionDraftItem[]>([]);
  const [customMode, setCustomMode] = useState(false);
  const [rewriteContent, setRewriteContent] = useState('');

  useEffect(() => {
    if (open) {
      setDrafts(toDrafts(adoption?.candidates ?? []));
      setRemovedDrafts([]);
      setCustomMode(false);
      setRewriteContent('');
    }
  }, [open, adoption]);

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
    <Modal
      open={open}
      onCancel={onClose}
      closable={false}
      styles={{ title: webType.modalTitle }}
      title={
        <Flex align="center" justify="space-between" gap={12}>
          <Typography.Text style={{ ...webType.modalTitle, fontWeight: 700 }}>
            AI消息复审
          </Typography.Text>
          <Button
            type="link"
            disabled={submitting}
            onClick={toggleCustomMode}
            style={{
              padding: 0,
              height: 'auto',
              fontWeight: 600,
              color: webColor.primary,
            }}
          >
            {customMode ? '取消自定义' : '自定义'}
          </Button>
        </Flex>
      }
      footer={
        <Flex vertical gap={8}>
          <Flex gap={12}>
            <Button
              block
              disabled={submitting}
              onClick={onClose}
              style={{
                height: 44,
                borderRadius: 12,
                border: 'none',
                background: webColor.bg,
                color: webColor.subLabel,
                fontWeight: 600,
              }}
            >
              取消
            </Button>
            <Button
              block
              disabled={submitting || drafts.length === 0}
              onClick={handleDrop}
              style={{
                height: 44,
                borderRadius: 12,
                border: 'none',
                background: webColor.warningSoft,
                color: webColor.warning,
                fontWeight: 600,
              }}
            >
              已处理
            </Button>
          </Flex>
          <Button
            type="primary"
            block
            loading={submitting}
            disabled={!canSubmit}
            onClick={handleConfirm}
            style={{ height: 44, borderRadius: 12, fontWeight: 600 }}
          >
            确定
          </Button>
        </Flex>
      }
    >
      {customMode ? (
        <div style={{ ...cardStyle, marginTop: 4 }}>
          <span
            style={{
              display: 'block',
              marginBottom: 6,
              fontSize: webFontSize.sm,
              fontWeight: 600,
              color: webColor.subLabel,
            }}
          >
            自定义消息
          </span>
          <Input.TextArea
            autoSize={{ minRows: 4, maxRows: 8 }}
            value={rewriteContent}
            onChange={(e) => setRewriteContent(e.target.value)}
            disabled={submitting}
            autoFocus
            placeholder="输入要发送的消息内容"
            style={{ borderRadius: 10, fontSize: webFontSize.md }}
          />
        </div>
      ) : (
        <Flex vertical gap={10} style={{ marginTop: 4, maxHeight: 360, overflowY: 'auto' }}>
          {drafts.map((d, i) => {
            const image = isImageDraft(d);
            return (
              <div key={d.candidateID} style={cardStyle}>
                <Flex align="center" gap={8} style={{ marginBottom: 6 }}>
                  <Typography.Text
                    style={{
                      flex: 1,
                      margin: 0,
                      fontSize: webFontSize.sm,
                      fontWeight: 600,
                      color: webColor.subLabel,
                    }}
                  >
                    候选 {i + 1}
                    {image ? ' · 图片 · 点击放大' : ''}
                  </Typography.Text>
                  <Button
                    type="text"
                    size="small"
                    danger={canRemove}
                    disabled={!canRemove}
                    icon={<DeleteOutlined />}
                    onClick={() => removeDraft(d.candidateID)}
                    aria-label="删除该候选"
                    style={{ flexShrink: 0 }}
                  />
                </Flex>
                {image ? (
                  <AdoptionImagePreview content={d.content || d.originalContent} />
                ) : (
                  <Input.TextArea
                    autoSize={{ minRows: 3, maxRows: 6 }}
                    value={d.content}
                    disabled={submitting}
                    placeholder="待复审内容"
                    onChange={(e) => updateContent(d.candidateID, e.target.value)}
                    style={{ borderRadius: 10, fontSize: webFontSize.md }}
                  />
                )}
              </div>
            );
          })}
        </Flex>
      )}
    </Modal>
  );
}
