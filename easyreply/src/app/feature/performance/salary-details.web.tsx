import { webRoute } from '@/lib/web-route';
import NativeSalaryDetails from './salary-details.tsx';

export default webRoute(
  () => import('@/ui/web/pages/SalaryDetailsPage'),
  NativeSalaryDetails,
);
