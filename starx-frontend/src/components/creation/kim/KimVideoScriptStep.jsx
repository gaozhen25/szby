import VideoStoryboardTable from "../../VideoStoryboardTable";
import { downloadVideoStoryboardCsv } from "../../../utils/videoStoryboardExport";

export default function KimVideoScriptStep({
  originalScript,
  rewrittenScript,
  title,
  hashtags,
  publishCopy,
  rewritePrompt,
  showRewritePrompt,
  rewriting,
  error,
  trackingError,
  onOriginalScriptChange,
  onRewrittenScriptChange,
  onTitleChange,
  onHashtagsChange,
  onPublishCopyChange,
  onRewritePromptChange,
  onToggleRewritePrompt,
  onCancelRewrite,
  onRewrite,
  onCopy,
  onBack,
  onRetry,
  onReconnect,
  packageResult,
}) {
  return <div className="wizard-step-content">
    <div className="wizard-step-nav">
      <button className="btn btn-xs" type="button" onClick={onBack}>← 更换视频素材</button>
    </div>

    {trackingError ? <div className="video-script-error" role="alert">
      <span>无法继续获取视频脚本任务：{trackingError}</span>
      <button className="btn btn-xs" type="button" onClick={onReconnect}>重新连接</button>
    </div> : null}
    {error ? <div className="video-script-error" role="alert">
      <span>{error}</span>
      <button className="btn btn-xs" type="button" disabled={rewriting} onClick={onRetry}>重试生成</button>
    </div> : null}

    <div className="video-script-step">
      <div className="script-creation-grid">
        <div className="script-col">
          <div className="script-col-header">
            <label className="field-label" htmlFor="kim-video-original-script">爆款原版脚本</label>
            <button className="btn btn-xs btn-primary" type="button" disabled={rewriting} onClick={showRewritePrompt ? onRewrite : onToggleRewritePrompt}>
              {rewriting ? "改写中..." : showRewritePrompt ? "确认改写" : "AI 改写脚本"}
            </button>
          </div>
          {showRewritePrompt ? <div className="rewrite-prompt-input">
            <input value={rewritePrompt} onChange={(event) => onRewritePromptChange(event.target.value)} placeholder="输入改写要求..." />
            <div className="rewrite-prompt-actions">
              <button className="btn btn-xs" type="button" onClick={onCancelRewrite}>取消</button>
              <button className="btn btn-xs" type="button" disabled={rewriting} onClick={onRewrite}>直接改写</button>
            </div>
          </div> : null}
          <textarea id="kim-video-original-script" value={originalScript} onChange={(event) => onOriginalScriptChange(event.target.value)} rows={10} placeholder="粘贴或编辑爆款原版脚本..." />
        </div>

        <div className="script-col">
          <div className="script-col-header">
            <label className="field-label" htmlFor="kim-video-rewritten-script">AI 改写版脚本</label>
            {rewrittenScript.trim() ? <button className="btn btn-xs" type="button" onClick={onCopy}>复制</button> : null}
          </div>
          <textarea id="kim-video-rewritten-script" value={rewrittenScript} onChange={(event) => onRewrittenScriptChange(event.target.value)} rows={10} placeholder="改写结果会填入此处..." />
        </div>
      </div>

      <section className="video-storyboard-section" aria-labelledby="video-storyboard-title">
        <div className="video-storyboard-title">
          <div>
            <span className="video-storyboard-kicker">AI 分镜脚本</span>
            <h3 id="video-storyboard-title">逐镜拍摄执行表</h3>
            <p>时间、画面与声音按镜头对齐，拍摄和剪辑可以直接照表执行。</p>
          </div>
          <div className="video-storyboard-actions">
            <span className="video-storyboard-status">● 已结构化</span>
            <button
              className="btn btn-xs video-storyboard-export"
              type="button"
              disabled={!packageResult?.finalScript?.length && !packageResult?.shotBreakdown?.length}
              onClick={() => downloadVideoStoryboardCsv(packageResult)}
            >⇩ 导出分镜</button>
          </div>
        </div>
        {packageResult?.hookSuggestion ? <div className="video-storyboard-hook">
          <span>HOOK · 前 3–5 秒</span>
          <strong>{packageResult.hookSuggestion}</strong>
          <small>首镜画面与旁白应共同兑现这句钩子</small>
        </div> : null}
        <VideoStoryboardTable packageResult={packageResult} />
      </section>

      <div className="video-meta-section">
        <div className="video-meta-grid">
          <div>
            <label className="field-label" htmlFor="kim-video-title">标题</label>
            <input id="kim-video-title" value={title} onChange={(event) => onTitleChange(event.target.value)} placeholder="输入视频标题" />
          </div>
          <div>
            <label className="field-label" htmlFor="kim-video-hashtags">标签</label>
            <input id="kim-video-hashtags" value={hashtags} onChange={(event) => onHashtagsChange(event.target.value)} placeholder="#视频 #脚本" />
          </div>
        </div>
        <label className="field-label" htmlFor="kim-video-publish-copy">发布文案</label>
        <textarea id="kim-video-publish-copy" value={publishCopy} onChange={(event) => onPublishCopyChange(event.target.value)} rows={3} placeholder="编辑发布文案..." />
      </div>
    </div>
  </div>;
}
