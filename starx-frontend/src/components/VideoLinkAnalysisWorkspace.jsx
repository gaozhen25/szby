import { formatVideoScriptLines } from "../utils/videoAnalysis";

const STATUS_TEXT = { pending: "排队中", running: "生成中", completed: "已完成", failed: "失败" };
const readableError = (error) => (
  !error ? "" : error === "AI service token is not configured" ? "AI 服务 Token 未配置" : error
);

function AnalysisResult({ job, onApply }) {
  if (job?.status !== "completed") {
    return <p className="muted">解析视频后，脚本、分镜和仿写参照会显示在这里。</p>;
  }
  const result = job.resultPayload || {};
  return (
    <div className="video-analysis-result">
      <div className="compact-row"><button className="btn btn-xs" onClick={() => onApply(job)}>填入稿件</button></div>
      <label className="field-label">视频脚本</label>
      <pre>{formatVideoScriptLines(result.videoScript || []) || "暂无脚本"}</pre>
      <label className="field-label">分镜拆解</label>
      <div className="shot-breakdown-list">
        {(result.shotBreakdown || []).map((item, index) => (
          <article key={`${item.timeRange}_${index}`}>
            <span>镜头 {item.shot || index + 1} · {item.timeRange || "未标注"}</span>
            <strong>{item.script || item.visualContent || "未生成内容"}</strong>
            <small>{[item.scriptRole, item.visualRole, item.shotSizeCamera, item.shootingTechnique].filter(Boolean).join(" · ")}</small>
          </article>
        ))}
        {!(result.shotBreakdown || []).length ? <p className="muted">暂无分镜拆解</p> : null}
      </div>
      <label className="field-label">仿写参照</label>
      <div className="rewrite-reference-list">
        {(result.rewriteReferences || []).map((item, index) => (
          <article key={`${item.title}_${index}`}>
            <strong>{item.title || `仿写参照 ${index + 1}`}</strong>
            {item.rhythm ? <small>{item.rhythm}</small> : null}
            <pre>{(item.script || []).join("\n") || "暂无仿写脚本"}</pre>
          </article>
        ))}
        {!(result.rewriteReferences || []).length ? <p className="muted">暂无仿写参照</p> : null}
      </div>
      <label className="field-label">复刻提示词</label>
      <pre>{result.replicationPrompt || "暂无复刻提示词"}</pre>
    </div>
  );
}

export default function VideoLinkAnalysisWorkspace({
  topicTitle,
  targetPlatform,
  linkText,
  onLinkTextChange,
  onAnalyze,
  busy,
  linkReference,
  activeJob,
  onApply,
  jobs = [],
  onSelectJob,
}) {
  const isBusy = busy === "video-extract" || busy === "video-analysis";
  return (
    <section className="video-link-analysis-workspace" aria-label="视频链接解析与 AI 脚本分析">
      <div className="glass-card generation-panel video-link-analysis-input">
        <div className="section-row">
          <div><h3>链接解析与 AI 脚本分析</h3><small className="muted">粘贴视频链接，自动提取脚本、分镜和复刻提示词</small></div>
          <span className="muted">{targetPlatform}</span>
        </div>
        <p className="video-topic-title">{topicTitle || "未命名选题"}</p>
        <label className="field-label">分享链接</label>
        <textarea value={linkText} onChange={(event) => onLinkTextChange(event.target.value)} rows={3} placeholder="粘贴抖音/小红书/快手分享文本..." />
        <button className="btn btn-sm btn-primary" disabled={isBusy || !linkText.trim()} onClick={onAnalyze}>
          {busy === "video-extract" ? "解析中..." : busy === "video-analysis" ? "分析中..." : "解析并分析视频"}
        </button>
        {linkReference ? (
          <div className="link-reference-card">
            <strong>{linkReference.title || "已解析内容"}</strong>
            <small>{linkReference.platform} · {(linkReference.images || []).length} 图 · {(linkReference.videos || []).length} 视频</small>
            {linkReference.description ? <p className="link-reference-desc">{linkReference.description}</p> : null}
          </div>
        ) : <p className="muted">链接解析入口位于视频页顶部，解析任务完成后可直接填入导演工作台。</p>}
      </div>

      <aside className="glass-card generation-panel video-analysis-aside">
        <div className="section-row">
          <h3>视频解析结果</h3>
          {activeJob ? <span className={`badge job-${activeJob.status}`}>{STATUS_TEXT[activeJob.status] || activeJob.status}</span> : null}
        </div>
        {activeJob?.error ? <p className="inline-error">{readableError(activeJob.error)}</p> : null}
        <AnalysisResult job={activeJob} onApply={onApply} />
        <div className="side-section-title" style={{ marginTop: 16 }}><h3>视频解析历史</h3></div>
        <div className="history-list">
          {jobs.slice(0, 10).map((job) => {
            const fallbackTitle = job.sourceUrl ? job.sourceUrl.split("/").pop()?.slice(0, 25) : "";
            return (
              <button key={job.id} onClick={() => onSelectJob(job)} title={job.title || job.sourceUrl || ""}>
                <span>{job.title || fallbackTitle || "未命名解析"}</span>
                <small>{job.platform || ""} · {job.status ? STATUS_TEXT[job.status] || job.status : ""}</small>
              </button>
            );
          })}
          {!jobs.length ? <p className="muted">暂无视频解析记录</p> : null}
        </div>
      </aside>
    </section>
  );
}
