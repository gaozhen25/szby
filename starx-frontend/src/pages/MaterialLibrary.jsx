import { useMemo, useState } from "react";

import DigitalHumanEnrollmentPanel from "../components/digital-human/DigitalHumanEnrollmentPanel";
import DigitalHumanProfileGrid from "../components/digital-human/DigitalHumanProfileGrid";

export default function MaterialLibrary({ app }) {
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [showDigitalHumanCreate, setShowDigitalHumanCreate] = useState(false);
  const materials = useMemo(
    () => app.materials.filter((material) =>
      (filter === "all" || material.type === filter)
      && (`${material.name} ${material.tags.join(" ")}`).toLowerCase().includes(query.toLowerCase())
    ),
    [app.materials, filter, query],
  );
  const digitalHumans = useMemo(
    () => (app.digitalHumanProfiles || []).filter((profile) =>
      profile.name.toLowerCase().includes(query.toLowerCase())
    ),
    [app.digitalHumanProfiles, query],
  );
  const showRegular = filter !== "digital-human";
  const showDigitalHumans = filter === "all" || filter === "digital-human";
  const total = (showRegular ? materials.length : 0) + (showDigitalHumans ? digitalHumans.length : 0);
  const upload = () => app.saveMaterial({
    name: `手动上传_素材_${Date.now()}.jpg`,
    type: "image",
    tags: ["手动上传"],
    date: new Date().toISOString().slice(0, 10),
    thumb: "📤",
  });

  return <div>
    <div className="section-header">
      <h2>素材库 · <span className="hl">{app.currentAccount?.name}</span></h2>
      <span className="muted">共 {total} 个</span>
    </div>
    <div className="material-toolbar">
      <select value={filter} onChange={(event) => setFilter(event.target.value)}>
        <option value="all">全部类型</option>
        <option value="image">🖼️ 图片</option>
        <option value="video">🎬 视频</option>
        <option value="script">📝 脚本</option>
        <option value="digital-human">🧑‍💼 数字人</option>
      </select>
      <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索素材名称、标签…" />
    </div>

    {showDigitalHumans ? <section style={{ margin: "18px 0" }}>
      <div className="section-row">
        <h3>数字人资产</h3>
        <button className="btn btn-sm" type="button" onClick={() => setShowDigitalHumanCreate((value) => !value)}>
          {showDigitalHumanCreate ? "收起" : "+ 创建数字人"}
        </button>
      </div>
      {showDigitalHumanCreate ? <DigitalHumanEnrollmentPanel app={app} onCreated={() => setShowDigitalHumanCreate(false)} /> : null}
      <DigitalHumanProfileGrid app={app} profiles={digitalHumans} />
    </section> : null}

    {showRegular ? <>
      <div className="upload-zone" onClick={upload} style={{ margin: "18px 0" }}>＋<br />点击上传本地文件（模拟）</div>
      <div className="material-grid">{materials.map((material) => <article className="glass-card" key={material.id}>
        <div className="material-thumb">{String(material.thumb || "").startsWith("http")
          ? <img src={material.thumb} alt={material.name} />
          : material.thumb}</div>
        <div className="material-info">
          <h3>{material.name}</h3>
          <p className="muted">{material.tags.map((tag) => `#${tag}`).join(" ")} · {material.date}</p>
          <div className="button-row" style={{ marginTop: 8 }}>
            <button className="btn btn-xs" onClick={() => app.addToast("编辑素材信息（模拟）")}>✏️</button>
            <button className="btn btn-xs" onClick={() => app.addToast("素材下载中…", "success")}>⬇️</button>
            <button className="btn btn-xs btn-danger" onClick={() => app.deleteMaterial(material.id)}>🗑️</button>
          </div>
        </div>
      </article>)}</div>
    </> : null}
  </div>;
}
