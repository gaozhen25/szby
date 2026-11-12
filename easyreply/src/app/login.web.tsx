import { webRoute } from '@/lib/web-route';
import NativeLogin from './login.tsx';

export default webRoute(() => import('@/ui/web/pages/LoginPage'), NativeLogin);
