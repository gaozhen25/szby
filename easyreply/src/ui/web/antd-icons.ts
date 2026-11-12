// ============================================================
// antd 图标：只按叶子路径引入实际用到的图标
//
// Metro 不做 tree-shaking，`import { X } from "@ant-design/icons"` 会把
// 整包 847 个图标（icons-svg 里 6.6MB 的 path 数据）全部打进首屏 bundle。
// 走 `@ant-design/icons/es/icons/X` 叶子路径后只有这里列出的图标进包。
//
// 新增图标请加在这里，不要在业务文件里直接从 "@ant-design/icons" 导入
// （scripts/check-antd-barrel-imports.js 会在 lint 阶段拦截）。
// ============================================================

import AppstoreOutlined from '@ant-design/icons/es/icons/AppstoreOutlined';
import ArrowLeftOutlined from '@ant-design/icons/es/icons/ArrowLeftOutlined';
import ArrowUpOutlined from '@ant-design/icons/es/icons/ArrowUpOutlined';
import AudioOutlined from '@ant-design/icons/es/icons/AudioOutlined';
import BarChartOutlined from '@ant-design/icons/es/icons/BarChartOutlined';
import BellOutlined from '@ant-design/icons/es/icons/BellOutlined';
import BugOutlined from '@ant-design/icons/es/icons/BugOutlined';
import CalculatorOutlined from '@ant-design/icons/es/icons/CalculatorOutlined';
import CameraOutlined from '@ant-design/icons/es/icons/CameraOutlined';
import CaretRightFilled from '@ant-design/icons/es/icons/CaretRightFilled';
import CheckCircleFilled from '@ant-design/icons/es/icons/CheckCircleFilled';
import CheckCircleOutlined from '@ant-design/icons/es/icons/CheckCircleOutlined';
import CheckOutlined from '@ant-design/icons/es/icons/CheckOutlined';
import ClearOutlined from '@ant-design/icons/es/icons/ClearOutlined';
import ClockCircleOutlined from '@ant-design/icons/es/icons/ClockCircleOutlined';
import CloseCircleFilled from '@ant-design/icons/es/icons/CloseCircleFilled';
import CloseOutlined from '@ant-design/icons/es/icons/CloseOutlined';
import CloudDownloadOutlined from '@ant-design/icons/es/icons/CloudDownloadOutlined';
import CloudOutlined from '@ant-design/icons/es/icons/CloudOutlined';
import CommentOutlined from '@ant-design/icons/es/icons/CommentOutlined';
import CopyOutlined from '@ant-design/icons/es/icons/CopyOutlined';
import DeleteOutlined from '@ant-design/icons/es/icons/DeleteOutlined';
import DownCircleOutlined from '@ant-design/icons/es/icons/DownCircleOutlined';
import DownloadOutlined from '@ant-design/icons/es/icons/DownloadOutlined';
import EditOutlined from '@ant-design/icons/es/icons/EditOutlined';
import EllipsisOutlined from '@ant-design/icons/es/icons/EllipsisOutlined';
import EnvironmentOutlined from '@ant-design/icons/es/icons/EnvironmentOutlined';
import ExclamationCircleOutlined from '@ant-design/icons/es/icons/ExclamationCircleOutlined';
import ExportOutlined from '@ant-design/icons/es/icons/ExportOutlined';
import EyeInvisibleOutlined from '@ant-design/icons/es/icons/EyeInvisibleOutlined';
import EyeOutlined from '@ant-design/icons/es/icons/EyeOutlined';
import FileExcelFilled from '@ant-design/icons/es/icons/FileExcelFilled';
import FileImageFilled from '@ant-design/icons/es/icons/FileImageFilled';
import FileOutlined from '@ant-design/icons/es/icons/FileOutlined';
import FilePdfFilled from '@ant-design/icons/es/icons/FilePdfFilled';
import FilePptFilled from '@ant-design/icons/es/icons/FilePptFilled';
import FileTextOutlined from '@ant-design/icons/es/icons/FileTextOutlined';
import FileWordFilled from '@ant-design/icons/es/icons/FileWordFilled';
import FileZipFilled from '@ant-design/icons/es/icons/FileZipFilled';
import FolderOpenOutlined from '@ant-design/icons/es/icons/FolderOpenOutlined';
import HeartOutlined from '@ant-design/icons/es/icons/HeartOutlined';
import InfoCircleOutlined from '@ant-design/icons/es/icons/InfoCircleOutlined';
import LockOutlined from '@ant-design/icons/es/icons/LockOutlined';
import LogoutOutlined from '@ant-design/icons/es/icons/LogoutOutlined';
import MessageOutlined from '@ant-design/icons/es/icons/MessageOutlined';
import MinusCircleOutlined from '@ant-design/icons/es/icons/MinusCircleOutlined';
import MoonOutlined from '@ant-design/icons/es/icons/MoonOutlined';
import MoreOutlined from '@ant-design/icons/es/icons/MoreOutlined';
import PauseOutlined from '@ant-design/icons/es/icons/PauseOutlined';
import PhoneOutlined from '@ant-design/icons/es/icons/PhoneOutlined';
import PictureOutlined from '@ant-design/icons/es/icons/PictureOutlined';
import PlayCircleFilled from '@ant-design/icons/es/icons/PlayCircleFilled';
import PlusOutlined from '@ant-design/icons/es/icons/PlusOutlined';
import ProfileOutlined from '@ant-design/icons/es/icons/ProfileOutlined';
import ReloadOutlined from '@ant-design/icons/es/icons/ReloadOutlined';
import RightOutlined from '@ant-design/icons/es/icons/RightOutlined';
import RollbackOutlined from '@ant-design/icons/es/icons/RollbackOutlined';
import SearchOutlined from '@ant-design/icons/es/icons/SearchOutlined';
import SendOutlined from '@ant-design/icons/es/icons/SendOutlined';
import SettingOutlined from '@ant-design/icons/es/icons/SettingOutlined';
import ShopOutlined from '@ant-design/icons/es/icons/ShopOutlined';
import SkinOutlined from '@ant-design/icons/es/icons/SkinOutlined';
import SmileOutlined from '@ant-design/icons/es/icons/SmileOutlined';
import SoundOutlined from '@ant-design/icons/es/icons/SoundOutlined';
import StarFilled from '@ant-design/icons/es/icons/StarFilled';
import StarOutlined from '@ant-design/icons/es/icons/StarOutlined';
import StopOutlined from '@ant-design/icons/es/icons/StopOutlined';
import SyncOutlined from '@ant-design/icons/es/icons/SyncOutlined';
import TeamOutlined from '@ant-design/icons/es/icons/TeamOutlined';
import ThunderboltOutlined from '@ant-design/icons/es/icons/ThunderboltOutlined';
import ToolOutlined from '@ant-design/icons/es/icons/ToolOutlined';
import UpOutlined from '@ant-design/icons/es/icons/UpOutlined';
import UserAddOutlined from '@ant-design/icons/es/icons/UserAddOutlined';
import UserOutlined from '@ant-design/icons/es/icons/UserOutlined';
import VideoCameraOutlined from '@ant-design/icons/es/icons/VideoCameraOutlined';
import WalletOutlined from '@ant-design/icons/es/icons/WalletOutlined';
import WifiOutlined from '@ant-design/icons/es/icons/WifiOutlined';

export {
  AppstoreOutlined,
  ArrowLeftOutlined,
  ArrowUpOutlined,
  AudioOutlined,
  BarChartOutlined,
  BellOutlined,
  BugOutlined,
  CalculatorOutlined,
  CameraOutlined,
  CaretRightFilled,
  CheckCircleFilled,
  CheckCircleOutlined,
  CheckOutlined,
  ClearOutlined,
  ClockCircleOutlined,
  CloseCircleFilled,
  CloseOutlined,
  CloudDownloadOutlined,
  CloudOutlined,
  CommentOutlined,
  CopyOutlined,
  DeleteOutlined,
  DownCircleOutlined,
  DownloadOutlined,
  EditOutlined,
  EllipsisOutlined,
  EnvironmentOutlined,
  ExclamationCircleOutlined,
  ExportOutlined,
  EyeInvisibleOutlined,
  EyeOutlined,
  FileExcelFilled,
  FileImageFilled,
  FileOutlined,
  FilePdfFilled,
  FilePptFilled,
  FileTextOutlined,
  FileWordFilled,
  FileZipFilled,
  FolderOpenOutlined,
  HeartOutlined,
  InfoCircleOutlined,
  LockOutlined,
  LogoutOutlined,
  MessageOutlined,
  MinusCircleOutlined,
  MoonOutlined,
  MoreOutlined,
  PauseOutlined,
  PhoneOutlined,
  PictureOutlined,
  PlayCircleFilled,
  PlusOutlined,
  ProfileOutlined,
  ReloadOutlined,
  RightOutlined,
  RollbackOutlined,
  SearchOutlined,
  SendOutlined,
  SettingOutlined,
  ShopOutlined,
  SkinOutlined,
  SmileOutlined,
  SoundOutlined,
  StarFilled,
  StarOutlined,
  StopOutlined,
  SyncOutlined,
  TeamOutlined,
  ThunderboltOutlined,
  ToolOutlined,
  UpOutlined,
  UserAddOutlined,
  UserOutlined,
  VideoCameraOutlined,
  WalletOutlined,
  WifiOutlined,
};
