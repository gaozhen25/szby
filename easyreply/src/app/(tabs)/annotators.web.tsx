import { webRoute } from '@/lib/web-route';
import NativeAnnotators from './annotators.tsx';

export default webRoute(
  () => import('@/ui/web/pages/AnnotatorsPage'),
  NativeAnnotators,
);
