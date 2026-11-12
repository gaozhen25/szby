import { useCallback, useEffect, useState } from 'react';
import { Button, Flex, Modal, Spin, Upload } from 'antd';
import { CheckOutlined, PlusOutlined } from '@/ui/web/antd-icons';
import { uploadImageAsset } from '@/api/assets';
import { appAlert } from '@/lib/app-alert';
import {
  addCustomSticker,
  ensureCustomStickersHydrated,
  MAX_CUSTOM_STICKERS,
  removeCustomStickers,
  subscribeCustomStickers,
  type CustomSticker,
} from '@/chatMessage/stickerPack';
import { webFontSize } from '@/ui/web/theme';

const IMAGE_ACCEPT = 'image/png,image/jpeg,image/jpg,image/webp,image/gif,.png,.jpg,.jpeg,.webp,.gif';

export function WebCustomStickersModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [stickers, setStickers] = useState<CustomSticker[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());

  useEffect(() => {
    if (!open) return;
    let alive = true;
    setLoading(true);
    setSelectedIds(new Set());
    void ensureCustomStickersHydrated()
      .then((list) => {
        if (alive) setStickers(list);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    const off = subscribeCustomStickers((list) => {
      if (!alive) return;
      setStickers(list);
      setSelectedIds((prev) => {
        if (prev.size === 0) return prev;
        const valid = new Set(list.map((s) => s.id));
        const next = new Set([...prev].filter((id) => valid.has(id)));
        return next.size === prev.size ? prev : next;
      });
    });
    return () => {
      alive = false;
      off();
    };
  }, [open]);

  const uploadFile = useCallback(async (file: File) => {
    if (stickers.length >= MAX_CUSTOM_STICKERS) {
      appAlert('已达上限', `最多添加 ${MAX_CUSTOM_STICKERS} 个自定义表情`);
      return;
    }
    setUploading(true);
    const uri = URL.createObjectURL(file);
    try {
      const uploaded = await uploadImageAsset({
        uri,
        mimeType: file.type,
        fileName: file.name,
        blob: file,
      });
      await addCustomSticker({
        url: uploaded.url,
        objectKey: uploaded.objectKey,
      });
    } catch (e) {
      appAlert('上传失败', e instanceof Error ? e.message : '请稍后重试');
    } finally {
      URL.revokeObjectURL(uri);
      setUploading(false);
    }
  }, [stickers.length]);

  const allSelected = stickers.length > 0 && stickers.every((s) => selectedIds.has(s.id));

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleSelectAll = () => {
    if (stickers.length === 0) return;
    setSelectedIds(allSelected ? new Set() : new Set(stickers.map((s) => s.id)));
  };

  const handleDelete = () => {
    if (selectedIds.size === 0) return;
    appAlert('删除表情', `确认删除选中的 ${selectedIds.size} 个表情？`, [
      { text: '取消', style: 'cancel' },
      {
        text: '删除',
        style: 'destructive',
        onPress: () => {
          void (async () => {
            try {
              await removeCustomStickers([...selectedIds]);
              setSelectedIds(new Set());
            } catch (e) {
              appAlert('删除失败', e instanceof Error ? e.message : '请稍后重试');
            }
          })();
        },
      },
    ]);
  };

  const atLimit = stickers.length >= MAX_CUSTOM_STICKERS;

  return (
    <Modal
      title={`添加的单个表情 (${stickers.length})`}
      open={open}
      onCancel={onClose}
      destroyOnHidden
      centered
      width={480}
      zIndex={1200}
      rootClassName="qh-sticker-modal"
      footer={
        <Flex justify="flex-end" gap={8}>
          <Button type="text" disabled={stickers.length === 0} onClick={handleSelectAll}>
            {allSelected ? '取消全选' : '全选'}
          </Button>
          <Button type="text" danger disabled={selectedIds.size === 0} onClick={handleDelete}>
            {selectedIds.size > 0 ? `删除(${selectedIds.size})` : '删除'}
          </Button>
        </Flex>
      }
    >
      {loading ? (
        <Flex justify="center" style={{ padding: 48 }}>
          <Spin />
        </Flex>
      ) : (
        <div className="qh-sticker-manage-grid">
          <Upload
            accept={IMAGE_ACCEPT}
            showUploadList={false}
            disabled={uploading || atLimit}
            beforeUpload={(file) => {
              void uploadFile(file as File);
              return false;
            }}
          >
            <button
              type="button"
              className="qh-sticker-add-cell qh-sticker-manage-add"
              disabled={uploading || atLimit}
              aria-label="从相册添加表情"
              title={atLimit ? `最多添加 ${MAX_CUSTOM_STICKERS} 个表情` : '添加图片或动图'}
            >
              {uploading ? (
                <Spin size="small" />
              ) : (
                <PlusOutlined style={{ fontSize: webFontSize.xl }} />
              )}
            </button>
          </Upload>
          {stickers.map((s) => {
            const selected = selectedIds.has(s.id);
            return (
              <button
                key={s.id}
                type="button"
                className={`qh-sticker-manage-cell${selected ? ' is-selected' : ''}`}
                aria-pressed={selected}
                aria-label="选择表情"
                onClick={() => toggleSelect(s.id)}
              >
                <img src={s.url} alt="" />
                <span className="qh-sticker-check" aria-hidden>
                  {selected ? <CheckOutlined /> : null}
                </span>
              </button>
            );
          })}
        </div>
      )}
    </Modal>
  );
}
