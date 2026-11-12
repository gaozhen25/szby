// ============================================================
// Web：contentEditable 图文混排输入（微信表情始终以图片展示）
// 底层 value 仍是 [名称] token 文本，发送协议不变
// ============================================================
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
} from 'react';
import { StyleSheet, View } from 'react-native';
import {
  appendEmojiToken,
  backspaceEmojiDraft,
  getWechatEmojiUri,
} from '@/chatMessage/message/chat-emoji-draft';
import { getWechatEmojiSource } from '@/core/im/wechat-emoji';
import type { ChatComposerHandle, ChatComposerProps } from './ChatComposer.types';

export type { ChatComposerHandle, ChatComposerProps };

const EMOJI_SIZE = 22;
const EMOJI_ATTR = 'data-emoji';

function createEmojiImg(name: string): HTMLImageElement | null {
  if (!getWechatEmojiSource(name)) return null;
  const uri = getWechatEmojiUri(name);
  if (!uri) return null;
  const img = document.createElement('img');
  img.setAttribute(EMOJI_ATTR, name);
  img.src = uri;
  img.alt = `[${name}]`;
  img.className = 'qh-chat-emoji';
  img.width = EMOJI_SIZE;
  img.height = EMOJI_SIZE;
  img.draggable = false;
  img.contentEditable = 'false';
  Object.assign(img.style, {
    width: `${EMOJI_SIZE}px`,
    height: `${EMOJI_SIZE}px`,
    verticalAlign: 'middle',
    display: 'inline-block',
    margin: '0 1px',
    objectFit: 'contain',
    userSelect: 'none',
  });
  return img;
}

function serializeEditor(root: HTMLElement): string {
  let out = '';
  const walk = (node: Node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      out += node.textContent ?? '';
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return;
    const el = node as HTMLElement;
    if (el.tagName === 'IMG' && el.getAttribute(EMOJI_ATTR)) {
      out += `[${el.getAttribute(EMOJI_ATTR)}]`;
      return;
    }
    if (el.tagName === 'BR') {
      out += '\n';
      return;
    }
    if (el.tagName === 'DIV' || el.tagName === 'P') {
      // 块级换行：非首块前补换行
      if (out.length > 0 && !out.endsWith('\n')) out += '\n';
    }
    for (const child of Array.from(el.childNodes)) walk(child);
  };
  for (const child of Array.from(root.childNodes)) walk(child);
  // contentEditable 空态可能残留 <br>
  if (out === '\n') return '';
  return out;
}

function draftToDocumentFragment(text: string): DocumentFragment {
  const frag = document.createDocumentFragment();
  if (!text) return frag;
  const parts = text.split(/(\[[^\]]+\])/g).filter((p) => p.length > 0);
  for (const part of parts) {
    const m = part.match(/^\[([^\]]+)\]$/);
    if (m) {
      const img = createEmojiImg(m[1]);
      if (img) {
        frag.appendChild(img);
        continue;
      }
    }
    // 处理换行
    const lines = part.split('\n');
    lines.forEach((line, i) => {
      if (i > 0) frag.appendChild(document.createElement('br'));
      if (line) frag.appendChild(document.createTextNode(line));
    });
  }
  return frag;
}

function placeCaretAtEnd(el: HTMLElement) {
  const sel = window.getSelection();
  if (!sel) return;
  const range = document.createRange();
  range.selectNodeContents(el);
  range.collapse(false);
  sel.removeAllRanges();
  sel.addRange(range);
}

function placeCaretAtStart(el: HTMLElement) {
  const sel = window.getSelection();
  if (!sel) return;
  const range = document.createRange();
  range.selectNodeContents(el);
  range.collapse(true);
  sel.removeAllRanges();
  sel.addRange(range);
}

function insertNodeAtCaret(editor: HTMLElement, node: Node) {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0 || !editor.contains(sel.anchorNode)) {
    editor.appendChild(node);
    placeCaretAtEnd(editor);
    return;
  }
  const range = sel.getRangeAt(0);
  range.deleteContents();
  range.insertNode(node);
  range.setStartAfter(node);
  range.collapse(true);
  sel.removeAllRanges();
  sel.addRange(range);
}

function deleteBackwardAtCaret(editor: HTMLElement): boolean {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0) return false;
  const range = sel.getRangeAt(0);

  if (!range.collapsed) {
    range.deleteContents();
    return true;
  }

  // 光标紧跟表情图：整图删除
  const { startContainer, startOffset } = range;
  if (startContainer.nodeType === Node.ELEMENT_NODE) {
    const el = startContainer as HTMLElement;
    const prev = el.childNodes[startOffset - 1] as HTMLElement | undefined;
    if (prev?.nodeType === Node.ELEMENT_NODE && prev.tagName === 'IMG' && prev.getAttribute(EMOJI_ATTR)) {
      prev.remove();
      return true;
    }
  }
  if (startContainer.nodeType === Node.TEXT_NODE && startOffset === 0) {
    const prev = startContainer.previousSibling as HTMLElement | null;
    if (prev?.nodeType === Node.ELEMENT_NODE && prev.tagName === 'IMG' && prev.getAttribute(EMOJI_ATTR)) {
      prev.remove();
      return true;
    }
  }
  if (startContainer.nodeType === Node.TEXT_NODE && startOffset > 0) {
    const text = startContainer.textContent ?? '';
    const before = text.slice(0, startOffset);
    const chars = Array.from(before);
    if (chars.length === 0) return false;
    const next = chars.slice(0, -1).join('') + text.slice(startOffset);
    startContainer.textContent = next;
    const newOffset = Array.from(before).slice(0, -1).join('').length;
    range.setStart(startContainer, newOffset);
    range.collapse(true);
    sel.removeAllRanges();
    sel.addRange(range);
    return true;
  }

  // 退到编辑器末尾时的兜底
  const last = editor.lastChild as HTMLElement | null;
  if (last?.nodeType === Node.ELEMENT_NODE && last.tagName === 'IMG' && last.getAttribute(EMOJI_ATTR)) {
    last.remove();
    return true;
  }
  return false;
}

const WebChatComposer = forwardRef<ChatComposerHandle, ChatComposerProps>(function WebChatComposer(
  {
    value,
    onChangeText,
    onFocus,
    onBlur,
    onSubmitEditing,
    editable = true,
    placeholder = '',
    placeholderTextColor = '#BDC7D2',
    maxLength = 5000,
    textColor = '#333333',
    backgroundColor = '#EDF0F4',
    style,
  },
  ref,
) {
  const editorRef = useRef<HTMLDivElement | null>(null);
  const composingRef = useRef(false);
  /** compositionend 时刻：极短窗口内吞掉同一次 Enter 的重复 keydown */
  const lastCompositionEndRef = useRef(0);
  const onSubmitEditingRef = useRef(onSubmitEditing);
  const onChangeTextRef = useRef(onChangeText);
  const lastValueRef = useRef(value);
  const savedRangeRef = useRef<Range | null>(null);
  const skipNextFocusSaveRef = useRef(false);
  const [isEmpty, setIsEmpty] = useState(() => !value);
  const [isComposing, setIsComposing] = useState(false);

  const syncEmptyClass = useCallback((empty: boolean) => {
    setIsEmpty(empty);
    editorRef.current?.classList.toggle('is-empty', empty);
  }, []);

  const emitChange = useCallback(() => {
    const editor = editorRef.current;
    if (!editor) return;
    let next = serializeEditor(editor);
    if (next.length > maxLength) {
      next = next.slice(0, maxLength);
      editor.innerHTML = '';
      editor.appendChild(draftToDocumentFragment(next));
      placeCaretAtEnd(editor);
    }
    lastValueRef.current = next;
    syncEmptyClass(next.length === 0);
    onChangeText(next);
  }, [maxLength, onChangeText, syncEmptyClass]);

  const restoreFromValue = useCallback((text: string) => {
    const editor = editorRef.current;
    if (!editor) return;
    editor.innerHTML = '';
    editor.appendChild(draftToDocumentFragment(text));
    lastValueRef.current = text;
    syncEmptyClass(text.length === 0);
  }, [syncEmptyClass]);

  /** 发送后原地清空，避免受控 value="" 重绘 contentEditable 导致失焦 */
  const clearEditorInPlace = useCallback(() => {
    const editor = editorRef.current;
    if (!editor) return;
    editor.innerHTML = '';
    lastValueRef.current = '';
    syncEmptyClass(true);
    if (document.activeElement === editor) {
      placeCaretAtStart(editor);
      return;
    }
    skipNextFocusSaveRef.current = true;
    editor.focus();
    placeCaretAtStart(editor);
  }, [syncEmptyClass]);

  // 外部清空 / 受控同步（避免输入过程中打断光标与 IME）
  useLayoutEffect(() => {
    if (composingRef.current) return;
    if (value === lastValueRef.current) return;
    restoreFromValue(value);
  }, [value, restoreFromValue]);

  const saveSelection = useCallback(() => {
    const editor = editorRef.current;
    const sel = window.getSelection();
    if (!editor || !sel || sel.rangeCount === 0) return;
    const range = sel.getRangeAt(0);
    if (editor.contains(range.commonAncestorContainer)) {
      savedRangeRef.current = range.cloneRange();
    }
  }, []);

  const restoreSelection = useCallback(() => {
    const editor = editorRef.current;
    const range = savedRangeRef.current;
    const sel = window.getSelection();
    if (!editor || !range || !sel) {
      if (editor) placeCaretAtEnd(editor);
      return;
    }
    try {
      sel.removeAllRanges();
      sel.addRange(range);
    } catch {
      placeCaretAtEnd(editor);
    }
  }, []);

  useImperativeHandle(
    ref,
    () => ({
      focus: () => {
        const editor = editorRef.current;
        if (!editor) return;
        // focus() 会把光标甩到开头；onFocus 的 saveSelection 会覆盖「插在表情后」的选区
        let preserved: Range | null = null;
        try {
          preserved = savedRangeRef.current?.cloneRange() ?? null;
        } catch {
          preserved = null;
        }
        skipNextFocusSaveRef.current = true;
        editor.focus();
        if (preserved) savedRangeRef.current = preserved;
        restoreSelection();
      },
      blur: () => {
        editorRef.current?.blur();
      },
      insertEmoji: (name: string) => {
        const editor = editorRef.current;
        if (!editor || !editable) return;
        const img = createEmojiImg(name);
        if (!img) return;
        const nextLen = appendEmojiToken(serializeEditor(editor), name).length;
        if (nextLen > maxLength) return;

        // 尽量不抢焦点，避免收起表情面板 / 弹出系统键盘
        const sel = window.getSelection();
        const hasLiveCaret =
          !!sel && sel.rangeCount > 0 && !!sel.anchorNode && editor.contains(sel.anchorNode);

        if (hasLiveCaret) {
          insertNodeAtCaret(editor, img);
        } else if (savedRangeRef.current) {
          try {
            sel?.removeAllRanges();
            sel?.addRange(savedRangeRef.current);
            insertNodeAtCaret(editor, img);
          } catch {
            editor.appendChild(img);
          }
        } else {
          editor.appendChild(img);
        }

        try {
          const range = document.createRange();
          range.setStartAfter(img);
          range.collapse(true);
          savedRangeRef.current = range.cloneRange();
          sel?.removeAllRanges();
          sel?.addRange(range);
        } catch {
          // ignore
        }
        emitChange();
      },
      backspace: () => {
        const editor = editorRef.current;
        if (!editor || !editable) return;
        const sel = window.getSelection();
        const hasLiveCaret =
          !!sel && sel.rangeCount > 0 && !!sel.anchorNode && editor.contains(sel.anchorNode);
        if (hasLiveCaret) {
          // keep
        } else if (savedRangeRef.current) {
          try {
            sel?.removeAllRanges();
            sel?.addRange(savedRangeRef.current);
          } catch {
            // fall through
          }
        }

        const deleted = deleteBackwardAtCaret(editor);
        if (!deleted) {
          const next = backspaceEmojiDraft(serializeEditor(editor));
          restoreFromValue(next);
          onChangeText(next);
          return;
        }
        emitChange();
        saveSelection();
      },
    }),
    [editable, emitChange, maxLength, onChangeText, restoreFromValue, restoreSelection, saveSelection],
  );

  useEffect(() => {
    onSubmitEditingRef.current = onSubmitEditing;
  }, [onSubmitEditing]);

  useEffect(() => {
    onChangeTextRef.current = onChangeText;
  }, [onChangeText]);

  const emitChangeRef = useRef(emitChange);
  useEffect(() => {
    emitChangeRef.current = emitChange;
  }, [emitChange]);

  // 原生 capture：RN Web 合成事件的 isComposing 不可靠，且 IME 确认 Enter 可能早于 draft 同步
  useEffect(() => {
    const editor = editorRef.current;
    if (!editor) return;

    const onBeforeInput = (e: InputEvent) => {
      if (e.isComposing) composingRef.current = true;
    };

    const onKeyDownCapture = (e: KeyboardEvent) => {
      if (e.key !== 'Enter' || e.shiftKey) return;

      const activelyComposing = composingRef.current || e.isComposing || e.keyCode === 229;
      if (activelyComposing) return;

      e.preventDefault();
      e.stopImmediatePropagation();

      // 组字刚结束几毫秒内的重复 keydown（同一次 Enter），只消化不发送
      if (Date.now() - lastCompositionEndRef.current < 15) return;

      const editor = editorRef.current;
      if (!editor) return;

      const text = serializeEditor(editor);
      lastValueRef.current = text;
      syncEmptyClass(text.length === 0);
      onChangeTextRef.current(text);

      const payload = text.trim();
      if (!payload) return;

      onSubmitEditingRef.current?.(payload);
      clearEditorInPlace();
    };

    editor.addEventListener('beforeinput', onBeforeInput);
    editor.addEventListener('keydown', onKeyDownCapture, true);
    return () => {
      editor.removeEventListener('beforeinput', onBeforeInput);
      editor.removeEventListener('keydown', onKeyDownCapture, true);
    };
  }, [clearEditorInPlace, syncEmptyClass]);

  useEffect(() => {
    const id = 'qh-chat-composer-css-v3';
    if (document.getElementById(id)) return;
    document.getElementById('qh-chat-composer-css')?.remove();
    document.getElementById('qh-chat-composer-css-v2')?.remove();
    const el = document.createElement('style');
    el.id = id;
    el.textContent = composerCss;
    document.head.appendChild(el);
  }, []);

  useEffect(() => {
    const editor = editorRef.current;
    if (!editor) return;
    restoreFromValue(value);
    // 仅挂载时灌一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const showPlaceholder = Boolean(placeholder) && isEmpty && !isComposing;

  return (
    <View style={[styles.wrap, { backgroundColor }, style as object]}>
      {showPlaceholder ? (
        <div
          aria-hidden
          className="qh-chat-composer-placeholder"
          style={{
            ...webPlaceholderStyle,
            color: placeholderTextColor,
          }}
        >
          {placeholder}
        </div>
      ) : null}
      <div
        ref={editorRef}
        role="textbox"
        aria-multiline="true"
        aria-placeholder={placeholder}
        contentEditable={editable}
        enterKeyHint={"send" as 'send'}
        inputMode="text"
        suppressContentEditableWarning
        className="qh-chat-composer is-empty"
        style={{
          ...webEditorStyle,
          color: textColor,
          backgroundColor,
          opacity: editable ? 1 : 0.55,
        }}
        onInput={() => {
          if (composingRef.current) return;
          emitChange();
          saveSelection();
        }}
        onCompositionStart={() => {
          composingRef.current = true;
          setIsComposing(true);
        }}
        onCompositionEnd={() => {
          composingRef.current = false;
          lastCompositionEndRef.current = Date.now();
          setIsComposing(false);
          emitChange();
          saveSelection();
        }}
        onFocus={() => {
          onFocus?.();
          const editor = editorRef.current;
          if (skipNextFocusSaveRef.current) {
            skipNextFocusSaveRef.current = false;
            return;
          }
          if (editor && serializeEditor(editor).length === 0) {
            placeCaretAtStart(editor);
          }
          saveSelection();
        }}
        onBlur={() => {
          saveSelection();
          onBlur?.();
        }}
        onKeyDown={(e) => {
          if (e.key === 'Backspace') {
            const sel = window.getSelection();
            if (sel && sel.isCollapsed) {
              const editor = editorRef.current;
              if (!editor) return;
              // 让我们的整图删除逻辑优先于浏览器默认（部分浏览器会拆坏结构）
              const { startContainer, startOffset } = sel.getRangeAt(0);
              const prevSibling =
                startContainer.nodeType === Node.TEXT_NODE && startOffset === 0
                  ? startContainer.previousSibling
                  : startContainer.nodeType === Node.ELEMENT_NODE
                    ? (startContainer as HTMLElement).childNodes[startOffset - 1]
                    : null;
              if (
                prevSibling &&
                prevSibling.nodeType === Node.ELEMENT_NODE &&
                (prevSibling as HTMLElement).tagName === 'IMG' &&
                (prevSibling as HTMLElement).getAttribute(EMOJI_ATTR)
              ) {
                e.preventDefault();
                (prevSibling as HTMLElement).remove();
                emitChange();
                saveSelection();
              }
            }
          }
        }}
        onPaste={(e) => {
          e.preventDefault();
          const text = e.clipboardData.getData('text/plain');
          if (!text) return;
          const sel = window.getSelection();
          if (!sel || sel.rangeCount === 0) return;
          const range = sel.getRangeAt(0);
          range.deleteContents();
          const frag = draftToDocumentFragment(text);
          const last = frag.lastChild;
          range.insertNode(frag);
          if (last) {
            range.setStartAfter(last);
            range.collapse(true);
            sel.removeAllRanges();
            sel.addRange(range);
          }
          emitChange();
          saveSelection();
        }}
        onMouseUp={saveSelection}
        onKeyUp={saveSelection}
        onClick={saveSelection}
      />
    </View>
  );
});

const webPlaceholderStyle: CSSProperties = {
  position: 'absolute',
  left: 14,
  top: 8,
  right: 14,
  zIndex: 2,
  fontSize: 14,
  fontWeight: 400,
  lineHeight: '22px',
  whiteSpace: 'nowrap',
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  pointerEvents: 'none',
  userSelect: 'none',
};

const webEditorStyle: CSSProperties = {
  flex: 1,
  minHeight: 36,
  maxHeight: 120,
  overflowY: 'auto',
  outline: 'none',
  fontSize: 16,
  lineHeight: '22px',
  padding: '8px 14px',
  borderRadius: 20,
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-word',
  boxSizing: 'border-box',
  width: '100%',
  position: 'relative',
  zIndex: 1,
};

const composerCss = `
.qh-chat-composer img.qh-chat-emoji {
  width: ${EMOJI_SIZE}px !important;
  height: ${EMOJI_SIZE}px !important;
  vertical-align: middle;
  display: inline-block;
  margin: 0 1px;
  object-fit: contain;
  -webkit-user-drag: none;
  user-select: none;
}
`;

const styles = StyleSheet.create({
  wrap: {
    flex: 1,
    minHeight: 36,
    maxHeight: 120,
    borderRadius: 20,
    overflow: 'hidden',
    position: 'relative',
  },
});

export const ChatComposer = WebChatComposer;
export default ChatComposer;
