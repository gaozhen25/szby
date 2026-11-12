import { useEffect, useState } from 'react';
import { Button, Card, Flex, Tag, Typography } from 'antd';
import {
  BellOutlined,
  CheckOutlined,
  CloseOutlined,
  CopyOutlined,
  SendOutlined,
} from '@/ui/web/antd-icons';
import type { ProactiveActionHint } from '@/core/im/types';
import { copyText } from '@/lib/clipboard';
import {
  pickValidProactiveActionHints,
  proactiveActionHintKey,
} from '@/lib/proactive-action-hints';
import { webColor } from '@/ui/web/theme';

type Props = {
  visible: boolean;
  hints: ProactiveActionHint[] | null | undefined;
  canQuickSend?: boolean;
  onDismiss: () => void;
  onQuickSend?: (hint: ProactiveActionHint, index: number) => void;
  onFillDraft?: (text: string) => void;
};

function FillableText({
  text,
  canFill,
  onFill,
  className,
  layout,
}: {
  text: string;
  canFill: boolean;
  onFill?: (text: string) => void;
  className: string;
  layout?: 'task' | 'content';
}) {
  if (!text) return null;

  const body = (
    <Typography.Text className={className} ellipsis>
      {text}
    </Typography.Text>
  );

  if (!canFill || !onFill) return body;

  return (
    <button
      type="button"
      className={`qh-proactive-hint-fill${layout === 'task' ? ' is-task' : layout === 'content' ? ' is-content' : ''}`}
      onClick={() => onFill(text)}
      aria-label="填入输入框"
    >
      {body}
    </button>
  );
}

function HintItem({
  item,
  index,
  total,
  multi,
  canQuickSend,
  onQuickSend,
  onFillDraft,
}: {
  item: ProactiveActionHint;
  index: number;
  total: number;
  multi: boolean;
  canQuickSend: boolean;
  onQuickSend?: (hint: ProactiveActionHint, index: number) => void;
  onFillDraft?: (text: string) => void;
}) {
  const taskName = item.taskName?.trim();
  const content = item.actionContent.trim();
  const [copied, setCopied] = useState(false);
  const canFill = canQuickSend && !!onFillDraft;

  const handleCopy = async () => {
    const ok = await copyText(content);
    if (!ok) return;
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className={`qh-proactive-hint-item${index < total - 1 ? ' is-divided' : ''}`}>
      <div className="qh-proactive-hint-item-main">
        {multi ? <span className="qh-proactive-hint-index">{index + 1}</span> : null}

        <div className="qh-proactive-hint-item-text">
          <div className="qh-proactive-hint-content-row">
            {taskName ? (
              <>
                <FillableText
                  text={taskName}
                  canFill={canFill}
                  onFill={onFillDraft}
                  className="qh-proactive-hint-task"
                  layout="task"
                />
                {content ? <span className="qh-proactive-hint-sep">·</span> : null}
              </>
            ) : null}
            {content ? (
              <span className="qh-proactive-hint-content-group">
                <FillableText
                  text={content}
                  canFill={canFill}
                  onFill={onFillDraft}
                  className="qh-proactive-hint-content"
                  layout="content"
                />
                <Button
                  type="text"
                  size="small"
                  className={`qh-proactive-hint-copy${copied ? ' is-copied' : ''}`}
                  icon={copied ? <CheckOutlined /> : <CopyOutlined />}
                  aria-label={copied ? '已复制' : '复制内容'}
                  onClick={() => void handleCopy()}
                />
              </span>
            ) : null}
          </div>
        </div>

        {canQuickSend && onQuickSend ? (
          <Button
            type="primary"
            size="small"
            className="qh-proactive-hint-send"
            icon={<SendOutlined />}
            onClick={() => onQuickSend(item, index)}
          >
            发送
          </Button>
        ) : null}
      </div>
    </div>
  );
}

export function WebProactiveActionHintBanner({
  visible,
  hints,
  canQuickSend = true,
  onDismiss,
  onQuickSend,
  onFillDraft,
}: Props) {
  const items = pickValidProactiveActionHints(hints) ?? [];
  const shouldShow = visible && items.length > 0;
  const multi = items.length > 1;

  const [mounted, setMounted] = useState(shouldShow);
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    if (shouldShow) {
      setLeaving(false);
      setMounted(true);
      return;
    }
    if (!mounted) return;
    setLeaving(true);
    const timer = window.setTimeout(() => {
      setMounted(false);
      setLeaving(false);
    }, 200);
    return () => window.clearTimeout(timer);
  }, [shouldShow, mounted]);

  if (!mounted) return null;

  return (
    <div
      className={`qh-proactive-hint-host${leaving ? ' is-leaving' : ' is-entering'}`}
      role="region"
      aria-label="新的消息提醒"
    >
      <Card size="small" className="qh-proactive-hint-card" styles={{ body: { padding: 0 } }}>
        <Flex align="center" gap={4} className="qh-proactive-hint-header">
          <BellOutlined style={{ color: webColor.proactive, fontSize: 13, flexShrink: 0 }} />
          <Typography.Text className="qh-proactive-hint-title">
            新的消息提醒
          </Typography.Text>
          {multi ? (
            <Tag bordered={false} className="qh-proactive-hint-count">
              {items.length}
            </Tag>
          ) : null}
          <span style={{ flex: 1, minWidth: 8 }} />
          <Button
            type="text"
            size="small"
            className="qh-proactive-hint-close"
            icon={<CloseOutlined />}
            aria-label="关闭提醒"
            onClick={onDismiss}
          />
        </Flex>
        <div className="qh-proactive-hint-body">
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
            />
          ))}
        </div>
      </Card>
    </div>
  );
}

export default WebProactiveActionHintBanner;
