import { webRoute } from '@/lib/web-route';
import NativeMyFavorites from './my-favorites.tsx';

export default webRoute(
  () => import('@/ui/web/pages/MyFavoritesRedirect'),
  NativeMyFavorites,
);
