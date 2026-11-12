import { webRoute } from '@/lib/web-route';
import NativeChat from './chat.tsx';

export default webRoute(
  () => import('@/ui/web/pages/ConversationListPage'),
  NativeChat,
);
