import React from "react";
import { Platform, StyleSheet, View, type ViewProps } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useTheme } from "@/design/theme-context";

type Props = ViewProps & {
  children: React.ReactNode;
  safeAreaTop?: boolean;
  /** 默认 true；聊天页等需纯色底时传 false，避免光晕影响气泡观感 */
  showOrbs?: boolean;
};

/** Full-screen base with soft celadon wash orbs for depth (no extra native deps). */
export function ScreenCanvas({ children, safeAreaTop = true, showOrbs = true, style, ...rest }: Props) {
  const theme = useTheme();

  return (
    <View style={[styles.root, { backgroundColor: theme.bg }, style]} {...rest}>
      {showOrbs ? (
        <View pointerEvents="none" style={StyleSheet.absoluteFill}>
          <View
            style={[
              styles.orb,
              {
                top: -72,
                right: -56,
                width: 240,
                height: 240,
                borderRadius: 120,
                backgroundColor: theme.primarySoft,
                opacity: 0.55,
              },
            ]}
          />
          <View
            style={[
              styles.orb,
              {
                bottom: -40,
                left: -64,
                width: 200,
                height: 200,
                borderRadius: 100,
                backgroundColor: theme.wash2,
                opacity: 0.45,
              },
            ]}
          />
          <View
            style={[
              styles.orb,
              {
                top: "38%",
                left: -80,
                width: 160,
                height: 160,
                borderRadius: 80,
                backgroundColor: theme.wash1,
                opacity: 0.35,
              },
            ]}
          />
        </View>
      ) : null}
      <SafeAreaView style={styles.content} edges={safeAreaTop ? ["top"] : []}>
        {children}
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    overflow: "hidden",
    ...(Platform.OS === "web" ? { minHeight: 0, width: "100%" as const } : null),
  },
  content: {
    flex: 1,
    overflow: "hidden",
    ...(Platform.OS === "web" ? { minHeight: 0, width: "100%" as const } : null),
  },
  orb: {
    position: "absolute",
  },
});
