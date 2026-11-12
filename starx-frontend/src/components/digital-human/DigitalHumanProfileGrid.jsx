import { useEffect } from "react";

const statusLabels = {
  validating: "检测中",
  cloning_voice: "声音克隆中",
  ready: "已就绪",
  failed: "创建失败",
  disabled: "已停用",
};

export default function DigitalHumanProfileGrid({
  app,
  profiles,
  selectable = false,
  compact = false,
  selectedId = "",
  onSelect,
  onCreateProfile,
  onGenerateVideo,
}) {
  const pendingKey = (profiles || [])
    .filter((item) => ["validating", "cloning_voice"].includes(item.status))
    .map((item) => item.id)
    .join("|");

  useEffect(() => {
    if (!pendingKey || !app.refreshDigitalHumanProfiles) return undefined;
    const timer = window.setInterval(() => app.refreshDigitalHumanProfiles().catch(() => {}), 5000);
    return () => window.clearInterval(timer);
  }, [app.refreshDigitalHumanProfiles, pendingKey]);

  if (!profiles?.length) {
    return (
      <div className="dh-empty dh-empty-action">
        <span className="dh-empty-mark">02</span>
        <strong>当前账号还没有数字人</strong>
        <p>创建完成后，数字人的检测状态、声音试听和源视频都会集中显示在这里。</p>
        {onCreateProfile ? (
          <button className="btn btn-primary" type="button" onClick={onCreateProfile}>去创建数字人</button>
        ) : null}
      </div>
    );
  }

  return (
    <div className={`dh-profile-grid ${compact ? "is-compact" : ""}`}>
      {profiles.map((profile) => {
        const ready = profile.status === "ready";
        const selected = selectedId === profile.id;
        return (
          <article
            className={`dh-profile-card ${selected ? "selected" : ""} ${ready ? "is-ready" : "is-muted"}`}
            key={profile.id}
          >
            <button
              className="dh-profile-cover"
              type="button"
              disabled={!selectable || !ready}
              onClick={() => onSelect?.(profile.id)}
              aria-label={selectable ? `选择${profile.name}` : `${profile.name}封面`}
            >
              {profile.coverUrl
                ? <img src={profile.coverUrl} alt={`${profile.name}封面`} />
                : <span aria-hidden="true">DH</span>}
            </button>
            <div className="dh-profile-info">
              <div className="dh-profile-title-row">
                <strong>{profile.name}</strong>
                <span className={`badge job-${ready ? "completed" : profile.status === "failed" ? "failed" : "running"}`}>
                  {statusLabels[profile.status] || profile.status}
                </span>
              </div>
              <small>
                {profile.width && profile.height ? `${profile.width} x ${profile.height}` : "正在分析视频"}
                {" / "}
                {profile.durationSeconds ? `${profile.durationSeconds} 秒` : "时长待识别"}
              </small>
              {profile.voicePreviewUrl ? <audio src={profile.voicePreviewUrl} controls preload="none" /> : null}
              {profile.errorMessage ? <p className="dh-error">{profile.errorMessage}</p> : null}
              <div className="button-row">
                {selectable && ready ? (
                  <button className="btn btn-xs btn-primary" type="button" onClick={() => onSelect?.(profile.id)}>
                    {selected ? "已选择" : "选择"}
                  </button>
                ) : null}
                {!selectable && ready && onGenerateVideo ? (
                  <button className="btn btn-xs btn-primary" type="button" onClick={onGenerateVideo}>生成视频</button>
                ) : null}
                {profile.sourceVideoUrl ? (
                  <button className="btn btn-xs" type="button" onClick={() => window.open(profile.sourceVideoUrl, "_blank", "noopener")}>源视频</button>
                ) : null}
                {profile.status !== "disabled" ? (
                  <button className="btn btn-xs btn-danger" type="button" onClick={() => app.disableDigitalHumanProfile(profile.id)}>停用</button>
                ) : null}
              </div>
            </div>
          </article>
        );
      })}
    </div>
  );
}
