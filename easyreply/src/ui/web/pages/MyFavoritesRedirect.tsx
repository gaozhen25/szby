import { Redirect } from 'expo-router';

/** 桌面 Web：原收藏页路由重定向到会话列表并打开收藏弹窗 */
export default function MyFavoritesRedirect() {
  return <Redirect href="/(tabs)/chat?favorites=1" />;
}
