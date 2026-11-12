import { normalizeVideoShootingSegments } from "../utils/videoScriptPackage";

function formatShotNumber(value) {
  return String(value || 0).padStart(2, "0");
}

function readDurationSeconds(segments) {
  const end = String(segments.at(-1)?.timeRange || "").split("-").at(-1);
  const [minutes, seconds] = String(end || "").split(":").map(Number);
  return Number.isFinite(minutes) && Number.isFinite(seconds) ? minutes * 60 + seconds : 0;
}

export default function VideoStoryboardTable({ packageResult, compact = false }) {
  const segments = normalizeVideoShootingSegments(packageResult);

  if (!segments.length) {
    return <div className="video-storyboard-empty">
      <span aria-hidden="true">▦</span>
      <strong>分镜脚本将在生成后显示</strong>
      <small>每一镜会对齐时间、机位、画面和声音，方便直接进入拍摄。</small>
    </div>;
  }

  const durationSeconds = readDurationSeconds(segments);
  const averageSeconds = durationSeconds ? Math.round(durationSeconds / segments.length) : 0;

  return <>
    {!compact ? <div className="video-storyboard-summary" aria-label="分镜脚本概览">
      <span><strong>{segments.length}</strong> 个镜头</span>
      {durationSeconds ? <span><strong>{durationSeconds}</strong> 秒成片</span> : null}
      {averageSeconds ? <span>平均 <strong>{averageSeconds}</strong> 秒 / 镜</span> : null}
    </div> : null}
    <div className={`video-storyboard-shell${compact ? " is-compact" : ""}`}>
    <div className="video-storyboard-table" role="table" aria-label="视频分镜脚本">
      <div className="video-storyboard-row video-storyboard-head" role="row">
        <span role="columnheader">镜号</span>
        <span role="columnheader">时间</span>
        <span role="columnheader">景别 / 机位</span>
        <span role="columnheader">画面内容</span>
        <span role="columnheader">声音 / 旁白</span>
      </div>
      {segments.map((segment) => <article
        className="video-storyboard-row"
        role="row"
        key={`${segment.shotNumber}_${segment.timeRange}`}
      >
        <div className="video-storyboard-shot" role="cell" data-label="镜号">
          <strong>{formatShotNumber(segment.shotNumber)}</strong>
          {!compact ? <small>{segment.shotNumber === 1 ? "钩子" : segment.shotNumber === segments.length ? "收束" : "正文"}</small> : null}
        </div>
        <div className="video-storyboard-time" role="cell" data-label="时间">
          <span>{segment.timeRange || "待定"}</span>
        </div>
        <div role="cell" data-label="景别 / 机位">
          <p>{segment.shotSizeCamera || "待补充"}</p>
        </div>
        <div role="cell" data-label="画面内容">
          <p>{segment.visual || "待补充"}</p>
          {!compact && segment.shootingTechnique ? <small>{segment.shootingTechnique}</small> : null}
        </div>
        <div role="cell" data-label="声音 / 旁白">
          <p className="video-storyboard-narration">{segment.narration || segment.soundNarration || "待补充"}</p>
          {!compact && segment.bgmSound ? <small><b>声音</b>{segment.bgmSound}</small> : null}
          {!compact && segment.subtitle ? <small>字幕：{segment.subtitle}</small> : null}
        </div>
      </article>)}
    </div>
    </div>
  </>;
}
