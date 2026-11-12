import { webRoute } from '@/lib/web-route';
import NativeActorInfo from './[id].tsx';

export default webRoute(
  () => import('@/ui/web/pages/ActorInfoPage'),
  NativeActorInfo,
);
