import { webRoute } from '@/lib/web-route';
import NativeIndex from './index.tsx';

export default webRoute(() => import('@/ui/web/pages/IndexPage'), NativeIndex);
