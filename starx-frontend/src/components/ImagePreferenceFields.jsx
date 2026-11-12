import {
  CREATIVITY_LEVEL_OPTIONS,
  IMAGE_COUNT_OPTIONS,
  IMAGE_RATIO_OPTIONS,
  VISUAL_STYLE_OPTIONS,
} from "../utils/creationPreferences";

const renderOptions = (options) => options.map(({ value, label }) => (
  <option key={value} value={value}>{label}</option>
));

export default function ImagePreferenceFields({ preferences, onChange }) {
  const seriesDisabled = preferences.imageCount === 1;

  return (
    <>
      <div>
        <label htmlFor="creation-image-count">生成张数</label>
        <select
          id="creation-image-count"
          value={preferences.imageCount}
          onChange={(event) => onChange("imageCount", Number(event.target.value))}
        >
          {renderOptions(IMAGE_COUNT_OPTIONS)}
        </select>
      </div>
      <div>
        <span className="creation-preference-label">图片组织</span>
        <div className="creation-preference-segments" role="group" aria-label="图片组织方式">
          <button
            type="button"
            className={preferences.collectionMode === "independent" ? "active" : ""}
            aria-pressed={preferences.collectionMode === "independent"}
            onClick={() => onChange("collectionMode", "independent")}
          >
            独立图片
          </button>
          <button
            type="button"
            className={preferences.collectionMode === "series" ? "active" : ""}
            aria-pressed={preferences.collectionMode === "series"}
            disabled={seriesDisabled}
            title={seriesDisabled ? "生成 2 张及以上时可选择系列图" : ""}
            onClick={() => onChange("collectionMode", "series")}
          >
            系列图
          </button>
        </div>
      </div>
      <div>
        <label htmlFor="creation-image-ratio">图片比例</label>
        <select id="creation-image-ratio" value={preferences.ratio} onChange={(event) => onChange("ratio", event.target.value)}>
          {renderOptions(IMAGE_RATIO_OPTIONS)}
        </select>
      </div>
      <div>
        <label htmlFor="creation-creativity-level">创意程度</label>
        <select
          id="creation-creativity-level"
          value={preferences.creativityLevel}
          onChange={(event) => onChange("creativityLevel", event.target.value)}
        >
          {renderOptions(CREATIVITY_LEVEL_OPTIONS)}
        </select>
      </div>
      <div className="creation-preference-full">
        <label htmlFor="creation-visual-style">视觉风格</label>
        <select id="creation-visual-style" value={preferences.visualStyle} onChange={(event) => onChange("visualStyle", event.target.value)}>
          {renderOptions(VISUAL_STYLE_OPTIONS)}
        </select>
      </div>
    </>
  );
}
