import { type CSSProperties, type ComponentType, type ReactNode } from 'react';
import { Typography } from 'antd';
import { isPureWechatEmojiText, parseWechatEmojiText } from '@/core/im/wechat-emoji';
import { getWechatEmojiUri } from '@/chatMessage/message/chat-emoji-draft';
import { webComponent } from '@/lib/web-component';
import { EmojiText as NativeEmojiText } from './EmojiText.tsx';

export type EmojiTextVariant = 'bubble' | 'preview';

type Props = {
  text: string;
  color?: string;
  className?: string;
  style?: CSSProperties;
  textStyle?: CSSProperties;
  /** bubble：聊天气泡；preview：会话列表末条，单行 */
  variant?: EmojiTextVariant;
  /** 己方气泡内链接配色 */
  mine?: boolean;
};

const HTTP_URL_RE = /(https?:\/\/[^\s]+)/gi;

function renderLinks(text: string, mine: boolean, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let last = 0;
  let match: RegExpExecArray | null;
  HTTP_URL_RE.lastIndex = 0;
  while ((match = HTTP_URL_RE.exec(text))) {
    const raw = match[0];
    const start = match.index;
    if (start > last) nodes.push(text.slice(last, start));
    const trimmed = raw.replace(/[),.;!?]+$/g, '');
    const href = trimmed || raw;
    const trail = trimmed && trimmed !== raw ? raw.slice(trimmed.length) : '';
    nodes.push(
      <Typography.Link
        key={`${keyPrefix}-link-${start}`}
        className={mine ? 'qh-chat-link is-mine' : 'qh-chat-link'}
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        onClick={(e) => e.stopPropagation()}
      >
        {href}
      </Typography.Link>,
    );
    if (trail) nodes.push(trail);
    last = start + raw.length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes.length > 0 ? nodes : [text];
}

function renderSegments(text: string, mine: boolean, linkify: boolean): ReactNode[] {
  return parseWechatEmojiText(text).map((seg, index) => {
    if (seg.kind !== 'emoji') {
      if (!linkify) return <span key={`t-${index}`}>{seg.value}</span>;
      return <span key={`t-${index}`}>{renderLinks(seg.value, mine, `t-${index}`)}</span>;
    }
    const uri = getWechatEmojiUri(seg.name);
    if (!uri) return <span key={`e-${index}`}>[{seg.name}]</span>;
    return <img key={`e-${index}`} src={uri} alt={seg.name} draggable={false} />;
  });
}

/** Web：与原生同一套 parseWechatEmojiText / getWechatEmojiUri，仅渲染层用 img */
function WebEmojiText({
  text,
  color,
  className,
  style,
  textStyle,
  variant = 'bubble',
  mine = false,
}: Props) {
  const preview = variant === 'preview';
  const pure = !preview && isPureWechatEmojiText(text);
  const cls = [
    'qh-emoji-text',
    preview ? 'is-preview' : 'is-bubble',
    pure ? 'is-pure' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ');
  const mergedStyle = { ...style, ...textStyle, color };

  if (pure) {
    const name = text.trim().slice(1, -1);
    const uri = getWechatEmojiUri(name);
    if (uri) {
      return (
        <span className={cls} style={mergedStyle}>
          <img src={uri} alt={name} draggable={false} />
        </span>
      );
    }
  }

  return (
    <span className={cls} style={mergedStyle}>
      {renderSegments(text, mine, !preview)}
    </span>
  );
}

export const EmojiText = webComponent(WebEmojiText, NativeEmojiText as ComponentType<Props>);
