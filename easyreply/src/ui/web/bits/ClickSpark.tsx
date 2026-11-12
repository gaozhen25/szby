import { useCallback, useEffect, useRef, type MouseEvent, type ReactNode } from 'react';

type Spark = { x: number; y: number; angle: number; startTime: number };

function prefersReducedMotion() {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/** React Bits ClickSpark：点击处放射短线，仅在有火花时跑 rAF。 */
export function ClickSpark({
  children,
  sparkColor,
  sparkSize = 7,
  sparkRadius = 14,
  sparkCount = 8,
  duration = 380,
}: {
  children: ReactNode;
  sparkColor: string;
  sparkSize?: number;
  sparkRadius?: number;
  sparkCount?: number;
  duration?: number;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const sparksRef = useRef<Spark[]>([]);
  const rafRef = useRef(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    const parent = canvas?.parentElement;
    if (!canvas || !parent) return;

    const resize = () => {
      const { width, height } = parent.getBoundingClientRect();
      const w = Math.max(1, Math.round(width));
      const h = Math.max(1, Math.round(height));
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
      }
    };

    const ro = new ResizeObserver(resize);
    ro.observe(parent);
    resize();
    return () => ro.disconnect();
  }, []);

  const easeOut = useCallback((t: number) => t * (2 - t), []);

  const tick = useCallback(
    (timestamp: number) => {
      const canvas = canvasRef.current;
      const ctx = canvas?.getContext('2d');
      if (!canvas || !ctx) {
        rafRef.current = 0;
        return;
      }
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      sparksRef.current = sparksRef.current.filter((spark) => {
        const elapsed = timestamp - spark.startTime;
        if (elapsed >= duration) return false;
        const eased = easeOut(elapsed / duration);
        const distance = eased * sparkRadius;
        const lineLength = sparkSize * (1 - eased);
        const cos = Math.cos(spark.angle);
        const sin = Math.sin(spark.angle);
        ctx.strokeStyle = sparkColor;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(spark.x + distance * cos, spark.y + distance * sin);
        ctx.lineTo(spark.x + (distance + lineLength) * cos, spark.y + (distance + lineLength) * sin);
        ctx.stroke();
        return true;
      });
      if (sparksRef.current.length > 0) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        rafRef.current = 0;
      }
    },
    [duration, easeOut, sparkColor, sparkRadius, sparkSize],
  );

  useEffect(() => () => cancelAnimationFrame(rafRef.current), []);

  const onClick = (e: MouseEvent<HTMLDivElement>) => {
    const canvas = canvasRef.current;
    if (!canvas || prefersReducedMotion()) return;
    const rect = canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    const now = performance.now();
    for (let i = 0; i < sparkCount; i++) {
      sparksRef.current.push({
        x,
        y,
        angle: (2 * Math.PI * i) / sparkCount,
        startTime: now,
      });
    }
    if (!rafRef.current) rafRef.current = requestAnimationFrame(tick);
  };

  return (
    <div className="qh-click-spark" onClick={onClick}>
      <canvas ref={canvasRef} className="qh-click-spark-canvas" aria-hidden />
      {children}
    </div>
  );
}
