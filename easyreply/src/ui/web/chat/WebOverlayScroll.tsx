import {
  useCallback,
  useEffect,
  useRef,
  type HTMLAttributes,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
  type Ref,
  type UIEvent,
} from 'react';

type Props = {
  children: ReactNode;
  className?: string;
  viewportRef?: Ref<HTMLDivElement | null>;
  onScroll?: (event: UIEvent<HTMLDivElement>) => void;
} & Omit<HTMLAttributes<HTMLDivElement>, 'onScroll' | 'children'>;

function assignRef<T>(ref: Ref<T> | undefined, value: T) {
  if (!ref) return;
  if (typeof ref === 'function') ref(value);
  else ref.current = value;
}

function syncThumb(viewport: HTMLElement, thumb: HTMLElement, host: HTMLElement) {
  const { scrollTop, scrollHeight, clientHeight } = viewport;
  const scrollable = scrollHeight > clientHeight + 1;
  host.classList.toggle('is-scrollable', scrollable);
  if (!scrollable) {
    thumb.style.height = '0px';
    thumb.style.transform = 'translateY(0)';
    return;
  }

  const ratio = clientHeight / scrollHeight;
  const thumbH = Math.max(24, Math.round(clientHeight * ratio));
  const maxTop = Math.max(0, clientHeight - thumbH);
  const maxScroll = Math.max(1, scrollHeight - clientHeight);
  const top = (scrollTop / maxScroll) * maxTop;
  thumb.style.height = `${thumbH}px`;
  thumb.style.transform = `translateY(${top}px)`;
}

/**
 * 列表浮层细滚动条：原生条隐藏不占宽，thumb 叠在右侧。
 */
export function WebOverlayScroll({
  children,
  className,
  viewportRef,
  onScroll,
  ...hostProps
}: Props) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const localViewportRef = useRef<HTMLDivElement | null>(null);
  const thumbRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<{ startY: number; startScrollTop: number } | null>(null);
  const hideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(() => {
    const viewport = localViewportRef.current;
    const thumb = thumbRef.current;
    const host = hostRef.current;
    if (!viewport || !thumb || !host) return;
    syncThumb(viewport, thumb, host);
  }, []);

  const flash = useCallback(() => {
    const host = hostRef.current;
    if (!host) return;
    host.classList.add('is-scrolling');
    if (hideTimerRef.current) clearTimeout(hideTimerRef.current);
    hideTimerRef.current = setTimeout(() => {
      host.classList.remove('is-scrolling');
    }, 800);
  }, []);

  const setViewportNode = useCallback(
    (el: HTMLDivElement | null) => {
      localViewportRef.current = el;
      assignRef(viewportRef, el);
      if (el) requestAnimationFrame(refresh);
    },
    [viewportRef, refresh],
  );

  useEffect(() => {
    const viewport = localViewportRef.current;
    if (!viewport) return;
    refresh();
    const ro = new ResizeObserver(() => refresh());
    ro.observe(viewport);
    const first = viewport.firstElementChild;
    if (first instanceof HTMLElement) ro.observe(first);
    return () => ro.disconnect();
  }, [refresh, children]);

  useEffect(
    () => () => {
      if (hideTimerRef.current) clearTimeout(hideTimerRef.current);
    },
    [],
  );

  const handleScroll = useCallback(
    (event: UIEvent<HTMLDivElement>) => {
      refresh();
      flash();
      onScroll?.(event);
    },
    [refresh, flash, onScroll],
  );

  const onThumbPointerDown = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    const viewport = localViewportRef.current;
    const thumb = thumbRef.current;
    if (!viewport || !thumb) return;
    event.preventDefault();
    event.stopPropagation();
    thumb.setPointerCapture(event.pointerId);
    dragRef.current = { startY: event.clientY, startScrollTop: viewport.scrollTop };
    hostRef.current?.classList.add('is-scrolling');
  }, []);

  const onThumbPointerMove = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    const viewport = localViewportRef.current;
    if (!drag || !viewport) return;
    const { scrollHeight, clientHeight } = viewport;
    const maxScroll = Math.max(1, scrollHeight - clientHeight);
    const thumbH = Math.max(24, Math.round(clientHeight * (clientHeight / Math.max(scrollHeight, 1))));
    const maxTop = Math.max(1, clientHeight - thumbH);
    const delta = ((event.clientY - drag.startY) / maxTop) * maxScroll;
    viewport.scrollTop = drag.startScrollTop + delta;
  }, []);

  const onThumbPointerUp = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      dragRef.current = null;
      try {
        event.currentTarget.releasePointerCapture(event.pointerId);
      } catch {
        /* ignore */
      }
      flash();
    },
    [flash],
  );

  const hostClass = ['qh-overlay-scroll', className].filter(Boolean).join(' ');

  return (
    <div {...hostProps} ref={hostRef} className={hostClass}>
      <div
        ref={setViewportNode}
        className="qh-conv-scroller qh-overlay-scroll-viewport"
        onScroll={handleScroll}
      >
        {children}
      </div>
      <div
        ref={thumbRef}
        className="qh-overlay-scroll-thumb"
        onPointerDown={onThumbPointerDown}
        onPointerMove={onThumbPointerMove}
        onPointerUp={onThumbPointerUp}
        onPointerCancel={onThumbPointerUp}
      />
    </div>
  );
}
