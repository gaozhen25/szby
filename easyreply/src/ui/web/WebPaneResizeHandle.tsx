import { useCallback, useRef, type PointerEvent } from 'react';
import { resizePane, type PaneKey } from '@/ui/web/pane-resize';

export function WebPaneResizeHandle({ pane }: { pane: PaneKey }) {
  const dragRef = useRef<{ startX: number; startW: number } | null>(null);

  const onPointerDown = useCallback((event: PointerEvent<HTMLDivElement>) => {
    const paneEl = event.currentTarget.parentElement;
    if (!paneEl) return;
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = {
      startX: event.clientX,
      startW: paneEl.getBoundingClientRect().width,
    };
    document.body.classList.add('qh-pane-resizing');
  }, []);

  const onPointerMove = useCallback(
    (event: PointerEvent<HTMLDivElement>) => {
      const drag = dragRef.current;
      if (!drag) return;
      resizePane(pane, drag.startW + (event.clientX - drag.startX));
    },
    [pane],
  );

  const onPointerUp = useCallback((event: PointerEvent<HTMLDivElement>) => {
    dragRef.current = null;
    document.body.classList.remove('qh-pane-resizing');
    try {
      event.currentTarget.releasePointerCapture(event.pointerId);
    } catch {
      /* ignore */
    }
  }, []);

  return (
    <div
      className="qh-pane-resize"
      role="separator"
      aria-orientation="vertical"
      aria-label="拖动调整栏宽"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
    />
  );
}
