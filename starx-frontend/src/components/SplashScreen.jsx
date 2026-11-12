import { useEffect, useState } from "react";

const typingTexts = [
  "AI精准定位",
  "一键创作爆款"
];

export default function SplashScreen({ onDone }) {
  const [typedText, setTypedText] = useState("");
  const [textIndex, setTextIndex] = useState(0);
  const [isDeleting, setIsDeleting] = useState(false);
  const [showCursor, setShowCursor] = useState(true);
  const [isExiting, setIsExiting] = useState(false);
  const [showStats, setShowStats] = useState(false);

  useEffect(() => {
    const timer = setInterval(() => setShowCursor(v => !v), 530);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    const currentText = typingTexts[textIndex];
    
    const timeout = setTimeout(() => {
      if (!isDeleting) {
        if (typedText.length < currentText.length) {
          setTypedText(currentText.slice(0, typedText.length + 1));
        } else {
          setTimeout(() => setIsDeleting(true), 2000);
        }
      } else {
        if (typedText.length > 0) {
          setTypedText(typedText.slice(0, -1));
        } else {
          setIsDeleting(false);
          setTextIndex((prev) => (prev + 1) % typingTexts.length);
        }
      }
    }, isDeleting ? 50 : 100);

    return () => clearTimeout(timeout);
  }, [typedText, isDeleting, textIndex]);

  useEffect(() => {
    const t1 = setTimeout(() => setShowStats(true), 2000);
    return () => clearTimeout(t1);
  }, []);

  const handleEnter = () => {
    setIsExiting(true);
    setTimeout(onDone, 500);
  };

  return (
    <div className={`splash-screen ${isExiting ? "fade-out" : ""}`} onClick={handleEnter}>
      <div className="splash-grid" />
      
      <div className="splash-particles">
        {[...Array(30)].map((_, i) => (
          <div key={i} className="particle" style={{
            left: `${Math.random() * 100}%`,
            animationDelay: `${Math.random() * 5}s`,
            animationDuration: `${3 + Math.random() * 4}s`
          }} />
        ))}
      </div>

      <div className="splash-content" onClick={(e) => e.stopPropagation()}>
        <div className="splash-logo">
          <div className="logo-ring ring-1" />
          <div className="logo-ring ring-2" />
          <div className="logo-ring ring-3" />
          <span className="logo-icon">✦</span>
        </div>

        <h1 className="splash-brand">STARX</h1>
        <p className="splash-subtitle">INTERSTELLAR CONTENT PLATFORM</p>

        <div className="splash-typing-large">
          <span className="typing-text-large">{typedText}</span>
          <span className={`typing-cursor-large ${showCursor ? "visible" : ""}`}>|</span>
        </div>

        <div className={`splash-stats ${showStats ? "visible" : ""}`}>
          <div className="stat-item">
            <span className="stat-number">10</span>
            <span className="stat-label">每日选题</span>
          </div>
          <div className="stat-divider" />
          <div className="stat-item">
            <span className="stat-number">6</span>
            <span className="stat-label">流程状态</span>
          </div>
          <div className="stat-divider" />
          <div className="stat-item">
            <span className="stat-number">∞</span>
            <span className="stat-label">素材管理</span>
          </div>
          <div className="stat-divider" />
          <div className="stat-item">
            <span className="stat-number">AI</span>
            <span className="stat-label">智能创作</span>
          </div>
        </div>

        <button className="splash-enter-btn" onClick={handleEnter}>
          点击进入系统
        </button>
      </div>

      <div className="splash-footer">
        <span>SYSTEM ONLINE</span>
        <span className="footer-dot" />
        <span>2026 ALGORITHM DRIVEN</span>
      </div>
    </div>
  );
}
