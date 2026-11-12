import { webRoute } from '@/lib/web-route';
import NativeCustomStickers from './custom-stickers.tsx';

export default webRoute(
  () => import('@/ui/web/pages/CustomStickersPage'),
  NativeCustomStickers,
);
