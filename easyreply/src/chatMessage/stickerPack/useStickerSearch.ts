import { useCallback, useEffect, useRef, useState } from 'react';
import {
  searchStickers,
  stickerItemToSendable,
  type StickerItem,
} from '@/api/stickers';
import type { CustomSticker } from '@/chatMessage/stickerPack/custom-stickers-store';

export function useStickerSearch(active: boolean) {
  const [keyword, setKeyword] = useState('');
  const [draftKeyword, setDraftKeyword] = useState('');
  const [items, setItems] = useState<StickerItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);
  const reqSeq = useRef(0);

  const runSearch = useCallback(async (kw: string) => {
    const trimmed = kw.trim();
    if (!trimmed) {
      setItems([]);
      setError(null);
      setSearched(false);
      return;
    }
    const seq = ++reqSeq.current;
    setLoading(true);
    setError(null);
    setSearched(true);
    try {
      const list = await searchStickers({
        keyword: trimmed,
        tag_codes: [],
        tag_match: 'all',
        limit: 999,
      });
      if (seq !== reqSeq.current) return;
      setItems(list);
    } catch (e) {
      if (seq !== reqSeq.current) return;
      setItems([]);
      setError(e instanceof Error ? e.message : '搜索失败');
    } finally {
      if (seq === reqSeq.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!active) return;
    void runSearch(keyword);
  }, [active, keyword, runSearch]);

  const onSubmitSearch = useCallback(() => {
    setKeyword(draftKeyword.trim());
  }, [draftKeyword]);

  const onClearSearch = useCallback(() => {
    setDraftKeyword('');
    setKeyword('');
  }, []);

  const toSendable = useCallback(
    (item: StickerItem) => stickerItemToSendable(item) as CustomSticker,
    [],
  );

  return {
    draftKeyword,
    setDraftKeyword,
    keyword,
    items,
    loading,
    error,
    searched,
    runSearch,
    onSubmitSearch,
    onClearSearch,
    toSendable,
  };
}
