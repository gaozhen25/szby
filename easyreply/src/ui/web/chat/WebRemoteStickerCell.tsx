import { Popover } from 'antd';
import type { StickerItem } from '@/api/stickers';
import { webLayout } from '@/ui/web/theme';

const PREVIEW_SIZE = Math.round(webLayout.emojiSticker * 2);

/** 描述 / 使用说明 / 避免场景 / 标签 的信息气泡暂不展示 */

export function WebRemoteStickerCell({
  item,
  onSend,
}: {
  item: StickerItem;
  onSend: (item: StickerItem) => void;
}) {
  return (
    <Popover
      trigger="hover"
      mouseEnterDelay={0.3}
      mouseLeaveDelay={0.08}
      placement="top"
      arrow={false}
      getPopupContainer={() => document.body}
      overlayClassName="qh-sticker-breath"
      classNames={{ root: 'qh-sticker-breath' }}
      styles={{ container: { padding: 0, background: 'transparent' } }}
      content={
        <div className="qh-sticker-breath-preview">
          <img src={item.file_url} alt={item.name || ''} width={PREVIEW_SIZE} height={PREVIEW_SIZE} />
        </div>
      }
    >
      <button
        type="button"
        className="qh-sticker-send-cell"
        aria-label={item.name || '发送表情'}
        onClick={() => onSend(item)}
      >
        <img
          src={item.file_url}
          alt=""
          width={webLayout.emojiSticker}
          height={webLayout.emojiSticker}
        />
      </button>
    </Popover>
  );
}
