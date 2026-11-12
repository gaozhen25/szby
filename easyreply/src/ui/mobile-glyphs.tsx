import { Feather, MaterialCommunityIcons } from '@expo/vector-icons';
import { StyleSheet, View } from 'react-native';

type GlyphProps = {
  size?: number;
  color?: string;
};

/** 移动端搜索框：细线放大镜，小尺寸下比 AntDesign / Ionicons 更清晰 */
export function SearchInputGlyph({ size = 17, color = '#7A828C' }: GlyphProps) {
  return (
    <View style={styles.searchWrap}>
      <Feather name="search" size={size} color={color} allowFontScaling={false} />
    </View>
  );
}

/** TabBar「我的」：空心人形，与其它 Tab 线框图标风格一致 */
export function ProfileTabGlyph({ size = 22, color = '#121820' }: GlyphProps) {
  return (
    <View style={styles.tabWrap}>
      <MaterialCommunityIcons
        name="account-outline"
        size={size}
        color={color}
        allowFontScaling={false}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  searchWrap: {
    width: 20,
    height: 20,
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },
  tabWrap: {
    width: 28,
    height: 28,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
