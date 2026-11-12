import { AntDesign, Ionicons } from '@expo/vector-icons';
import type { ComponentProps } from 'react';

/** 原生端：用 Ant Design 图标字体，组件名与 `@ant-design/icons` 对齐（Web 见 `antd-icons.web.tsx`）。 */

type Glyph = ComponentProps<typeof AntDesign>['name'];
type IonGlyph = ComponentProps<typeof Ionicons>['name'];

export type AntdIconProps = {
  size?: number;
  color?: string;
  style?: { fontSize?: number; color?: string };
};

function wrap(name: Glyph) {
  return function AntdIcon({ size, color, style }: AntdIconProps) {
    const fontSize = size ?? (typeof style?.fontSize === 'number' ? style.fontSize : 16);
    const tint = color ?? (typeof style?.color === 'string' ? style.color : undefined);
    return <AntDesign name={name} size={fontSize} color={tint} />;
  };
}

/** Ionicons 线框：小尺寸更清晰，对齐 Web 端 Outlined 风格 */
function wrapIon(name: IonGlyph) {
  return function IonIcon({ size, color, style }: AntdIconProps) {
    const fontSize = size ?? (typeof style?.fontSize === 'number' ? style.fontSize : 16);
    const tint = color ?? (typeof style?.color === 'string' ? style.color : undefined);
    return <Ionicons name={name} size={fontSize} color={tint} />;
  };
}

export const AppstoreOutlined = wrap('appstore');
export const ArrowLeftOutlined = wrap('arrow-left');
export const ArrowUpOutlined = wrap('arrow-up');
export const AudioOutlined = wrap('audio');
export const BarChartOutlined = wrap('bar-chart');
export const BellOutlined = wrap('bell');
export const BugOutlined = wrap('bug');
export const CalculatorOutlined = wrap('calculator');
export const CameraOutlined = wrap('camera');
export const CaretRightFilled = wrap('caret-right');
export const CheckCircleFilled = wrap('check-circle');
export const CheckCircleOutlined = wrap('check-circle');
export const CheckOutlined = wrap('check');
export const ClearOutlined = wrap('clear');
export const ClockCircleOutlined = wrap('clock-circle');
export const CloseCircleFilled = wrap('close-circle');
export const CloseOutlined = wrap('close');
export const CloudDownloadOutlined = wrap('cloud-download');
export const CloudOutlined = wrap('cloud');
export const CommentOutlined = wrap('comment');
export const CopyOutlined = wrap('copy');
export const DeleteOutlined = wrap('delete');
export const DownloadOutlined = wrap('download');
export const DownCircleOutlined = wrap('down-circle');
export const EditOutlined = wrap('edit');
export const EnvironmentOutlined = wrap('environment');
export const ExclamationCircleOutlined = wrap('exclamation-circle');
export const ExportOutlined = wrap('export');
export const EyeInvisibleOutlined = wrap('eye-invisible');
export const EyeOutlined = wrap('eye');
export const FileOutlined = wrap('file');
export const FileTextOutlined = wrap('file-text');
export const FolderOpenOutlined = wrap('folder-open');
export const HeartOutlined = wrap('heart');
export const InfoCircleOutlined = wrap('info-circle');
export const LockOutlined = wrap('lock');
export const LogoutOutlined = wrap('logout');
export const MessageOutlined = wrap('message');
export const MinusCircleOutlined = wrap('minus-circle');
export const MoonOutlined = wrap('moon');
export const MoreOutlined = wrap('ellipsis');
export const PauseOutlined = wrap('pause');
export const PhoneOutlined = wrap('phone');
export const PictureOutlined = wrap('picture');
export const PlayCircleFilled = wrap('play-circle');
export const PlusOutlined = wrap('plus');
export const ProfileOutlined = wrap('profile');
export const ReloadOutlined = wrap('reload');
export const RightOutlined = wrap('right');
export const RollbackOutlined = wrap('rollback');
export const SearchOutlined = wrapIon('search-outline');
export const SendOutlined = wrap('send');
export const ShopOutlined = wrap('shop');
export const SmileOutlined = wrap('smile');
export const SoundOutlined = wrap('sound');
export const StarFilled = wrap('star');
export const StarOutlined = wrap('star');
export const StopOutlined = wrap('stop');
export const SyncOutlined = wrap('sync');
export const TeamOutlined = wrap('team');
export const ThunderboltOutlined = wrap('thunderbolt');
export const ToolOutlined = wrap('tool');
export const UserAddOutlined = wrap('user-add');
export const UserOutlined = wrapIon('person-outline');
export const VideoCameraOutlined = wrap('video-camera');
export const WalletOutlined = wrap('wallet');
export const WifiOutlined = wrap('wifi');
