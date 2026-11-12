import { useEffect, useMemo, useState } from "react";

import { starxApi } from "../../api/starx";

export default function DigitalHumanEnrollmentPanel({ app, onCreated }) {
  const [script, setScript] = useState(null);
  const [name, setName] = useState("");
  const [videoFile, setVideoFile] = useState(null);
  const [consent, setConsent] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const previewUrl = useMemo(() => (videoFile ? URL.createObjectURL(videoFile) : ""), [videoFile]);

  useEffect(() => {
    starxApi.getDigitalHumanTrainingScript().then(setScript).catch(() => {});
  }, []);

  useEffect(() => () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
  }, [previewUrl]);

  const submit = async () => {
    if (!name.trim() || !videoFile || !consent || !script) {
      app.addToast("请填写名称、上传视频并确认授权", "warning");
      return;
    }
    setSubmitting(true);
    try {
      const response = await app.createDigitalHumanProfile({
        name: name.trim(),
        videoFile,
        trainingScriptVersion: script.version,
        consentConfirmed: consent,
      });
      setName("");
      setVideoFile(null);
      setConsent(false);
      onCreated?.(response?.profile);
    } catch (error) {
      app.addToast(error.message || "数字人创建失败", "warning");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="dh-enrollment">
      <div className="dh-section-heading">
        <div>
          <span className="dh-kicker">CREATE DIGITAL HUMAN</span>
          <h3>创建数字人</h3>
          <p>上传一段稳定、正面、清晰的口播视频，系统会自动完成检测和声音克隆。</p>
        </div>
        <span className="badge">形象 + 声音</span>
      </div>

      <div className="dh-create-layout">
        <div className="dh-create-main">
          <label className="dh-field" htmlFor="dh-profile-name">
            <span>数字人名称</span>
            <input
              id="dh-profile-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="例如：创始人数字分身"
            />
          </label>

          <div className="dh-script-card">
            <div className="dh-script-card-head">
              <strong>朗读文案</strong>
              <button
                className="btn btn-xs"
                type="button"
                disabled={!script?.text}
                onClick={() => navigator.clipboard?.writeText(script.text)}
              >
                复制文案
              </button>
            </div>
            <p>{script?.text || "正在加载固定朗读文案..."}</p>
          </div>

          <div className="dh-recording-guide">
            {(script?.instructions || [
              "建议竖屏 9:16，至少 720p",
              "单人正面出镜，脸部和嘴部无遮挡",
              "不要剪辑、变速或叠加背景音乐",
            ]).map((item) => <span key={item}>• {item}</span>)}
          </div>
        </div>

        <div className="dh-create-side">
          <label className="dh-upload-zone">
            <input
              type="file"
              accept="video/mp4,video/quicktime,.mp4,.mov"
              onChange={(event) => setVideoFile(event.target.files?.[0] || null)}
            />
            <strong>{videoFile ? videoFile.name : "点击选择 MP4 / MOV 视频"}</strong>
            <small>建议时长 {script?.minDurationSeconds || 10} - {script?.maxDurationSeconds || 60} 秒</small>
          </label>

          {previewUrl ? <video className="dh-upload-preview" src={previewUrl} controls /> : null}

          <label className="dh-consent">
            <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
            <span>我确认已获得视频中人物的肖像、声音克隆和数字内容生成授权。</span>
          </label>

          <button className="btn btn-primary full-btn" type="button" disabled={submitting} onClick={submit}>
            {submitting ? "正在上传..." : "开始检测并创建数字人"}
          </button>
        </div>
      </div>
    </section>
  );
}
