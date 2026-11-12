import { webRoute } from '@/lib/web-route';
import NativePerformance from './performance.tsx';

export default webRoute(
  () => import('@/ui/web/pages/PerformancePage'),
  NativePerformance,
);
