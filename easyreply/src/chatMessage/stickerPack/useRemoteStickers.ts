import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  fetchStickerList,
  fetchStickerOptions,
  searchStickers,
  stickerItemToSendable,
  type StickerItem,
  type StickerTag,
} from '@/api/stickers';
import type { CustomSticker } from '@/chatMessage/stickerPack/custom-stickers-store';

const PAGE_SIZE = 24;

type BrowseMode = { kind: 'all' } | { kind: 'search'; tagCodes: string[] };

export function useRemoteStickers(active: boolean) {
  const [tags, setTags] = useState<StickerTag[]>([]);
  const [optionsError, setOptionsError] = useState(false);
  const [tagCodes, setTagCodes] = useState<string[]>([]);
  const [items, setItems] = useState<StickerItem[]>([]);
  const [pageNo, setPageNo] = useState(1);
  const [hasNext, setHasNext] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reqSeq = useRef(0);

  const browseKey = useMemo(() => {
    if (tagCodes.length > 0) return `search:${[...tagCodes].sort().join(',')}`;
    return 'all';
  }, [tagCodes]);

  const browseMode = useMemo<BrowseMode>(() => {
    if (tagCodes.length > 0) return { kind: 'search', tagCodes };
    return { kind: 'all' };
  }, [tagCodes]);

  const loadOptions = useCallback(async () => {
    try {
      const groups = await fetchStickerOptions();
      const seen = new Set<string>();
      const flat: StickerTag[] = [];
      for (const g of groups) {
        for (const t of g.tags) {
          if (!t.code || seen.has(t.code)) continue;
          seen.add(t.code);
          flat.push(t);
        }
      }
      setTags(flat);
      setOptionsError(false);
    } catch {
      setTags([]);
      setOptionsError(true);
    }
  }, []);

  const loadBrowse = useCallback(async (mode: BrowseMode, page: number, append: boolean) => {
    const seq = ++reqSeq.current;
    if (append) setLoadingMore(true);
    else {
      setLoading(true);
      setError(null);
    }
    try {
      if (mode.kind === 'search') {
        const list = await searchStickers({
          keyword: '',
          tag_codes: mode.tagCodes,
          tag_match: 'all',
          limit: 999,
        });
        if (seq !== reqSeq.current) return;
        setItems(list);
        setPageNo(1);
        setHasNext(false);
        return;
      }

      const pageData = await fetchStickerList({ page_no: page, page_size: PAGE_SIZE });
      if (seq !== reqSeq.current) return;
      setItems((prev) => (append ? [...prev, ...pageData.items] : pageData.items));
      setPageNo(page);
      setHasNext(!!pageData.has_next);
    } catch (e) {
      if (seq !== reqSeq.current) return;
      if (!append) {
        setItems([]);
        setHasNext(false);
        setError(e instanceof Error ? e.message : '加载失败');
      }
    } finally {
      if (seq === reqSeq.current) {
        setLoading(false);
        setLoadingMore(false);
      }
    }
  }, []);

  useEffect(() => {
    if (!active) return;
    void loadOptions();
  }, [active, loadOptions]);

  useEffect(() => {
    if (!active) return;
    void loadBrowse(browseMode, 1, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, browseKey, loadBrowse]);

  const onPressAll = useCallback(() => {
    setTagCodes([]);
  }, []);

  const onPressTag = useCallback((code: string) => {
    setTagCodes((prev) => (prev.length === 1 && prev[0] === code ? [] : [code]));
  }, []);

  const onLoadMore = useCallback(() => {
    if (!hasNext || loading || loadingMore) return;
    if (browseMode.kind === 'search') return;
    void loadBrowse(browseMode, pageNo + 1, true);
  }, [hasNext, loading, loadingMore, browseMode, pageNo, loadBrowse]);

  const reload = useCallback(() => {
    void loadBrowse(browseMode, 1, false);
  }, [browseMode, loadBrowse]);

  const toSendable = useCallback(
    (item: StickerItem) => stickerItemToSendable(item) as CustomSticker,
    [],
  );

  return {
    tags,
    optionsError,
    tagCodes,
    items,
    loading,
    loadingMore,
    error,
    hasNext,
    onPressAll,
    onPressTag,
    onLoadMore,
    reload,
    toSendable,
  };
}
