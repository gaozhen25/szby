import React, { useCallback, useRef } from 'react';
import { Animated, Pressable, StyleSheet } from 'react-native';
import type { BottomTabBarButtonProps } from '@react-navigation/bottom-tabs';

/** Tab 点击时图标回弹反馈（用 RN Pressable，避免 PlatformPressable 依赖导航 theme） */
export function BounceTabBarButton({
  children,
  style,
  onPress,
  onPressIn,
  onLongPress,
  accessibilityRole,
  accessibilityState,
  accessibilityLabel,
  testID,
}: BottomTabBarButtonProps) {
  const scale = useRef(new Animated.Value(1)).current;

  const playBounce = useCallback(() => {
    scale.setValue(1);
    Animated.sequence([
      Animated.timing(scale, {
        toValue: 0.88,
        duration: 70,
        useNativeDriver: true,
      }),
      Animated.spring(scale, {
        toValue: 1,
        useNativeDriver: true,
        speed: 36,
        bounciness: 6,
      }),
    ]).start();
  }, [scale]);

  const childList = React.Children.toArray(children);

  return (
    <Pressable
      accessibilityRole={accessibilityRole ?? 'button'}
      accessibilityState={accessibilityState}
      accessibilityLabel={accessibilityLabel}
      testID={testID}
      onPress={onPress}
      onLongPress={onLongPress}
      style={[styles.tabButton, style]}
      onPressIn={(e) => {
        playBounce();
        onPressIn?.(e);
      }}
    >
      {childList.map((child, index) => {
        if (index === 0) {
          return (
            <Animated.View key="tab-icon" style={{ transform: [{ scale }] }}>
              {child}
            </Animated.View>
          );
        }
        return child;
      })}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  tabButton: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
});

export default BounceTabBarButton;
