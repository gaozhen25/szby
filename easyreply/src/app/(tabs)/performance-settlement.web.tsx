import { webRoute } from '@/lib/web-route';
import NativePerformanceSettlement from './performance-settlement.tsx';

export default webRoute(
  () => import('@/ui/web/pages/PerformanceSettlementPage'),
  NativePerformanceSettlement,
);
