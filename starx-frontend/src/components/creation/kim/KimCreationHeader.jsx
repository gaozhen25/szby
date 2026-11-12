const PLATFORM_EMOJI = {
  抖音: "🎵",
  小红书: "📕",
  快手: "⚡",
  视频号: "💬",
  B站: "📺",
  bilibili: "📺",
  微博: "📢",
};

function platformLabel(name) {
  const text = String(name || "").trim();
  if (!text) return "";
  const emoji = PLATFORM_EMOJI[text] || "📱";
  return text.includes(emoji) ? text : `${emoji} ${text}`;
}

export default function KimCreationHeader({
  accountName,
  accountType,
  creationType = "image",
  onCreationTypeChange,
  platforms = [],
  targetPlatform,
  onPlatformChange,
  onNewCreation,
  newCreationDisabled = false,
}) {
  const normalizedCreationType = creationType === "video" ? "video" : "image";

  return (
    <div className="section-header creation-topline">
      <h2>内容创作 · <span className="hl">{accountName || ""}</span></h2>
      <div className="section-header-right">
        <div className="creation-mode-switch" role="group" aria-label="切换创作方式">
          <div className={`creation-mode-switch-track ${normalizedCreationType === "video" ? "is-video" : ""}`}>
            <span className="creation-mode-switch-thumb" aria-hidden="true" />
            {[
              ["image", "图文创作", "🖼️"],
              ["video", "视频创作", "🎬"],
            ].map(([mode, label, icon]) => {
              const active = normalizedCreationType === mode;
              return (
                <button
                  type="button"
                  className={`creation-mode-option ${active ? "is-active" : ""}`}
                  aria-pressed={active}
                  key={mode}
                  onClick={() => onCreationTypeChange?.(mode)}
                >
                  <span className="creation-mode-icon" aria-hidden="true">{icon}</span>
                  <span className="creation-mode-copy"><strong>{label}</strong></span>
                </button>
              );
            })}
          </div>
        </div>
        <button
          type="button"
          className="btn creation-new-btn"
          disabled={newCreationDisabled}
          onClick={() => onNewCreation?.()}
        >
          新建创作
        </button>
        <span className="muted creation-account-type">{accountType || "普通号"} · </span>
        <select
          aria-label="切换创作平台"
          className="platform-select"
          value={targetPlatform}
          onChange={(event) => onPlatformChange?.(event.target.value)}
        >
          {platforms.map((platform) => <option value={platform} key={platform}>{platformLabel(platform)}</option>)}
        </select>
      </div>
    </div>
  );
}
