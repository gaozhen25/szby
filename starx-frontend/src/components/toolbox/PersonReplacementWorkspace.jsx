import { useEffect, useMemo, useState } from "react";

import { starxApi } from "../../api/starx";
import MediaLightbox, { useMediaLightbox } from "../MediaLightbox";
import { createImageSlide } from "../../utils/mediaLightbox";

const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled"]);
const STATUS_TEXT = {
  pending: "排队中",
  running: "正在生成",
  completed: "已完成",
  failed: "生成失败",
  cancelled: "已取消",
};
const RATIO_OPTIONS = ["1:1", "3:4", "4:3", "9:16", "16:9"];
const VARIANT_OPTIONS = [1, 2, 3, 4];
const MAX_SCENES = 12;
const SUBMIT_CONCURRENCY = 3;

function useObjectUrl(file) {
  const url = useMemo(() => (file ? URL.createObjectURL(file) : ""), [file]);
  useEffect(() => () => {
    if (url) URL.revokeObjectURL(url);
  }, [url]);
  return url;
}

function useObjectUrls(files) {
  const urls = useMemo(() => files.map((file) => URL.createObjectURL(file)), [files]);
  useEffect(() => () => urls.forEach((url) => URL.revokeObjectURL(url)), [urls]);
  return urls;
}

function greatestCommonDivisor(left, right) {
  let a = Math.abs(left);
  let b = Math.abs(right);
  while (b) [a, b] = [b, a % b];
  return a || 1;
}

async function inferImageRatio(file) {
  if (!file || typeof createImageBitmap !== "function") return "3:4";
  const bitmap = await createImageBitmap(file);
  try {
    const divisor = greatestCommonDivisor(bitmap.width, bitmap.height);
    return `${bitmap.width / divisor}:${bitmap.height / divisor}`;
  } finally {
    bitmap.close();
  }
}

function fileIdentity(file) {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

function friendlyGenerationError(error) {
  const message = String(error || "").trim();
  if (/ConnectError|ConnectTimeout|ReadTimeout|PoolTimeout|TransportError/i.test(message)) {
    return "上游生图服务连接失败，系统已自动重试；请稍后重新生成该场景。";
  }
  return message || "生成失败，请重新生成该场景。";
}

function PersonUpload({ file, previewUrl, disabled, onChange, onPreview }) {
  return (
    <label className={`person-replacement-person-upload ${file ? "has-image" : ""}`}>
      <input
        type="file"
        accept="image/png,image/jpeg,image/webp"
        disabled={disabled}
        aria-label="上传人物参考图"
        onChange={(event) => onChange(event.target.files?.[0] || null)}
      />
      {previewUrl ? (
        <img
          className="person-replacement-previewable"
          src={previewUrl}
          alt="人物参考图预览，双击查看大图"
          title="双击预览"
          tabIndex="0"
          onClick={(event) => event.preventDefault()}
          onDoubleClick={(event) => {
            event.preventDefault();
            onPreview();
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              onPreview();
            }
          }}
        />
      ) : (
        <span className="person-replacement-upload-icon" aria-hidden="true">＋</span>
      )}
      <span className="person-replacement-upload-copy">
        <strong>{file ? "人物参考图" : "上传人物参考图"}</strong>
        <small>{file ? "点击可替换人物" : "建议单人、面部清晰、半身或全身"}</small>
      </span>
    </label>
  );
}

function ScenePicker({ count, disabled, onFiles }) {
  const handleDrop = (event) => {
    event.preventDefault();
    if (!disabled) onFiles(event.dataTransfer.files);
  };

  return (
    <label
      className={`person-replacement-scene-picker ${count ? "compact" : ""}`}
      onDragOver={(event) => event.preventDefault()}
      onDrop={handleDrop}
    >
      <input
        type="file"
        accept="image/png,image/jpeg,image/webp"
        multiple
        disabled={disabled}
        aria-label="批量上传场景图"
        onChange={(event) => {
          onFiles(event.target.files);
          event.target.value = "";
        }}
      />
      <span className="person-replacement-upload-icon" aria-hidden="true">＋</span>
      <span>
        <strong>{count ? "继续添加场景" : "批量上传场景图"}</strong>
        <small>{count ? `已添加 ${count}/${MAX_SCENES} 张` : `拖拽或选择图片，最多 ${MAX_SCENES} 张`}</small>
      </span>
    </label>
  );
}

export default function PersonReplacementWorkspace({ app }) {
  const accountId = app.currentAccountId || app.currentAccount?.id || "";
  const [targetImages, setTargetImages] = useState([]);
  const [personImage, setPersonImage] = useState(null);
  const [ratioChoice, setRatioChoice] = useState("scene");
  const [variantsPerScene, setVariantsPerScene] = useState(1);
  const [submitting, setSubmitting] = useState(false);
  const [jobItems, setJobItems] = useState([]);
  const [downloadingJobId, setDownloadingJobId] = useState("");
  const [downloadingAll, setDownloadingAll] = useState(false);
  const targetPreviews = useObjectUrls(targetImages);
  const personPreview = useObjectUrl(personImage);
  const mediaLightbox = useMediaLightbox();
  const activeJobs = jobItems.filter((item) => item.job && !TERMINAL_STATUSES.has(item.job.status));
  const availableOutputItems = jobItems.flatMap((item) =>
    (item.job?.resultPayload?.images || []).map((image, variantIndex) => ({
      item,
      image,
      variantIndex,
      url: typeof image === "string" ? image : image?.url || "",
    })).filter(({ url }) => url)
  );
  const completedOutputItems = availableOutputItems.filter(({ item }) => item.job?.status === "completed");
  const expectedOutputCount = targetImages.length * variantsPerScene;
  const isActive = submitting || activeJobs.length > 0;
  const jobSignature = jobItems.map((item) => `${item.job?.id || "upload"}:${item.job?.status || "idle"}`).join("|");

  useEffect(() => {
    if (!accountId || !activeJobs.length) return undefined;
    let mounted = true;
    let polling = false;
    const poll = async () => {
      if (polling) return;
      polling = true;
      const snapshot = activeJobs;
      const updates = await Promise.all(snapshot.map(async (item) => {
        try {
          return { sceneIndex: item.sceneIndex, job: await starxApi.getGenerationJob(accountId, item.job.id) };
        } catch (error) {
          return { sceneIndex: item.sceneIndex, pollError: error.message || "状态获取失败" };
        }
      }));
      if (mounted) {
        const byScene = new Map(updates.map((update) => [update.sceneIndex, update]));
        setJobItems((current) => current.map((item) => {
          const update = byScene.get(item.sceneIndex);
          if (!update) return item;
          if (update.pollError) return { ...item, pollError: update.pollError };
          if (item.job?.status !== "completed" && update.job.status === "completed") {
            app.addToast?.(`场景 ${item.sceneIndex + 1} 人物替换完成`, "success");
          }
          if (item.job?.status !== "failed" && update.job.status === "failed") {
            app.addToast?.(
              `场景 ${item.sceneIndex + 1}：${friendlyGenerationError(update.job.error)}`,
              "warning",
            );
          }
          return { ...item, job: update.job, pollError: "" };
        }));
      }
      polling = false;
    };
    const timer = window.setInterval(poll, 2000);
    poll();
    return () => {
      mounted = false;
      window.clearInterval(timer);
    };
  }, [accountId, app.addToast, jobSignature]); // eslint-disable-line react-hooks/exhaustive-deps

  const addTargetImages = (fileList) => {
    const incoming = Array.from(fileList || []).filter((file) => file.type.startsWith("image/"));
    if (!incoming.length) return;
    setTargetImages((current) => {
      const known = new Set(current.map(fileIdentity));
      const unique = incoming.filter((file) => {
        const identity = fileIdentity(file);
        if (known.has(identity)) return false;
        known.add(identity);
        return true;
      });
      const next = [...current, ...unique].slice(0, MAX_SCENES);
      if (current.length + unique.length > MAX_SCENES) {
        app.addToast?.(`单次最多添加 ${MAX_SCENES} 张场景图`, "warning");
      }
      return next;
    });
  };

  const removeTargetImage = (index) => {
    if (isActive) return;
    setTargetImages((current) => current.filter((_, currentIndex) => currentIndex !== index));
  };

  const reset = () => {
    setTargetImages([]);
    setPersonImage(null);
    setRatioChoice("scene");
    setVariantsPerScene(1);
    setJobItems([]);
  };

  const resolveOutputRatios = async (images) => {
    if (ratioChoice === "person") {
      const personRatio = await inferImageRatio(personImage);
      return images.map(() => personRatio);
    }
    if (ratioChoice === "scene") return Promise.all(images.map(inferImageRatio));
    return images.map(() => ratioChoice);
  };

  const previewPerson = () => {
    mediaLightbox.openMedia([
      createImageSlide(personPreview, {
        title: "人物参考图",
        downloadFilename: personImage?.name || "人物参考图.png",
      }),
    ], 0);
  };

  const previewScene = (index) => {
    const slides = targetPreviews.map((url, sceneIndex) => createImageSlide(url, {
      title: `场景 ${sceneIndex + 1} · 原图`,
      downloadFilename: targetImages[sceneIndex]?.name || `场景-${sceneIndex + 1}.png`,
    }));
    mediaLightbox.openMedia(slides, index);
  };

  const previewResult = (sceneIndex, variantIndex) => {
    const slides = availableOutputItems.map(({ item, url, variantIndex: currentVariantIndex }) => createImageSlide(url, {
      title: `场景 ${item.sceneIndex + 1} · 结果 ${currentVariantIndex + 1}`,
      downloadFilename: `人物替换-${item.sceneIndex + 1}-${currentVariantIndex + 1}.png`,
    }));
    const index = availableOutputItems.findIndex(({ item, variantIndex: currentVariantIndex }) =>
      item.sceneIndex === sceneIndex && currentVariantIndex === variantIndex
    );
    mediaLightbox.openMedia(slides, Math.max(index, 0));
  };

  const downloadResult = async (item, variantIndex) => {
    if (!accountId || !item.job?.id || downloadingJobId) return;
    const downloadKey = `${item.job.id}:${variantIndex}`;
    setDownloadingJobId(downloadKey);
    try {
      const blob = await starxApi.downloadPersonReplacementResult(accountId, item.job.id, variantIndex);
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = `人物替换-${item.sceneIndex + 1}-${variantIndex + 1}.png`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    } catch (error) {
      app.addToast?.(error.message || "结果下载失败，请稍后重试", "warning");
    } finally {
      setDownloadingJobId("");
    }
  };

  const downloadAll = async () => {
    if (!completedOutputItems.length || downloadingAll) return;
    setDownloadingAll(true);
    try {
      const { default: JSZip } = await import("jszip");
      const zip = new JSZip();
      const blobs = await Promise.all(completedOutputItems.map(({ item, variantIndex }) =>
        starxApi.downloadPersonReplacementResult(accountId, item.job.id, variantIndex)
      ));
      blobs.forEach((blob, index) => {
        const output = completedOutputItems[index];
        zip.file(`人物替换-${output.item.sceneIndex + 1}-${output.variantIndex + 1}.png`, blob);
      });
      const archive = await zip.generateAsync({ type: "blob" });
      const objectUrl = URL.createObjectURL(archive);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = `人物替换-批量结果-${completedOutputItems.length}张.zip`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    } catch (error) {
      app.addToast?.(error.message || "批量下载失败，请稍后重试", "warning");
    } finally {
      setDownloadingAll(false);
    }
  };

  const submit = async (event) => {
    event.preventDefault();
    if (!accountId) {
      app.addToast?.("请先选择一个运营账号", "warning");
      return;
    }
    if (!targetImages.length || !personImage) {
      app.addToast?.("请上传人物参考图和至少一张场景图", "warning");
      return;
    }

    setSubmitting(true);
    setJobItems(targetImages.map((file, sceneIndex) => ({
      sceneIndex,
      fileName: file.name,
      job: null,
      uploadError: "",
    })));

    try {
      const ratios = await resolveOutputRatios(targetImages);
      const results = await starxApi.createPersonReplacementJobs(accountId, {
        targetImages,
        personImage,
        consentConfirmed: true,
        ratios,
        count: variantsPerScene,
        concurrency: SUBMIT_CONCURRENCY,
      });
      const createdCount = results.filter((result) => result.job).length;
      setJobItems((current) => current.map((item) => ({
        ...item,
        job: results[item.sceneIndex]?.job || null,
        uploadError: results[item.sceneIndex]?.error || "",
      })));
      if (createdCount) app.addToast?.(`已提交 ${createdCount} 个场景任务`, "success");
      if (createdCount < targetImages.length) {
        app.addToast?.(`${targetImages.length - createdCount} 个任务提交失败，请在结果区重试`, "warning");
      }
    } catch (error) {
      setJobItems((current) => current.map((item) => ({
        ...item,
        uploadError: error.message || "批量任务提交失败",
      })));
      app.addToast?.(error.message || "批量任务提交失败", "warning");
    } finally {
      setSubmitting(false);
    }
  };

  const retryItem = async (item) => {
    if (isActive || !targetImages[item.sceneIndex]) return;
    setSubmitting(true);
    setJobItems((current) => current.map((currentItem) =>
      currentItem.sceneIndex === item.sceneIndex
        ? { ...currentItem, job: null, uploadError: "", pollError: "" }
        : currentItem
    ));
    try {
      const [ratio] = await resolveOutputRatios([targetImages[item.sceneIndex]]);
      const [result] = await starxApi.createPersonReplacementJobs(accountId, {
        targetImages: [targetImages[item.sceneIndex]],
        personImage,
        consentConfirmed: true,
        ratios: [ratio],
        count: variantsPerScene,
        concurrency: 1,
      });
      setJobItems((current) => current.map((currentItem) =>
        currentItem.sceneIndex === item.sceneIndex
          ? { ...currentItem, job: result.job, uploadError: result.error || "" }
          : currentItem
      ));
      app.addToast?.(result.job ? `场景 ${item.sceneIndex + 1} 已重新提交` : result.error, result.job ? "success" : "warning");
    } catch (error) {
      setJobItems((current) => current.map((currentItem) =>
        currentItem.sceneIndex === item.sceneIndex
          ? { ...currentItem, uploadError: error.message || "重新提交失败" }
          : currentItem
      ));
      app.addToast?.(error.message || "重新提交失败", "warning");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="toolbox-workspace person-replacement-workspace">
      <header className="toolbox-workspace-header person-replacement-header">
        <div>
          <span>AI 图片工具 · 支持批量</span>
          <h2>让同一个人物，自然出现在每个场景</h2>
          <p>上传 1 张人物参考图与多张场景图，系统会为每个场景生成一张替换结果。</p>
        </div>
        {jobItems.length ? (
          <button className="btn btn-sm" type="button" disabled={isActive} onClick={reset}>新建一批</button>
        ) : null}
      </header>

      <ol className="person-replacement-steps" aria-label="人物替换步骤">
        <li className={personImage ? "complete" : "active"}><span>1</span><strong>确定人物</strong></li>
        <li className={targetImages.length ? "complete" : personImage ? "active" : ""}><span>2</span><strong>添加场景</strong></li>
        <li className={jobItems.length ? "complete" : targetImages.length && personImage ? "active" : ""}><span>3</span><strong>生成结果</strong></li>
      </ol>

      <form className="glass-card person-replacement-card" onSubmit={submit}>
        <div className="person-replacement-inputs">
          <section className="person-replacement-person-column">
            <div className="person-replacement-section-heading">
              <span className="person-replacement-step-number">1</span>
              <div><h3>人物参考</h3><p>所有场景都将替换为这个人物</p></div>
            </div>
            <PersonUpload
              file={personImage}
              previewUrl={personPreview}
              disabled={isActive}
              onChange={setPersonImage}
              onPreview={previewPerson}
            />
            <div className="person-replacement-tip">
              <span aria-hidden="true">✦</span>
              <p><strong>选择高质量参考图</strong><br />面部无遮挡、光线均匀，人物特征会更稳定。</p>
            </div>
          </section>

          <section className="person-replacement-scenes-column">
            <div className="person-replacement-section-heading">
              <span className="person-replacement-step-number">2</span>
              <div><h3>场景队列</h3><p>每张场景图会生成 1 张结果</p></div>
              {targetImages.length ? <span className="person-replacement-count">{targetImages.length} 张</span> : null}
            </div>
            <div className={`person-replacement-scenes-grid ${targetImages.length ? "" : "empty"}`}>
              {targetImages.map((file, index) => (
                <article className="person-replacement-scene-card" key={fileIdentity(file)}>
                  <img
                    className="person-replacement-previewable"
                    src={targetPreviews[index]}
                    alt={`场景 ${index + 1} 预览，双击查看大图`}
                    title="双击预览"
                    tabIndex="0"
                    onDoubleClick={() => previewScene(index)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") previewScene(index);
                    }}
                  />
                  <span className="person-replacement-scene-index">{index + 1}</span>
                  <button
                    type="button"
                    aria-label={`移除场景 ${index + 1}`}
                    disabled={isActive}
                    onClick={() => removeTargetImage(index)}
                  >×</button>
                  <small title={file.name}>{file.name}</small>
                </article>
              ))}
              {targetImages.length < MAX_SCENES ? (
                <ScenePicker count={targetImages.length} disabled={isActive} onFiles={addTargetImages} />
              ) : null}
            </div>
          </section>
        </div>

        <div className="person-replacement-settings">
          <label className="person-replacement-ratio">
            <span>输出比例</span>
            <select disabled={isActive} value={ratioChoice} onChange={(event) => setRatioChoice(event.target.value)}>
              <option value="person">与人物参考图相同</option>
              <option value="scene">与场景参考图相同</option>
              {RATIO_OPTIONS.map((ratio) => <option key={ratio} value={ratio}>{ratio}</option>)}
            </select>
            <small>选择“与场景参考图相同”时，每张结果分别保持对应场景的宽高比。</small>
          </label>
          <label className="person-replacement-variant-count">
            <span>每个场景生成</span>
            <select
              disabled={isActive}
              value={variantsPerScene}
              onChange={(event) => setVariantsPerScene(Number(event.target.value))}
            >
              {VARIANT_OPTIONS.map((count) => (
                <option key={count} value={count}>{count} 张</option>
              ))}
            </select>
            <small>同一场景可生成多个不同结果供选择。</small>
          </label>
          <div className="person-replacement-summary" aria-live="polite">
            <span>预计生成</span><strong>{expectedOutputCount} 张</strong>
          </div>
        </div>

        <div className="person-replacement-action-bar">
          <button
            className="btn btn-primary person-replacement-submit"
            type="submit"
            disabled={isActive || !targetImages.length || !personImage}
          >
            {submitting ? `正在提交 ${targetImages.length} 个任务…` : `生成 ${expectedOutputCount} 张图片`}
          </button>
        </div>
      </form>

      {jobItems.length ? (
        <section className="glass-card person-replacement-result" aria-live="polite">
          <div className="section-row person-replacement-result-heading">
            <div>
              <span className="person-replacement-eyebrow">生成结果</span>
              <h3>{completedOutputItems.length}/{jobItems.length * variantsPerScene} 张已完成</h3>
              <p className="muted">{isActive ? "任务正在后台处理，请保持页面开启以查看实时进度。" : "本批任务已处理完毕。"}</p>
            </div>
            {completedOutputItems.length > 1 ? (
              <button className="btn btn-primary" type="button" disabled={downloadingAll} onClick={downloadAll}>
                {downloadingAll ? "正在打包…" : `下载全部（${completedOutputItems.length}）`}
              </button>
            ) : null}
          </div>
          <div className="person-replacement-batch-progress" aria-hidden="true">
            <span style={{ width: `${jobItems.length ? (completedOutputItems.length / (jobItems.length * variantsPerScene)) * 100 : 0}%` }} />
          </div>
          <div className="person-replacement-results-grid">
            {jobItems.map((item) => {
              const images = item.job?.resultPayload?.images || [];
              const persistenceStatus = item.job?.resultPayload?.persistenceStatus || "";
              const status = item.uploadError ? "failed" : item.job?.status || "uploading";
              const stageText = item.job?.currentStage === "image_persisting"
                ? "图片已生成，正在后台转存"
                : STATUS_TEXT[status] || "正在上传";
              const generatedCount = images.filter((image) =>
                typeof image === "string" ? image : image?.url
              ).length;
              return (
                <article className={`person-replacement-result-group is-${status}`} key={item.sceneIndex}>
                  <header className="person-replacement-result-group-header">
                    <img
                      className="person-replacement-previewable"
                      src={targetPreviews[item.sceneIndex]}
                      alt={`场景 ${item.sceneIndex + 1} 原图，双击查看大图`}
                      title="双击预览场景原图"
                      tabIndex="0"
                      onDoubleClick={() => previewScene(item.sceneIndex)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") previewScene(item.sceneIndex);
                      }}
                    />
                    <div>
                      <strong>场景 {item.sceneIndex + 1}</strong>
                      <small title={item.fileName}>{item.fileName}</small>
                    </div>
                    <span className={`person-replacement-group-status is-${status}`}>
                      {status === "completed" ? `${generatedCount}/${variantsPerScene} 张完成` : stageText}
                    </span>
                    {status === "failed" ? (
                      <button className="btn btn-sm" type="button" disabled={isActive} onClick={() => retryItem(item)}>
                        重新生成本场景
                      </button>
                    ) : null}
                  </header>

                  <div className="person-replacement-result-variants">
                    {Array.from({ length: variantsPerScene }, (_, variantIndex) => {
                      const image = images[variantIndex];
                      const resultUrl = typeof image === "string" ? image : image?.url || "";
                      const displayStatus = status === "completed" && !resultUrl ? "failed" : status;
                      const downloadKey = `${item.job?.id || ""}:${variantIndex}`;
                      return (
                        <article
                          className={`person-replacement-result-card is-${displayStatus}`}
                          key={`${item.sceneIndex}:${variantIndex}`}
                        >
                          <div className="person-replacement-result-media">
                            {resultUrl ? (
                      <img
                        className="person-replacement-previewable"
                        src={resultUrl}
                        alt={`场景 ${item.sceneIndex + 1} 结果 ${variantIndex + 1}，双击查看大图`}
                        title="双击预览"
                        tabIndex="0"
                        onDoubleClick={() => previewResult(item.sceneIndex, variantIndex)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") previewResult(item.sceneIndex, variantIndex);
                        }}
                      />
                            ) : (
                              <>
                                <img className="is-placeholder" src={targetPreviews[item.sceneIndex]} alt="" />
                                <span className="person-replacement-result-overlay">
                                  {displayStatus === "failed" ? "!" : `${item.job?.progress || 0}%`}
                                </span>
                              </>
                            )}
                            <span className={`person-replacement-status is-${displayStatus}`}>
                              {displayStatus === "failed" && status === "completed" ? "结果缺失" : stageText}
                            </span>
                          </div>
                          <div className="person-replacement-result-meta">
                            <strong>结果 {variantIndex + 1}</strong>
                            {resultUrl ? (
                              <button
                                className="btn btn-sm"
                                type="button"
                                disabled={downloadingJobId === downloadKey}
                                onClick={() => downloadResult(item, variantIndex)}
                              >
                                {downloadingJobId === downloadKey ? "下载中…" : "下载原图"}
                              </button>
                            ) : null}
                          </div>
                        </article>
                      );
                    })}
                  </div>
                  {item.uploadError || item.job?.error || item.pollError ? (
                    <p className="dh-error">
                      {friendlyGenerationError(item.uploadError || item.job?.error || item.pollError)}
                    </p>
                  ) : null}
                  {persistenceStatus === "failed" ? (
                    <p className="dh-error person-replacement-persistence">结果可查看，但转存失败，请及时下载。</p>
                  ) : null}
                </article>
              );
            })}
          </div>
        </section>
      ) : null}

      <MediaLightbox
        open={mediaLightbox.open}
        index={mediaLightbox.index}
        slides={mediaLightbox.slides}
        onClose={mediaLightbox.closeMedia}
        onIndexChange={mediaLightbox.setMediaIndex}
      />
    </section>
  );
}
