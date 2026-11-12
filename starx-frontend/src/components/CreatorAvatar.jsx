import { useEffect, useState } from "react";

export function safeAvatarUrl(value) {
  try {
    const parsed = new URL(String(value || ""));
    return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : "";
  } catch {
    return "";
  }
}

export default function CreatorAvatar({ creator, className = "", alt = "" }) {
  const avatarUrl = safeAvatarUrl(creator?.avatarUrl);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setFailed(false);
  }, [avatarUrl]);

  const fallback = String(creator?.name || "?").trim().slice(0, 1) || "?";
  return (
    <span className={`creator-avatar ${className}`.trim()}>
      {avatarUrl && !failed ? (
        <img
          src={avatarUrl}
          alt={alt}
          loading="lazy"
          referrerPolicy="no-referrer"
          onError={() => setFailed(true)}
        />
      ) : (
        <span className="creator-avatar-fallback" aria-hidden="true">{fallback}</span>
      )}
    </span>
  );
}
