import { webRoute } from '@/lib/web-route';
import NativeRegister from './register.tsx';

export default webRoute(() => import('@/ui/web/pages/RegisterPage'), NativeRegister);
