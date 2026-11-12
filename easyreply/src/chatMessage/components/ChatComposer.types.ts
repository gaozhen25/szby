import type { StyleProp, TextStyle, ViewStyle } from 'react-native';

export type ChatComposerHandle = {
  focus: () => void;
  blur: () => void;
  insertEmoji: (name: string) => void;
  backspace: () => void;
};

export type ChatComposerProps = {
  value: string;
  onChangeText: (text: string) => void;
  onFocus?: () => void;
  onBlur?: () => void;
  onSubmitEditing?: (text: string) => void;
  editable?: boolean;
  placeholder?: string;
  placeholderTextColor?: string;
  maxLength?: number;
  textColor?: string;
  backgroundColor?: string;
  style?: StyleProp<ViewStyle | TextStyle>;
};
