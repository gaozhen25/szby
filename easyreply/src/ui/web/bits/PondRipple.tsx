import { useEffect, useRef } from 'react';
import { webPageBg } from '@/ui/web/theme';

type Drop = { x: number; y: number; t: number; amp: number };

function prefersReducedMotion() {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

export function PondRipple({ className = '' }: { className?: string }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const wrap = wrapRef.current;
    const canvas = canvasRef.current;
    if (!wrap || !canvas) return;
    const ctx = canvas.getContext('2d', { alpha: false });
    if (!ctx) return;

    const mouse = { x: 0, y: 0, str: 0 };
    const drops: Drop[] = [];
    let frame = 0;
    let bufW = 0;
    let bufH = 0;
    let heights = new Float32Array(0);
    let pixels = new ImageData(1, 1);
    let off: HTMLCanvasElement | null = null;
    let offCtx: CanvasRenderingContext2D | null = null;

    function layout() {
      const box = wrap.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.max(1, Math.floor(box.width * dpr));
      canvas.height = Math.max(1, Math.floor(box.height * dpr));
      canvas.style.width = `${box.width}px`;
      canvas.style.height = `${box.height}px`;
      bufW = Math.max(80, Math.floor(box.width / 4));
      bufH = Math.max(50, Math.floor(box.height / 4));
      heights = new Float32Array(bufW * bufH);
      pixels = new ImageData(bufW, bufH);
      off = document.createElement('canvas');
      off.width = bufW;
      off.height = bufH;
      offCtx = off.getContext('2d');
      return box;
    }

    function sample(x: number, y: number, t: number) {
      const u = x / bufW;
      const v = y / bufH;
      let h =
        Math.pow(
          0.52 +
            0.48 *
              Math.sin(u * 14.5 + t * 0.0007) *
              Math.sin(v * 11.2 - t * 0.00052),
          2.1,
        ) *
          0.95 +
        Math.sin((u * 1.1 + v) * 9.4 - t * 0.00046) * 0.22 +
        Math.sin((v * 1.35 - u) * 7.1 + t * 0.00034) * 0.16;
      const mdx = x - mouse.x;
      const mdy = y - mouse.y;
      h += mouse.str * Math.exp(-(mdx * mdx + mdy * mdy) / 980);
      for (let i = 0; i < drops.length; i++) {
        const d = drops[i];
        const age = t - d.t;
        const spread = 18 + age * 0.01;
        const dx = x - d.x;
        const dy = y - d.y;
        h += d.amp * Math.exp(-age * 0.00105) * Math.exp(-(dx * dx + dy * dy) / (2 * spread * spread));
      }
      return h;
    }

    function paint(t: number) {
      const data = pixels.data;
      for (let y = 0; y < bufH; y++) {
        for (let x = 0; x < bufW; x++) {
          heights[y * bufW + x] = sample(x, y, t);
        }
      }
      for (let y = 0; y < bufH; y++) {
        for (let x = 0; x < bufW; x++) {
          const i = y * bufW + x;
          const left = heights[y * bufW + Math.max(0, x - 1)];
          const right = heights[y * bufW + Math.min(bufW - 1, x + 1)];
          const up = heights[Math.max(0, y - 1) * bufW + x];
          const down = heights[Math.min(bufH - 1, y + 1) * bufW + x];
          const nx = left - right;
          const ny = up - down;
          const spec = Math.max(0, nx * 1.1 + ny * 0.7 + 0.08);
          const gloss = spec * spec;
          const h = heights[i];
          const mix = Math.max(0, Math.min(1, 0.38 + h * 0.55));
          const p = i * 4;
          data[p] = Math.round(148 + mix * 92 + gloss * 70);
          data[p + 1] = Math.round(204 + mix * 42 + gloss * 36);
          data[p + 2] = Math.round(198 + mix * 44 + gloss * 28);
          data[p + 3] = 255;
        }
      }
      if (!offCtx) return;
      offCtx.putImageData(pixels, 0, 0);
      ctx.imageSmoothingEnabled = true;
      ctx.drawImage(off as HTMLCanvasElement, 0, 0, canvas.width, canvas.height);
    }

    function toBuf(clientX: number, clientY: number) {
      const box = wrap.getBoundingClientRect();
      return {
        x: ((clientX - box.left) / Math.max(1, box.width)) * bufW,
        y: ((clientY - box.top) / Math.max(1, box.height)) * bufH,
      };
    }

    function onMove(e: MouseEvent) {
      const p = toBuf(e.clientX, e.clientY);
      mouse.x = p.x;
      mouse.y = p.y;
      mouse.str = 0.55;
    }

    function onClick(e: MouseEvent) {
      if (prefersReducedMotion()) return;
      const p = toBuf(e.clientX, e.clientY);
      drops.push({ x: p.x, y: p.y, t: performance.now(), amp: 0.9 });
      if (drops.length > 6) drops.shift();
    }

    function tick(now: number) {
      mouse.str *= 0.96;
      const cutoff = now - 3200;
      while (drops.length && drops[0].t < cutoff) drops.shift();
      paint(now);
      frame = requestAnimationFrame(tick);
    }

    layout();
    mouse.x = bufW * 0.5;
    mouse.y = bufH * 0.5;

    const ro = new ResizeObserver(() => {
      layout();
      if (prefersReducedMotion()) paint(0);
    });
    ro.observe(wrap);

    if (prefersReducedMotion()) {
      paint(0);
      return () => ro.disconnect();
    }

    frame = requestAnimationFrame(tick);
    window.addEventListener('mousemove', onMove);
    window.addEventListener('click', onClick);
    return () => {
      ro.disconnect();
      cancelAnimationFrame(frame);
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('click', onClick);
    };
  }, []);

  return (
    <div
      ref={wrapRef}
      className={className ? `qh-auth-pond ${className}` : 'qh-auth-pond'}
      aria-hidden="true"
      style={{
        position: 'absolute',
        inset: 0,
        overflow: 'hidden',
        pointerEvents: 'none',
        background: webPageBg.login,
      }}
    >
      <canvas ref={canvasRef} className="qh-auth-pond-canvas" />
    </div>
  );
}
