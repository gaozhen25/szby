// ============================================================
// Native：WebView contentEditable 图文混排（与 Web 行为一致）
// ============================================================
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  type ComponentType,
  type Ref,
} from 'react';
import { Platform, StyleSheet, View } from 'react-native';
import RNWebView from 'react-native-webview';
import { buildWechatEmojiUriMap } from '@/chatMessage/message/chat-emoji-draft';
import type { ChatComposerHandle, ChatComposerProps } from './ChatComposer.types';

export type { ChatComposerHandle, ChatComposerProps };

/** tsc 在非 ios/android 解析时会落到 stub 类型，运行时原生端仍是真实 WebView */
const WebView = RNWebView as unknown as ComponentType<{
  ref?: Ref<{ injectJavaScript: (js: string) => void } | null>;
  originWhitelist?: string[];
  source?: { html: string };
  onMessage?: (e: { nativeEvent: { data: string } }) => void;
  style?: unknown;
  scrollEnabled?: boolean;
  hideKeyboardAccessoryView?: boolean;
  keyboardDisplayRequiresUserAction?: boolean;
  allowsInlineMediaPlayback?: boolean;
  mixedContentMode?: string;
  setSupportMultipleWindows?: boolean;
  androidLayerType?: string;
}>;

const EMOJI_SIZE = 22;

function buildHtml(params: {
  value: string;
  placeholder: string;
  placeholderColor: string;
  textColor: string;
  editable: boolean;
  emojiMap: Record<string, string>;
}): string {
  const { value, placeholder, placeholderColor, textColor, editable, emojiMap } = params;
  const mapJson = JSON.stringify(emojiMap);
  const valueJson = JSON.stringify(value);
  const placeholderJson = JSON.stringify(placeholder);
  return `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no" />
<style>
  html, body {
    margin: 0; padding: 0; background: transparent;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    height: auto; overflow: hidden;
  }
  #wrap {
    position: relative;
  }
  #placeholder {
    position: absolute;
    left: 14px;
    top: 8px;
    right: 14px;
    z-index: 2;
    font-size: 16px;
    line-height: 22px;
    color: ${placeholderColor};
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    pointer-events: none;
    user-select: none;
  }
  #placeholder.hidden { display: none; }
  #editor {
    position: relative;
    z-index: 1;
    min-height: 36px;
    outline: none; font-size: 16px; line-height: 22px;
    padding: 8px 14px; color: ${textColor}; white-space: pre-wrap; word-break: break-word;
    -webkit-user-select: text; user-select: text;
    overflow: hidden; box-sizing: border-box;
  }
  img.qh-emoji {
    width: ${EMOJI_SIZE}px; height: ${EMOJI_SIZE}px;
    vertical-align: middle; display: inline-block; margin: 0 1px;
    object-fit: contain; -webkit-user-drag: none; user-select: none;
  }
</style>
</head>
<body>
<div id="wrap">
  <div id="placeholder"></div>
  <div id="editor" contenteditable="${editable ? 'true' : 'false'}" enterkeyhint="send" inputmode="text"></div>
</div>
<script>
(function() {
  var EMOJI_MAP = ${mapJson};
  var EMOJI_ATTR = 'data-emoji';
  var editor = document.getElementById('editor');
  var placeholderEl = document.getElementById('placeholder');
  var composing = false;
  var lastCompositionEnd = 0;
  var lastValue = '';
  var suppressFocusEvent = false;
  var lastReportedHeight = 0;
  if (placeholderEl) placeholderEl.textContent = ${placeholderJson};

  function syncPlaceholder() {
    if (!placeholderEl) return;
    var empty = !serialize();
    var hide = !empty || composing;
    placeholderEl.classList.toggle('hidden', hide);
  }

  function post(type, payload) {
    window.ReactNativeWebView && window.ReactNativeWebView.postMessage(JSON.stringify({ type: type, payload: payload }));
  }

  function reportHeight() {
    var h = Math.ceil(Math.max(editor.scrollHeight || 0, editor.offsetHeight || 0, 36));
    if (h === lastReportedHeight) return;
    lastReportedHeight = h;
    post('height', h);
  }

  function withSuppressFocus(fn) {
    suppressFocusEvent = true;
    try { fn(); } finally {
      setTimeout(function() { suppressFocusEvent = false; }, 300);
    }
  }

  function createEmojiImg(name) {
    var uri = EMOJI_MAP[name];
    if (!uri) return null;
    var img = document.createElement('img');
    img.setAttribute(EMOJI_ATTR, name);
    img.src = uri;
    img.alt = '[' + name + ']';
    img.className = 'qh-emoji';
    img.width = ${EMOJI_SIZE};
    img.height = ${EMOJI_SIZE};
    img.draggable = false;
    img.contentEditable = 'false';
    return img;
  }

  function serialize() {
    var out = '';
    function walk(node) {
      if (node.nodeType === 3) { out += node.textContent || ''; return; }
      if (node.nodeType !== 1) return;
      var el = node;
      if (el.tagName === 'IMG' && el.getAttribute(EMOJI_ATTR)) {
        out += '[' + el.getAttribute(EMOJI_ATTR) + ']';
        return;
      }
      if (el.tagName === 'BR') { out += '\\n'; return; }
      if ((el.tagName === 'DIV' || el.tagName === 'P') && out.length && !out.endsWith('\\n')) out += '\\n';
      for (var i = 0; i < el.childNodes.length; i++) walk(el.childNodes[i]);
    }
    for (var i = 0; i < editor.childNodes.length; i++) walk(editor.childNodes[i]);
    if (out === '\\n') return '';
    return out;
  }

  function draftToFrag(text) {
    var frag = document.createDocumentFragment();
    if (!text) return frag;
    var parts = text.split(/(\\[[^\\]]+\\])/g).filter(Boolean);
    for (var i = 0; i < parts.length; i++) {
      var part = parts[i];
      var m = part.match(/^\\[([^\\]]+)\\]$/);
      if (m) {
        var img = createEmojiImg(m[1]);
        if (img) { frag.appendChild(img); continue; }
      }
      var lines = part.split('\\n');
      for (var j = 0; j < lines.length; j++) {
        if (j > 0) frag.appendChild(document.createElement('br'));
        if (lines[j]) frag.appendChild(document.createTextNode(lines[j]));
      }
    }
    return frag;
  }

  function placeCaretAtEnd() {
    var sel = window.getSelection();
    if (!sel) return;
    var range = document.createRange();
    range.selectNodeContents(editor);
    range.collapse(false);
    sel.removeAllRanges();
    sel.addRange(range);
  }

  function placeCaretAtStart() {
    var sel = window.getSelection();
    if (!sel) return;
    var range = document.createRange();
    range.selectNodeContents(editor);
    range.collapse(true);
    sel.removeAllRanges();
    sel.addRange(range);
  }

  function setValue(text, opts) {
    var next = text || '';
    if (next === lastValue && !(opts && opts.force)) return;
    var wasFocused = document.activeElement === editor;
    editor.innerHTML = '';
    editor.appendChild(draftToFrag(next));
    lastValue = next;
    syncPlaceholder();
    // 仅在已聚焦且有内容时回置光标；清空草稿时 placeCaretAtEnd 会在 iOS 抢焦点弹键盘
    if (opts && opts.caretEnd && wasFocused && next) placeCaretAtEnd();
    if (!wasFocused) {
      try { editor.blur(); } catch (e) {}
    }
    reportHeight();
  }

  function emitChange() {
    var next = serialize();
    if (next === lastValue) {
      syncPlaceholder();
      return;
    }
    lastValue = next;
    syncPlaceholder();
    post('change', next);
    reportHeight();
  }

  function insertEmoji(name) {
    withSuppressFocus(function() {
      var img = createEmojiImg(name);
      if (!img) return;
      var sel = window.getSelection();
      if (!sel || !sel.rangeCount || !editor.contains(sel.anchorNode)) {
        editor.appendChild(img);
      } else {
        var range = sel.getRangeAt(0);
        range.deleteContents();
        range.insertNode(img);
        range.setStartAfter(img);
        range.collapse(true);
        sel.removeAllRanges();
        sel.addRange(range);
      }
      emitChange();
      editor.blur();
    });
  }

  function backspace() {
    withSuppressFocus(function() {
      var sel = window.getSelection();
      if (sel && sel.rangeCount) {
        var range = sel.getRangeAt(0);
        if (!range.collapsed) {
          range.deleteContents();
          emitChange();
          editor.blur();
          return;
        }
        var sc = range.startContainer, so = range.startOffset, prev = null;
        if (sc.nodeType === 1) prev = sc.childNodes[so - 1];
        else if (sc.nodeType === 3 && so === 0) prev = sc.previousSibling;
        if (prev && prev.nodeType === 1 && prev.tagName === 'IMG' && prev.getAttribute(EMOJI_ATTR)) {
          prev.remove();
          emitChange();
          editor.blur();
          return;
        }
        if (sc.nodeType === 3 && so > 0) {
          var text = sc.textContent || '';
          var before = text.slice(0, so);
          var chars = Array.from(before);
          sc.textContent = chars.slice(0, -1).join('') + text.slice(so);
          var newOffset = Array.from(before).slice(0, -1).join('').length;
          range.setStart(sc, newOffset);
          range.collapse(true);
          sel.removeAllRanges();
          sel.addRange(range);
          emitChange();
          editor.blur();
          return;
        }
      }
      var last = editor.lastChild;
      if (last && last.nodeType === 1 && last.tagName === 'IMG' && last.getAttribute(EMOJI_ATTR)) {
        last.remove();
        emitChange();
        editor.blur();
        return;
      }
      var cur = serialize();
      if (!cur) return;
      var token = cur.match(/\\[[^\\]]+\\]$/);
      var next = token ? cur.slice(0, cur.length - token[0].length) : Array.from(cur).slice(0, -1).join('');
      setValue(next);
      placeCaretAtEnd();
      lastValue = next;
      post('change', next);
      editor.blur();
    });
  }

  editor.addEventListener('input', function() {
    if (composing) return;
    emitChange();
    reportHeight();
  });
  editor.addEventListener('compositionstart', function() {
    composing = true;
    syncPlaceholder();
  });
  editor.addEventListener('compositionend', function() {
    composing = false;
    lastCompositionEnd = Date.now();
    emitChange();
    reportHeight();
  });
  editor.addEventListener('focus', function() {
    if (!serialize()) placeCaretAtStart();
    if (suppressFocusEvent) return;
    post('focus');
  });
  editor.addEventListener('blur', function() {
    if (suppressFocusEvent) return;
    post('blur');
  });
  if (typeof ResizeObserver !== 'undefined') {
    try {
      new ResizeObserver(function() { reportHeight(); }).observe(editor);
    } catch (e) {}
  }
  editor.addEventListener('beforeinput', function(e) {
    if (e.isComposing) composing = true;
  });
  editor.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      var activelyComposing = composing || e.isComposing || e.keyCode === 229;
      if (activelyComposing) return;
      e.preventDefault();
      if (Date.now() - lastCompositionEnd < 15) return;
      emitChange();
      post('submit', serialize());
      var wasFocused = document.activeElement === editor;
      while (editor.firstChild) editor.removeChild(editor.firstChild);
      lastValue = '';
      syncPlaceholder();
      if (wasFocused) placeCaretAtStart();
      return;
    }
    if (e.key === 'Backspace') {
      var sel = window.getSelection();
      if (!sel || !sel.isCollapsed) return;
      var range = sel.getRangeAt(0);
      var sc = range.startContainer, so = range.startOffset, prev = null;
      if (sc.nodeType === 3 && so === 0) prev = sc.previousSibling;
      else if (sc.nodeType === 1) prev = sc.childNodes[so - 1];
      if (prev && prev.nodeType === 1 && prev.tagName === 'IMG' && prev.getAttribute(EMOJI_ATTR)) {
        e.preventDefault();
        prev.remove();
        emitChange();
      }
    }
  });

  setValue(${valueJson});
  syncPlaceholder();
  reportHeight();
  window.__QH_COMPOSER__ = {
    setValue: setValue,
    insertEmoji: insertEmoji,
    backspace: backspace,
    focus: function() {
      editor.focus();
      if (!serialize()) placeCaretAtStart();
      else placeCaretAtEnd();
    },
    blur: function() { editor.blur(); }
  };
  post('ready');
  setTimeout(reportHeight, 0);
})();
</script>
</body>
</html>`;
}

const COMPOSER_HTML_REV = 12;
const COMPOSER_MIN_HEIGHT = 36;
const COMPOSER_MAX_HEIGHT = 120;

export const ChatComposer = forwardRef<ChatComposerHandle, ChatComposerProps>(function ChatComposer(
  {
    value,
    onChangeText,
    onFocus,
    onBlur,
    onSubmitEditing,
    editable = true,
    placeholder = '',
    placeholderTextColor = '#9A9DA3',
    textColor = '#121820',
    backgroundColor = '#F3F4F6',
    style,
  },
  ref,
) {
  const webRef = useRef<{ injectJavaScript: (js: string) => void } | null>(null);
  const readyRef = useRef(false);
  /** 已与 WebView 对齐的草稿，避免父组件回写 value 时重绘 DOM 导致光标跳到开头 */
  const syncedValueRef = useRef(value);
  const [contentHeight, setContentHeight] = useState(COMPOSER_MIN_HEIGHT);
  const emojiMap = useMemo(() => buildWechatEmojiUriMap(), []);

  const html = useMemo(
    () =>
      buildHtml({
        value: '',
        placeholder,
        placeholderColor: placeholderTextColor,
        textColor,
        editable,
        emojiMap,
      }),
    [placeholder, placeholderTextColor, textColor, editable, emojiMap, COMPOSER_HTML_REV],
  );

  const run = useCallback((js: string) => {
    webRef.current?.injectJavaScript(`${js}; true;`);
  }, []);

  useEffect(() => {
    if (!readyRef.current) return;
    // 输入过程中 value 来自 WebView 自己的 change，无需再 setValue（否则会打散光标）
    if (value === syncedValueRef.current) return;
    syncedValueRef.current = value;
    run(
      `window.__QH_COMPOSER__ && window.__QH_COMPOSER__.setValue(${JSON.stringify(value)}, { caretEnd: true })`,
    );
  }, [value, run]);

  useImperativeHandle(
    ref,
    () => ({
      focus: () => run(`window.__QH_COMPOSER__ && window.__QH_COMPOSER__.focus()`),
      blur: () => run(`window.__QH_COMPOSER__ && window.__QH_COMPOSER__.blur()`),
      insertEmoji: (name: string) =>
        run(`window.__QH_COMPOSER__ && window.__QH_COMPOSER__.insertEmoji(${JSON.stringify(name)})`),
      backspace: () => run(`window.__QH_COMPOSER__ && window.__QH_COMPOSER__.backspace()`),
    }),
    [run],
  );

  const onMessage = useCallback(
    (e: { nativeEvent: { data: string } }) => {
      try {
        const msg = JSON.parse(e.nativeEvent.data) as {
          type: string;
          payload?: string | number;
        };
        switch (msg.type) {
          case 'ready':
            readyRef.current = true;
            syncedValueRef.current = value;
            run(
              `window.__QH_COMPOSER__ && window.__QH_COMPOSER__.setValue(${JSON.stringify(value)}, { caretEnd: true })`,
            );
            break;
          case 'change': {
            const next = String(msg.payload ?? '');
            syncedValueRef.current = next;
            onChangeText(next);
            break;
          }
          case 'height': {
            const raw = typeof msg.payload === 'number' ? msg.payload : Number(msg.payload);
            if (!Number.isFinite(raw)) break;
            const next = Math.min(
              COMPOSER_MAX_HEIGHT,
              Math.max(COMPOSER_MIN_HEIGHT, Math.ceil(raw)),
            );
            setContentHeight((prev: number) => (prev === next ? prev : next));
            break;
          }
          case 'focus':
            onFocus?.();
            break;
          case 'blur':
            onBlur?.();
            break;
          case 'submit':
            onSubmitEditing?.(typeof msg.payload === 'string' ? msg.payload : '');
            break;
          default:
            break;
        }
      } catch {
        // ignore
      }
    },
    [onBlur, onChangeText, onFocus, onSubmitEditing, run, value],
  );

  const atMaxHeight = contentHeight >= COMPOSER_MAX_HEIGHT;

  return (
    <View style={[styles.wrap, { backgroundColor, height: contentHeight }, style as object]}>
      <WebView
        ref={webRef}
        originWhitelist={['*']}
        source={{ html }}
        onMessage={onMessage}
        style={[styles.webview, { backgroundColor, height: contentHeight }]}
        scrollEnabled={atMaxHeight}
        hideKeyboardAccessoryView
        keyboardDisplayRequiresUserAction={false}
        allowsInlineMediaPlayback
        mixedContentMode="always"
        setSupportMultipleWindows={false}
        androidLayerType={Platform.OS === 'android' ? 'hardware' : undefined}
      />
    </View>
  );
});

const styles = StyleSheet.create({
  wrap: {
    flex: 1,
    borderRadius: 20,
    overflow: 'hidden',
  },
  webview: {
    backgroundColor: 'transparent',
    width: '100%',
  },
});

export default ChatComposer;
