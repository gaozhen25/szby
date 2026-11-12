import { webRoute } from '@/lib/web-route';
import NativeAssignActors from './assign-actors.tsx';

export default webRoute(
  () => import('@/ui/web/pages/AssignActorsPage'),
  NativeAssignActors,
);
