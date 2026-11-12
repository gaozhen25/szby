import { useEffect, useRef, useState } from "react";

import MediaLightbox, { useMediaLightbox } from "../MediaLightbox";
import {
  KNOWLEDGE_BASE_FIELD_OPTIONS,
  createEmptyKnowledgeBaseForm,
  normalizeKnowledgeBasePayload,
} from "../../utils/accountProfileForm";

const knowledgeBaseFieldLabels = {
  productIntro: "产品介绍",
  brandStory: "品牌故事",
  price: "价格",
  logoUrl: "Logo 链接",
  imageMaterials: "图片素材",
  contactInfo: "联系方式",
  websiteUrl: "官网链接",
};

const industries = [
  "美妆护肤",
  "服装鞋帽",
  "食品饮料",
  "母婴亲子",
  "数码科技",
  "家居生活",
  "教育培训",
  "医疗健康",
  "其他",
];

function buildFormFromKnowledgeBase(knowledgeBase) {
  const emptyForm = createEmptyKnowledgeBaseForm();
  if (!knowledgeBase) return { ...emptyForm, imageMaterials: [] };
  return {
    ...emptyForm,
    ...knowledgeBase,
    imageMaterials: Array.isArray(knowledgeBase.imageMaterials) && knowledgeBase.imageMaterials.length > 0
      ? knowledgeBase.imageMaterials
      : [],
    enabledFields: {
      ...emptyForm.enabledFields,
      ...(knowledgeBase.enabledFields || {}),
    },
  };
}

export default function KnowledgeBaseEditor({ app, onCancel, onBusyChange }) {
  const [form, setForm] = useState(() => buildFormFromKnowledgeBase(app.editingKnowledgeBase));
  const [step, setStep] = useState(1);
  const [isSaving, setIsSaving] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const savingRef = useRef(false);
  const uploadingRef = useRef(false);
  const mountedRef = useRef(true);
  const mediaLightbox = useMediaLightbox();

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    setForm(buildFormFromKnowledgeBase(app.editingKnowledgeBase));
    setStep(1);
  }, [app.editingKnowledgeBase]);

  const updateField = (key, value) => {
    setForm((previous) => ({ ...previous, [key]: value }));
  };

  const removeImageMaterial = (index) => {
    setForm((previous) => {
      const nextMaterials = previous.imageMaterials.filter((_, itemIndex) => itemIndex !== index);
      return {
        ...previous,
        imageMaterials: nextMaterials,
      };
    });
  };

  const previewImageMaterial = (index) => {
    const slides = form.imageMaterials.map((url, imageIndex) => ({
      src: url,
      downloadFilename: `knowledge-base-material-${imageIndex + 1}.png`,
    }));
    mediaLightbox.openMedia(slides, index);
  };

  const uploadImageMaterials = async (event) => {
    const files = Array.from(event.target.files || []);
    event.target.value = "";
    if (!files.length || uploadingRef.current) return;

    uploadingRef.current = true;
    setIsUploading(true);
    onBusyChange(true);
    try {
      const uploaded = await app.uploadKnowledgeBaseImages(files);
      const uploadedUrls = uploaded.map((item) => item.url).filter(Boolean);
      setForm((previous) => ({
        ...previous,
        imageMaterials: [...new Set([
          ...previous.imageMaterials.map((item) => item.trim()).filter(Boolean),
          ...uploadedUrls,
        ])],
      }));
      app.addToast?.(`已上传 ${uploadedUrls.length} 张图片素材`, "success");
    } catch (error) {
      app.addToast?.(error?.message || "图片素材上传失败，请稍后重试", "warning");
    } finally {
      uploadingRef.current = false;
      if (mountedRef.current) setIsUploading(false);
      onBusyChange(false);
    }
  };

  const toggleEnabledField = (key) => {
    setForm((previous) => ({
      ...previous,
      enabledFields: {
        ...previous.enabledFields,
        [key]: !previous.enabledFields[key],
      },
    }));
  };

  const validateBasicFields = () => {
    if (form.name.trim() && form.productName.trim()) return true;
    app.addToast?.("请至少填写知识库名称和产品名称", "warning");
    return false;
  };

  const submit = async () => {
    if (isSaving || isUploading) return;
    if (savingRef.current || !validateBasicFields()) return;

    const payload = normalizeKnowledgeBasePayload(form);
    savingRef.current = true;
    setIsSaving(true);
    onBusyChange(true);
    try {
      if (app.editingKnowledgeBase?.id) {
        await app.updateKnowledgeBase(app.editingKnowledgeBase.id, payload);
      } else {
        await app.createKnowledgeBase(payload);
      }
    } catch (error) {
      app.addToast?.(error?.message || "保存知识库失败，请稍后重试", "warning");
    } finally {
      savingRef.current = false;
      if (mountedRef.current) setIsSaving(false);
      onBusyChange(false);
    }
  };

  const goToContentStep = () => {
    if (!validateBasicFields()) return;
    setStep(2);
  };

  const title = app.editingKnowledgeBase?.id ? "编辑知识库" : "新建知识库";
  const stepLabels = ["基础资料", "内容配置"];

  return (
    <section className="knowledge-editor-shell" aria-labelledby="knowledge-editor-heading">
      <header className="knowledge-editor-header">
        <span className="knowledge-library-kicker">KNOWLEDGE EDITOR</span>
        <h3 id="knowledge-editor-heading">{title}</h3>
        <p>填写真实品牌资料，并决定哪些字段会提供给下游内容生成流程。</p>
      </header>

      <div className="knowledge-wizard-steps" aria-label={`第 ${step} 步，共 2 步`}>
        {stepLabels.map((label, index) => {
          const stepNumber = index + 1;
          return (
            <div
              className={`knowledge-wizard-step ${step === stepNumber ? "active" : ""} ${step > stepNumber ? "completed" : ""}`}
              key={label}
            >
              <span>{step > stepNumber ? "✓" : stepNumber}</span>
              <strong>{label}</strong>
            </div>
          );
        })}
      </div>

      <div
        className="knowledge-editor-fieldset"
        inert={isSaving || isUploading || undefined}
        aria-busy={isSaving || isUploading || undefined}
      >
        <div className="knowledge-editor-scroll">
        {step === 1 ? (
          <div className="knowledge-editor-body">
            <div className="knowledge-editor-form">
              <div className="knowledge-form-grid">
                <label>
                  <span>知识库名称 <b aria-hidden="true">*</b></span>
                  <input
                    data-autofocus
                    value={form.name}
                    onChange={(event) => updateField("name", event.target.value)}
                    placeholder="例如：星颜品牌基础库"
                  />
                </label>
                <label>
                  <span>品牌 / 产品名称 <b aria-hidden="true">*</b></span>
                  <input
                    value={form.productName}
                    onChange={(event) => updateField("productName", event.target.value)}
                    placeholder="例如：星颜修护精华"
                  />
                </label>
              </div>

              <div className="knowledge-form-grid">
                <label>
                  <span>所属行业</span>
                  <select
                    value={form.industry || ""}
                    onChange={(event) => updateField("industry", event.target.value)}
                  >
                    <option value="">请选择行业</option>
                    {industries.map((industry) => (
                      <option key={industry} value={industry}>{industry}</option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>官网链接</span>
                  <input
                    value={form.websiteUrl}
                    onChange={(event) => updateField("websiteUrl", event.target.value)}
                    placeholder="https://brand.example.com"
                  />
                  <small>用于识别品牌公开信息，可留空。</small>
                </label>
              </div>

              <label>
                <span>产品介绍</span>
                <textarea
                  value={form.productIntro}
                  onChange={(event) => updateField("productIntro", event.target.value)}
                  rows="4"
                  placeholder="介绍产品定位、核心卖点和适用场景"
                />
                <small>内容生成时会用它理解品牌与产品定位。</small>
              </label>
            </div>

            <aside className="knowledge-editor-aside">
              <strong>资料将用于</strong>
              <ul>
                <li><span aria-hidden="true">✦</span><div><b>内容创作</b><small>生成符合品牌调性的内容</small></div></li>
                <li><span aria-hidden="true">◎</span><div><b>账号绑定</b><small>为账号提供统一品牌上下文</small></div></li>
                <li><span aria-hidden="true">▣</span><div><b>资产沉淀</b><small>集中维护可复用资料</small></div></li>
              </ul>
            </aside>
          </div>
        ) : (
          <div className="knowledge-editor-body">
            <div className="knowledge-editor-form">
              <section className="knowledge-form-section">
                <div className="knowledge-form-section-heading">
                  <div>
                    <h4>图片素材</h4>
                    <p>从本地选择图片，后端会先上传到 OSS，再将链接写入知识库。</p>
                  </div>
                  <label className="btn btn-sm knowledge-material-upload">
                    {isUploading ? "上传中…" : "+ 上传本地图片"}
                    <input
                      type="file"
                      accept="image/jpeg,image/png,image/webp"
                      multiple
                      onChange={uploadImageMaterials}
                      aria-label="上传知识库图片素材"
                    />
                  </label>
                </div>
                {form.imageMaterials.length > 0 ? (
                  <div className="knowledge-material-list">
                    {form.imageMaterials.map((material, index) => (
                      <div className="knowledge-material-card" key={`${material}-${index}`}>
                        <button
                          className="knowledge-material-preview"
                          type="button"
                          title="双击预览图片"
                          aria-label={`预览图片素材 ${index + 1}`}
                          onDoubleClick={() => previewImageMaterial(index)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter") previewImageMaterial(index);
                          }}
                        >
                          <img src={material} alt={`图片素材 ${index + 1}`} />
                        </button>
                        <button
                          className="knowledge-material-remove"
                          type="button"
                          aria-label={`删除图片素材 ${index + 1}`}
                          onClick={() => removeImageMaterial(index)}
                        >
                          ×
                        </button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="knowledge-material-empty">尚未上传图片，支持 JPG、PNG、WebP，单张不超过 10 MB。</div>
                )}
              </section>

              <section className="knowledge-form-section">
                <div className="knowledge-form-section-heading">
                  <div>
                    <h4>下游字段启用</h4>
                    <p>关闭字段不会清空内容，只会停止默认向下游提供。</p>
                  </div>
                </div>
                <div className="knowledge-field-toggles">
                  {KNOWLEDGE_BASE_FIELD_OPTIONS.map((fieldKey) => (
                    <button
                      className={form.enabledFields[fieldKey] ? "active" : ""}
                      key={fieldKey}
                      type="button"
                      aria-pressed={Boolean(form.enabledFields[fieldKey])}
                      onClick={() => toggleEnabledField(fieldKey)}
                    >
                      <span>{knowledgeBaseFieldLabels[fieldKey]}</span>
                      <small>{form.enabledFields[fieldKey] ? "已启用" : "未启用"}</small>
                    </button>
                  ))}
                </div>
              </section>

              <div className="knowledge-form-grid">
                <label>
                  <span>价格</span>
                  <input value={form.price} onChange={(event) => updateField("price", event.target.value)} placeholder="例如：299 元" />
                </label>
                <label>
                  <span>联系方式</span>
                  <input value={form.contactInfo} onChange={(event) => updateField("contactInfo", event.target.value)} placeholder="例如：客服微信或电话" />
                </label>
              </div>

              <label>
                <span>Logo 链接</span>
                <input value={form.logoUrl} onChange={(event) => updateField("logoUrl", event.target.value)} placeholder="https://cdn.example.com/logo.png" />
              </label>

              <label>
                <span>品牌故事</span>
                <textarea value={form.brandStory} onChange={(event) => updateField("brandStory", event.target.value)} rows="4" placeholder="介绍品牌背景、价值主张与故事线" />
              </label>
            </div>

            <aside className="knowledge-editor-aside knowledge-editor-summary">
              <strong>发布前确认</strong>
              <dl>
                <div><dt>知识库</dt><dd>{form.name || "尚未填写"}</dd></div>
                <div><dt>产品</dt><dd>{form.productName || "尚未填写"}</dd></div>
                <div><dt>图片素材</dt><dd>{form.imageMaterials.filter((item) => item.trim()).length} 条</dd></div>
                <div><dt>启用字段</dt><dd>{Object.values(form.enabledFields).filter(Boolean).length} 项</dd></div>
              </dl>
              <p>点击保存后将立即更新真实知识库数据。</p>
            </aside>
          </div>
        )}
        </div>
      </div>

      <footer className="knowledge-editor-footer">
        <span>第 {step} 步，共 2 步</span>
        <div className="button-row">
          <button
            className="btn"
            type="button"
            disabled={isSaving || isUploading}
            onClick={() => step === 1 ? onCancel() : setStep(1)}
          >
            {step === 1 ? "返回知识库" : "上一步"}
          </button>
          {step === 1 ? (
            <button className="btn btn-primary" type="button" disabled={isSaving || isUploading} onClick={goToContentStep}>
              下一步
            </button>
          ) : (
            <button className="btn btn-primary" type="button" disabled={isSaving || isUploading} onClick={submit}>
              {isUploading ? "图片上传中…" : isSaving ? "保存中…" : app.editingKnowledgeBase?.id ? "保存修改" : "创建知识库"}
            </button>
          )}
        </div>
      </footer>

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
