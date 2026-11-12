export type PrependLock = {
  /** 加载前当前页顶部那条消息 */
  anchorKey: string;
  /** 该消息顶部相对列表可见区域顶部的像素 */
  viewportY: number;
  /** 插入前的内容高度 / 滚动位置：Web 用差值钉住，不依赖虚拟列表估算 */
  prevScrollHeight: number;
  prevScrollTop: number;
};

export type ChatMessageListHandle = {
  scrollToEnd: (opts: { animated: boolean }) => void;
  /**
   * prepend 更早消息前调用：Web 快照高度差钉住；Android 倒序列表无需处理。
   */
  prepareForPrepend: () => void;
  /** 请求一开始就冻住惯性，避免 fetch 期间列表继续滑 */
  lockScrollForPrepend: () => void;
  /** 没有插入数据时解开冻结 */
  releasePrependLock: () => void;
  /** 首屏加载完成：等内容真正渲染出高度后再滚一次，避免 Android 首次不在底部 */
  markInitialScrollPending: () => void;
  /** 本地缓存首屏已展示：跳过 loading 遮罩，直接滚到底 */
  revealFromCache: () => void;
};

/** 视图适配：量像素 / 改 scroll，算法不直接碰 FlatList / DOM */
export type ChatListScrollPort = {
  readNode: () => HTMLElement | null;
  scrollToEnd: (opts: { animated: boolean }) => void;
  scrollToY: (y: number) => void;
  measureAnchorViewportY: (anchorKey: string) => number | null;
  /** Web Listy：prepend 后将锚点消息钉回加载前的视口位置 */
  scrollAnchorToViewport?: (anchorKey: string, viewportY: number) => void;
};
