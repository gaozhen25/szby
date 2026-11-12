import { useEffect, useRef } from "react";

export default function StarfieldCanvas() {
  const ref = useRef(null);

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas.getContext("2d");
    let frame;
    let stars = [];
    const resize = () => {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
      stars = Array.from({ length: 220 }, () => ({
        x: Math.random() * canvas.width, y: Math.random() * canvas.height,
        r: Math.random() * 1.8 + 0.2, o: Math.random() * 0.65 + 0.15, p: Math.random() * 6.28,
      }));
    };
    const draw = () => {
      const gradient = ctx.createRadialGradient(canvas.width * 0.55, canvas.height * 0.35, 0, canvas.width / 2, canvas.height / 2, Math.max(canvas.width, canvas.height));
      gradient.addColorStop(0, "#0c081c");
      gradient.addColorStop(0.55, "#04040e");
      gradient.addColorStop(1, "#010104");
      ctx.fillStyle = gradient;
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      stars.forEach((star) => {
        star.p += 0.008;
        ctx.beginPath();
        ctx.arc(star.x, star.y, star.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(210,205,245,${star.o * (0.55 + Math.sin(star.p) * 0.35)})`;
        ctx.fill();
      });
      frame = window.requestAnimationFrame(draw);
    };
    resize();
    draw();
    window.addEventListener("resize", resize);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", resize);
    };
  }, []);

  return <canvas ref={ref} className="starfield" />;
}
