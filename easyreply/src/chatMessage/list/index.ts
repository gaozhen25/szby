/**
 * 聊天列表交互：滚动钉住、冻惯性、首屏揭示。
 * 视图（FlatList / ScrollView）只提供 ChatListScrollPort。
 */
export {
  LIST_PADDING_TOP,
  LOAD_MORE_HEADER_HEIGHT,
} from './constants';
export type { ChatListScrollPort, ChatMessageListHandle, PrependLock } from './types';
export { asRectNode, getScrollNode } from './scroll-dom';
export { useChatListController } from './useChatListController';
