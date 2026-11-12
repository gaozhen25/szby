import { useEffect, useMemo, useState } from "react";

import { starxApi } from "../../api/starx";
import MediaLightbox, { useMediaLightbox } from "../MediaLightbox";
import { createVideoSlide, downloadMedia } from "../../utils/mediaLightbox";
import DigitalHumanAssetUrlField from "./DigitalHumanAssetUrlField";
import DigitalHumanProfileGrid from "./DigitalHumanProfileGrid";

const HISTORY_PAGE_SIZE = 4;

const stageLabels = {
  preparing_voice: "准备克隆声音",
  submitting_provider: "提交数字人平台",
  provider_generating: "数字人视频生成中",
  preparing_editing: "准备成片素材",
  editing_video: "合成标题、字幕与素材",
  persisting_video: "保存最终视频",
  completed: "视频已完成",
  failed: "生成失败",
};

export default function DigitalHumanGenerator({
  app,
  initialScript = "",
  initialTitle = "",
  creationId = "",
  onJobCreated,
  onCreateProfile,
}) {
  const readyProfiles = (app.digitalHumanProfiles || []).filter((item) => item.status === "ready");
  const [selectedId, setSelectedId] = useState(readyProfiles[0]?.id || "");
  const [title, setTitle] = useState(initialTitle || "数字人口播视频");
  const [scriptText, setScriptText] = useState(initialScript);
  const [speed, setSpeed] = useState(1);
  const [subtitlesEnabled, setSubtitlesEnabled] = useState(true);
  const [backgroundUrl, setBackgroundUrl] = useState("");
  const [bubbleUrl, setBubbleUrl] = useState("");
  const [backgroundMusicUrl, setBackgroundMusicUrl] = useState("");
  const [backgroundMusicGain, setBackgroundMusicGain] = useState(0.1);
  const [uploadingAsset, setUploadingAsset] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [historyJobs, setHistoryJobs] = useState([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyPage, setHistoryPage] = useState(1);
  const [selectedJob, setSelectedJob] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    if (!selectedId && readyProfiles[0]?.id) setSelectedId(readyProfiles[0].id);
  }, [readyProfiles, selectedId]);
  useEffect(() => { if (initialScript) setScriptText(initialScript); }, [initialScript]);
  useEffect(() => { if (initialTitle) setTitle(initialTitle); }, [initialTitle]);

  useEffect(() => {
    if (!app.currentAccountId) {
      setHistoryJobs([]);
      setHistoryTotal(0);
      setSelectedJob(null);
      return undefined;
    }
    let active = true;
    setSelectedJob(null);
    setHistoryLoading(true);
    starxApi.getDigitalHumanVideoJobs(app.currentAccountId, {
      page: historyPage,
      pageSize: HISTORY_PAGE_SIZE,
      creationId: creationId || undefined,
    }).then((response) => {
      if (!active) return;
      setHistoryJobs(response?.items || []);
      setHistoryTotal(Number(response?.total || 0));
    }).catch((error) => {
      if (active) app.addToast(error.message || "数字人历史任务加载失败", "warning");
    }).finally(() => {
      if (active) setHistoryLoading(false);
    });
    return () => { active = false; };
  }, [app.currentAccountId, creationId, historyPage]);

  const jobs = useMemo(() => {
    const records = new Map();
    historyJobs.forEach((job) => records.set(job.id, job));
    (app.generationJobs || []).forEach((job) => {
      if (records.has(job.id)) records.set(job.id, job);
    });
    return [...records.values()]
      .sort((left, right) => new Date(right.createdAt || 0) - new Date(left.createdAt || 0));
  }, [app.generationJobs, historyJobs]);

  const pendingKey = jobs.filter((job) => ["pending", "running"].includes(job.status)).map((job) => job.id).join("|");

  useEffect(() => {
    if (!pendingKey) return undefined;
    const timer = window.setInterval(() => {
      pendingKey.split("|").filter(Boolean).forEach((jobId) => app.refreshGenerationJob(jobId).catch(() => {}));
    }, 5000);
    return () => window.clearInterval(timer);
  }, [app.refreshGenerationJob, pendingKey]);

  useEffect(() => {
    const totalPages = Math.max(1, Math.ceil(historyTotal / HISTORY_PAGE_SIZE));
    if (historyPage > totalPages) setHistoryPage(totalPages);
  }, [historyPage, historyTotal]);

  const generate = async () => {
    if (uploadingAsset) {
      app.addToast("请等待成片素材上传完成", "warning");
      return;
    }
    if (!selectedId || !title.trim() || !scriptText.trim()) {
      app.addToast("请选择数字人，并填写视频标题和口播文案", "warning");
      return;
    }
    setSubmitting(true);
    try {
      const job = await app.createDigitalHumanVideo({
        profileId: selectedId,
        creationId,
        title: title.trim(),
        scriptText: scriptText.trim(),
        speed: Number(speed),
        subtitlesEnabled,
        backgroundUrl: backgroundUrl.trim(),
        bubbleUrl: bubbleUrl.trim(),
        backgroundMusicUrl: backgroundMusicUrl.trim(),
        backgroundMusicGain: Number(backgroundMusicGain),
        idempotencyKey: `${creationId || "toolbox"}:${selectedId}:${Date.now()}`,
      });
      setHistoryJobs((items) => [
        job,
        ...items.filter((item) => item.id !== job.id),
      ].slice(0, HISTORY_PAGE_SIZE));
      setHistoryTotal((total) => total + 1);
      setHistoryPage(1);
      onJobCreated?.(job);
    } catch (error) {
      app.addToast(error.message || "数字人视频创建失败", "warning");
    } finally {
      setSubmitting(false);
    }
  };

  const uploadEditingAsset = async (field, file, setUrl) => {
    if (!app.currentAccountId) {
      app.addToast("请先选择账号", "warning");
      return;
    }
    setUploadingAsset(field);
    try {
      const uploaded = await starxApi.uploadDigitalHumanEditingAsset(
        app.currentAccountId,
        file,
        field === "music" ? "digital_human_background_music" : "digital_human_editing_asset",
      );
      setUrl(uploaded.url);
      app.addToast(`${file.name || "素材"}上传成功，URL 已自动填入`, "success");
    } catch (error) {
      app.addToast(error.message || "成片素材上传失败", "warning");
    } finally {
      setUploadingAsset("");
    }
  };

  const openJob = async (jobId) => {
    if (!app.currentAccountId || !jobId) return;
    setDetailLoading(true);
    try {
      const job = await starxApi.getGenerationJob(app.currentAccountId, jobId);
      setSelectedJob(job);
      setHistoryJobs((items) => items.map((item) => item.id === job.id ? job : item));
    } catch (error) {
      app.addToast(error.message || "任务详情加载失败", "warning");
    } finally {
      setDetailLoading(false);
    }
  };

  const history = (
    <GenerationHistory
      jobs={jobs}
      historyLoading={historyLoading}
      detailLoading={detailLoading}
      page={historyPage}
      total={historyTotal}
      onPageChange={setHistoryPage}
      openJob={openJob}
    />
  );

  const detail = selectedJob ? (
    <DigitalHumanJobDetail app={app} job={selectedJob} onClose={() => setSelectedJob(null)} />
  ) : null;

  if (!readyProfiles.length) {
    return (
      <section className="dh-generator">
        <div className="dh-empty dh-empty-action">
          <span className="dh-empty-mark">03</span>
          <strong>还没有可用于生成视频的数字人</strong>
          <p>先创建数字人并等待状态变为“已就绪”，这里就会自动出现可选形象。</p>
          <button className="btn btn-primary" type="button" onClick={onCreateProfile}>去创建数字人</button>
        </div>
        {history}
        {detail}
      </section>
    );
  }

  return (
    <section className="dh-generator">
      <div className="dh-generate-layout">
        <div className="dh-generator-main">
          <div className="dh-subsection-heading">
            <span>选择数字人</span>
            <small>{readyProfiles.length} 个可用</small>
          </div>
          <DigitalHumanProfileGrid
            app={app}
            profiles={readyProfiles}
            selectable
            compact
            selectedId={selectedId}
            onSelect={setSelectedId}
          />

          <div className="dh-generator-form">
            <div className="dh-form-grid">
              <label className="dh-field" htmlFor="dh-video-title">
                <span>视频标题</span>
                <input id="dh-video-title" value={title} onChange={(event) => setTitle(event.target.value)} />
              </label>
              <label className="dh-field" htmlFor="dh-video-speed">
                <span>语速：{Number(speed).toFixed(1)}x</span>
                <input id="dh-video-speed" type="range" min="0.5" max="2" step="0.1" value={speed} onChange={(event) => setSpeed(event.target.value)} />
              </label>
            </div>
            <label className="dh-field" htmlFor="dh-video-script">
              <span>口播文案</span>
              <textarea id="dh-video-script" rows={8} value={scriptText} onChange={(event) => setScriptText(event.target.value)} placeholder="输入需要数字人口播的新脚本..." />
            </label>

            <div className="dh-editing-fields">
              <div className="dh-editing-heading">
                <div>
                  <strong>成片包装</strong>
                  <small>生成原始口播后，可叠加字幕、背景和音乐。都可以留空。</small>
                </div>
                <label className="dh-switch">
                  <input type="checkbox" checked={subtitlesEnabled} onChange={(event) => setSubtitlesEnabled(event.target.checked)} />
                  自动字幕
                </label>
              </div>
              <div className="dh-form-grid">
                <DigitalHumanAssetUrlField
                  id="dh-background-url"
                  label="背景图片/视频 URL"
                  value={backgroundUrl}
                  placeholder="https://example.com/background.jpg"
                  accept="image/jpeg,image/png,image/webp,video/mp4,video/quicktime"
                  uploading={uploadingAsset === "background"}
                  disabled={Boolean(uploadingAsset)}
                  onChange={setBackgroundUrl}
                  onUpload={(file) => uploadEditingAsset("background", file, setBackgroundUrl)}
                />
                <DigitalHumanAssetUrlField
                  id="dh-bubble-url"
                  label="气泡图片 URL"
                  value={bubbleUrl}
                  placeholder="https://example.com/bubble.png"
                  accept="image/jpeg,image/png,image/webp"
                  uploading={uploadingAsset === "bubble"}
                  disabled={Boolean(uploadingAsset)}
                  onChange={setBubbleUrl}
                  onUpload={(file) => uploadEditingAsset("bubble", file, setBubbleUrl)}
                />
                <DigitalHumanAssetUrlField
                  id="dh-bgm-url"
                  label="背景音乐 URL"
                  value={backgroundMusicUrl}
                  placeholder="https://example.com/music.mp3 或 music.mp4"
                  accept="audio/mpeg,audio/mp4,audio/aac,audio/wav,audio/x-wav,audio/ogg,video/mp4,.mp3,.m4a,.aac,.wav,.ogg,.mp4"
                  uploading={uploadingAsset === "music"}
                  disabled={Boolean(uploadingAsset)}
                  onChange={setBackgroundMusicUrl}
                  onUpload={(file) => uploadEditingAsset("music", file, setBackgroundMusicUrl)}
                />
                <label className="dh-field" htmlFor="dh-bgm-gain">
                  <span>背景音乐增益：{Number(backgroundMusicGain).toFixed(2)}</span>
                  <input id="dh-bgm-gain" type="range" min="0" max="1" step="0.01" value={backgroundMusicGain} onChange={(event) => setBackgroundMusicGain(event.target.value)} />
                  <small className="muted">Gain 为阿里云线性音量：0 表示静音，1 表示原音量；口播背景音乐建议 0.05～0.20，过大可能产生破音。</small>
                </label>
              </div>
            </div>

            <button className="btn btn-primary full-btn" type="button" disabled={submitting || Boolean(uploadingAsset)} onClick={generate}>
              {submitting ? "正在创建任务..." : "生成数字人成片"}
            </button>
          </div>
        </div>

        {history}
      </div>
      {detail}
    </section>
  );
}

function GenerationHistory({ jobs, historyLoading, detailLoading, page, total, onPageChange, openJob }) {
  const totalPages = Math.max(1, Math.ceil(total / HISTORY_PAGE_SIZE));
  const currentPage = Math.min(Math.max(page || 1, 1), totalPages);

  return (
    <aside className="dh-job-list">
      <div className="dh-history-heading">
        <div>
          <span className="dh-kicker">HISTORY</span>
          <h4>生成记录</h4>
        </div>
        <span>{historyLoading ? "加载中..." : `${total} 条`}</span>
      </div>
      {jobs.map((job) => {
        const finalUrl = getJobVideoUrl(job);
        const progress = Math.max(5, Number(job.progress || (finalUrl ? 100 : 5)));
        return (
          <article className="dh-job-card" key={job.id}>
            <button className="dh-job-summary" type="button" onClick={() => openJob(job.id)}>
              <span>
                <strong>{job.title || "数字人口播视频"}</strong>
                <small>{formatJobTime(job.createdAt)}</small>
              </span>
              <span className={`badge job-${job.status}`}>{stageLabels[job.currentStage] || job.status}</span>
            </button>
            {job.error ? <p className="dh-error">{job.error}</p> : null}
            <div className="dh-progress"><span style={{ width: `${progress}%` }} /></div>
            <div className="button-row">
              <button className="btn btn-xs" type="button" disabled={detailLoading} onClick={() => openJob(job.id)}>查看详情</button>
              {finalUrl ? <a className="btn btn-xs" href={finalUrl} download>下载 MP4</a> : null}
            </div>
          </article>
        );
      })}
      {!historyLoading && !total ? <div className="dh-empty dh-empty-inline">还没有生成记录</div> : null}
      {totalPages > 1 ? (
        <div className="dh-history-pagination">
          <button className="btn btn-xs" type="button" disabled={currentPage <= 1} onClick={() => onPageChange(currentPage - 1)}>上一页</button>
          <span>{currentPage} / {totalPages}</span>
          <button className="btn btn-xs" type="button" disabled={currentPage >= totalPages} onClick={() => onPageChange(currentPage + 1)}>下一页</button>
        </div>
      ) : null}
    </aside>
  );
}

function DigitalHumanJobDetail({ app, job, onClose }) {
  const mediaLightbox = useMediaLightbox();
  const finalUrl = getJobVideoUrl(job);
  const rawVideoUrl = getRawVideoUrl(job);
  const sourceAudioUrl = getJobSourceAudioUrl(job);
  const input = job.inputPayload || {};
  const editing = input.editing || {};
  const backgroundMusicMeta = job.resultPayload?.backgroundMusicMeta || {};
  const mediaInfo = job.resultPayload?.mediaInfo || {};
  const rawVideoFilename = `${job.title || "数字人口播视频"}-供应商原片.mp4`;
  const sourceAudioFilename = `${job.title || "数字人口播视频"}-生成音轨.mp3`;

  const previewRawVideo = () => {
    mediaLightbox.openMedia([
      createVideoSlide(rawVideoUrl, {
        title: `${job.title || "数字人口播视频"} · 供应商原片`,
        downloadFilename: rawVideoFilename,
      }),
    ]);
  };

  return (
    <>
      <div className="dh-detail-backdrop" role="presentation" onMouseDown={onClose}>
        <section className="dh-task-detail glass-card" role="dialog" aria-modal="true" aria-labelledby="dh-task-detail-title" onMouseDown={(event) => event.stopPropagation()}>
          <header>
            <div>
              <span className="dh-kicker">TASK DETAIL</span>
              <h3 id="dh-task-detail-title">{job.title || "数字人口播视频"}</h3>
            </div>
            <button className="btn btn-xs" type="button" onClick={onClose}>关闭</button>
          </header>
          <div className="dh-detail-meta">
            <span>状态：{stageLabels[job.currentStage] || job.status}</span>
            <span>创建时间：{formatJobTime(job.createdAt)}</span>
            <span>数字人：{getProfileName(app.digitalHumanProfiles, input.profileId)}</span>
            <span>语速：{Number(input.speed || 1).toFixed(1)}x</span>
            <span>自动字幕：{editing.subtitlesEnabled === false ? "关闭" : "开启"}</span>
          </div>
          <DetailParameters editing={editing} />
          {Object.keys(backgroundMusicMeta).length ? (
            <AudioQuality title="背景音乐检测" info={backgroundMusicMeta} />
          ) : null}
          {Object.keys(mediaInfo).length ? (
            <AudioQuality title="最终成片音频" info={mediaInfo} />
          ) : null}
          <div className="dh-detail-script">
            <strong>口播文案</strong>
            <p>{input.scriptText || "该历史任务没有保存可展示的文案。"}</p>
          </div>
          {sourceAudioUrl ? (
            <div className="dh-detail-audio">
              <div>
                <strong>生成音轨</strong>
                <button
                  className="btn btn-xs"
                  type="button"
                  onClick={() => downloadMedia(sourceAudioUrl, sourceAudioFilename)}
                >
                  下载音轨
                </button>
              </div>
              <audio src={sourceAudioUrl} controls preload="metadata">
                当前浏览器不支持音频播放。
              </audio>
            </div>
          ) : null}
          {job.error ? <p className="dh-error">{job.error}</p> : null}
          {finalUrl ? (
            <video src={finalUrl} controls preload="metadata" />
          ) : (
            <div className="dh-progress"><span style={{ width: `${job.progress || 5}%` }} /></div>
          )}
          <div className="button-row">
            {finalUrl ? <a className="btn btn-primary" href={finalUrl} download>下载最终视频</a> : null}
            {rawVideoUrl ? <button className="btn" type="button" onClick={previewRawVideo}>查看供应商原片</button> : null}
            {rawVideoUrl ? (
              <button className="btn" type="button" onClick={() => downloadMedia(rawVideoUrl, rawVideoFilename)}>
                下载供应商原片
              </button>
            ) : null}
          </div>
        </section>
      </div>
      <MediaLightbox
        open={mediaLightbox.open}
        index={mediaLightbox.index}
        slides={mediaLightbox.slides}
        onClose={mediaLightbox.closeMedia}
        onIndexChange={mediaLightbox.setMediaIndex}
      />
    </>
  );
}

function DetailParameters({ editing }) {
  return (
    <div className="dh-detail-parameters">
      <strong>成片参数</strong>
      <dl>
        <dt>背景音乐 Gain</dt>
        <dd>{Number(editing.backgroundMusicGain ?? 0.1).toFixed(2)}</dd>
        <dt>背景音乐</dt>
        <dd><DetailMediaLink url={editing.backgroundMusicUrl} /></dd>
        <dt>背景素材</dt>
        <dd><DetailMediaLink url={editing.backgroundUrl} /></dd>
        <dt>气泡素材</dt>
        <dd><DetailMediaLink url={editing.bubbleUrl} /></dd>
      </dl>
    </div>
  );
}

function DetailMediaLink({ url }) {
  return url
    ? <a href={url} target="_blank" rel="noreferrer" title={url}>{url}</a>
    : <span className="muted">未设置</span>;
}

function AudioQuality({ title, info }) {
  const sampleRate = Number(info.sampleRate || info.audioSampleRate || 0);
  const channels = Number(info.channels || info.audioChannels || 0);
  const bitRate = Number(info.bitRate || info.audioBitRate || 0);
  const codec = info.codec || info.audioCodec || "-";
  return (
    <div className="dh-detail-parameters">
      <strong>{title}</strong>
      <dl>
        <dt>编码</dt><dd>{codec}</dd>
        <dt>采样率</dt><dd>{sampleRate ? `${(sampleRate / 1000).toFixed(1)} kHz` : "-"}</dd>
        <dt>声道</dt><dd>{channels || "-"}</dd>
        <dt>码率</dt><dd>{bitRate ? `${Math.round(bitRate / 1000)} kbps` : "-"}</dd>
        <dt>综合响度</dt><dd>{formatAudioMetric(info.integratedLoudnessLufs, "LUFS")}</dd>
        <dt>真峰值</dt><dd>{formatAudioMetric(info.truePeakDbtp, "dBTP")}</dd>
      </dl>
    </div>
  );
}

function formatAudioMetric(value, unit) {
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(1)} ${unit}` : "-";
}

function getJobVideoUrl(job) {
  return job?.resultPayload?.finalVideoUrl
    || (job?.assets || []).find((asset) => asset.assetType === "result_video")?.url
    || "";
}

function getRawVideoUrl(job) {
  return job?.resultPayload?.persistedRawVideoUrl
    || (job?.assets || []).find((asset) => asset.assetType === "raw_video")?.url
    || job?.resultPayload?.rawVideoUrl
    || "";
}

function getJobSourceAudioUrl(job) {
  return (job?.assets || []).find((asset) => asset.assetType === "source_audio")?.url
    || "";
}

function formatJobTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "-" : date.toLocaleString("zh-CN", { hour12: false });
}

function getProfileName(profiles, profileId) {
  return (profiles || []).find((profile) => profile.id === profileId)?.name || profileId || "-";
}
