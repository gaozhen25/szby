import { ActivityIndicator, Platform, View, type ViewStyle } from 'react-native';

import { webColor } from '@/ui/web/theme';

/** Web 路由 / Suspense fallback：相对视口居中，避免父级高度为 0 时 spinner 贴顶被裁半 */
export const webFullscreenLoaderStyle: ViewStyle = {
  flex: 1,
  width: '100%',
  alignItems: 'center',
  justifyContent: 'center',
  backgroundColor: webColor.bg,
  ...(Platform.OS === 'web'
    ? ({
        position: 'fixed',
        top: 0,
        right: 0,
        bottom: 0,
        left: 0,
        zIndex: 10,
      } as ViewStyle)
    : null),
};

export function WebFullscreenLoader() {
  return (
    <View style={webFullscreenLoaderStyle} accessibilityRole="progressbar">
      <ActivityIndicator size="large" color={webColor.primary} />
    </View>
  );
}
