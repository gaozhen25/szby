import { useCallback, useEffect, useRef, useState } from 'react';
import {
  formatCollectedAudienceError,
  listCollectedAudiences,
  removeCollectedAudience,
} from '@/api/agents';
import { appAlert } from '@/lib/app-alert';
import { getClaimedConversationsSnapshot } from '@/lib/claimed-conversations-store';

export type FavoriteRow = {
  audiencePlatformID: string;
  nickname: string;
};

export function resolveFavoriteRows(ids: string[]): FavoriteRow[] {
  const convs = getClaimedConversationsSnapshot();
  const byAudience = new Map<string, string>();
  for (const c of convs) {
    const id = (c.audiencePlatformID ?? '').trim();
    if (!id || byAudience.has(id)) continue;
    byAudience.set(id, c.audiencePlatformNickname?.trim() || c.to?.trim() || id);
  }
  return ids.map((id) => ({ audiencePlatformID: id, nickname: byAudience.get(id) || id }));
}

type UseFavoritesListOptions = {
  /** 为 false 时不拉取（弹窗关闭时节省请求） */
  active?: boolean;
  onIdsChange?: (ids: string[]) => void;
};

export function useFavoritesList({ active = true, onIdsChange }: UseFavoritesListOptions = {}) {
  const [rows, setRows] = useState<FavoriteRow[]>([]);
  const [loading, setLoading] = useState(false);
  const removingRef = useRef<Set<string>>(new Set());

  const loadList = useCallback(async () => {
    const fav = await listCollectedAudiences();
    const ids = fav?.ok && Array.isArray(fav.collected_audience_ids)
      ? fav.collected_audience_ids.map((id) => id.trim()).filter(Boolean)
      : [];
    return resolveFavoriteRows(ids);
  }, []);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const next = await loadList();
      setRows(next);
      onIdsChange?.(next.map((r) => r.audiencePlatformID));
      return next;
    } catch (e) {
      setRows([]);
      appAlert('加载失败', formatCollectedAudienceError(e));
      return [];
    } finally {
      setLoading(false);
    }
  }, [loadList, onIdsChange]);

  useEffect(() => {
    if (!active) return;
    let alive = true;
    setLoading(true);
    void loadList()
      .then((next) => {
        if (alive) setRows(next);
      })
      .catch((e) => {
        if (alive) {
          setRows([]);
          appAlert('加载失败', formatCollectedAudienceError(e));
        }
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [active, loadList]);

  const handleRemove = useCallback(
    (item: FavoriteRow) => {
      const id = item.audiencePlatformID;
      if (!id || removingRef.current.has(id)) return;
      appAlert('取消收藏', `确定取消收藏「${item.nickname}」？`, [
        { text: '取消', style: 'cancel' },
        {
          text: '取消收藏',
          style: 'destructive',
          onPress: () => {
            removingRef.current.add(id);
            const prev = rows;
            setRows((cur) => cur.filter((r) => r.audiencePlatformID !== id));
            void removeCollectedAudience({ audience_platform_id: id })
              .then((res) => {
                const ids = Array.isArray(res.collected_audience_ids)
                  ? res.collected_audience_ids.map((x) => x.trim()).filter(Boolean)
                  : [];
                const next = resolveFavoriteRows(ids);
                setRows(next);
                onIdsChange?.(ids);
              })
              .catch((e) => {
                setRows(prev);
                appAlert('取消收藏失败', formatCollectedAudienceError(e));
              })
              .finally(() => removingRef.current.delete(id));
          },
        },
      ]);
    },
    [onIdsChange, rows],
  );

  return { rows, loading, handleRemove, reload };
}
