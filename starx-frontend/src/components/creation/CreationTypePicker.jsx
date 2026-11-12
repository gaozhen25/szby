const creationTypes = [
  {
    type: "image",
    eyebrow: "图文创作",
    description: "生成图文内容、种草笔记、攻略清单等",
    tags: ["种草笔记", "产品测评", "攻略清单", "图文合集"],
  },
  {
    type: "video",
    eyebrow: "视频创作",
    description: "生成视频脚本、短视频内容、口播视频等",
    tags: ["短视频脚本", "口播视频", "产品展示", "剧情内容"],
  },
];

function CreationTypeArtwork({ type }) {
  const isVideo = type === "video";

  return (
    <div className={`creation-type-artwork ${type}`} aria-hidden="true">
      <span className="creation-type-orbit" />
      <span className="creation-type-spark spark-one">✦</span>
      <span className="creation-type-spark spark-two">✦</span>
      <span className="creation-type-spark spark-three">✦</span>
      <span className="creation-type-spark spark-four">✦</span>
      <span className="creation-type-window">
        <i className="creation-type-window-controls" />
        {isVideo ? (
          <svg viewBox="0 0 64 64" role="presentation">
            <path d="M23 17.5v29l24-14.5-24-14.5Z" fill="currentColor" />
          </svg>
        ) : (
          <svg viewBox="0 0 64 64" role="presentation">
            <rect x="14" y="16" width="36" height="32" rx="5" fill="none" stroke="currentColor" strokeWidth="4" />
            <circle cx="39" cy="25" r="4" fill="currentColor" />
            <path d="m18 43 10-11 7 7 6-6 7 10H18Z" fill="currentColor" />
          </svg>
        )}
      </span>
    </div>
  );
}

export default function CreationTypePicker({ onSelect }) {
  return (
    <section className="creation-type-picker" aria-labelledby="creation-type-title">
      <header className="creation-type-heading">
        <h1 id="creation-type-title">选择你的创作方式 <span aria-hidden="true">👋</span></h1>
        <p>根据你的创作目标，选择最适合的内容形式开始创作</p>
      </header>

      <div className="creation-type-grid">
        {creationTypes.map((item) => (
          <article className={`creation-type-card ${item.type}`} key={item.type}>
            <CreationTypeArtwork type={item.type} />
            <div className="creation-type-copy">
              <h2>{item.eyebrow} <span aria-hidden="true">✦</span></h2>
              <p>{item.description}</p>
            </div>
            <ul className="creation-type-tags" aria-label={`${item.eyebrow}适用场景`}>
              {item.tags.map((tag) => <li key={tag}>{tag}</li>)}
            </ul>
            <button type="button" onClick={() => onSelect(item.type)}>
              选择{item.eyebrow} <span aria-hidden="true">→</span>
            </button>
          </article>
        ))}
      </div>

      <p className="creation-type-footnote">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <rect x="5" y="10" width="14" height="10" rx="2" />
          <path d="M8 10V7a4 4 0 0 1 8 0v3" />
        </svg>
        你随时可以在创作过程中切换创作方式
      </p>
    </section>
  );
}
