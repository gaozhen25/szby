import { useEffect, useMemo, useState } from "react";

import DigitalHumanEnrollmentPanel from "../digital-human/DigitalHumanEnrollmentPanel";
import DigitalHumanGenerator from "../digital-human/DigitalHumanGenerator";
import DigitalHumanProfileGrid from "../digital-human/DigitalHumanProfileGrid";

const WORKFLOW_TABS = [
  {
    id: "create",
    step: "01",
    title: "创建数字人",
    description: "上传固定口播素材，完成形象和声音克隆。",
  },
  {
    id: "profiles",
    step: "02",
    title: "数字人管理",
    description: "查看状态、试听声音、停用不可用资产。",
  },
  {
    id: "generate",
    step: "03",
    title: "生成视频",
    description: "选择可用数字人，填写脚本并生成成片。",
  },
];

export default function DigitalHumanWorkspace({ app }) {
  const profiles = app.digitalHumanProfiles || [];
  const readyCount = profiles.filter((item) => item.status === "ready").length;
  const pendingCount = profiles.filter((item) => ["validating", "cloning_voice"].includes(item.status)).length;
  const failedCount = profiles.filter((item) => item.status === "failed").length;
  const [mode, setMode] = useState(readyCount ? "generate" : profiles.length ? "profiles" : "create");
  const activeIndex = Math.max(0, WORKFLOW_TABS.findIndex((item) => item.id === mode));
  const activeTab = WORKFLOW_TABS[activeIndex] || WORKFLOW_TABS[0];

  useEffect(() => {
    if (!pendingCount) return undefined;
    const timer = window.setInterval(() => app.refreshDigitalHumanProfiles().catch(() => {}), 5000);
    return () => window.clearInterval(timer);
  }, [app.refreshDigitalHumanProfiles, pendingCount]);

  const stats = useMemo(() => ([
    { label: "可生成", value: readyCount },
    { label: "处理中", value: pendingCount },
    { label: "异常", value: failedCount },
  ]), [failedCount, pendingCount, readyCount]);

  return (
    <div className="toolbox-workspace dh-workspace">
      <header className="dh-workspace-hero">
        <div className="dh-hero-copy">
          <span className="dh-kicker">DIGITAL HUMAN STUDIO</span>
          <h2>数字人工作室</h2>
          <p>先完成数字人资产创建，再在管理页确认状态，最后进入生成视频。每一步都可以直接跳转，不用来回猜入口。</p>
        </div>
        <div className="dh-hero-stats" aria-label="数字人资产状态">
          {stats.map((item) => (
            <span key={item.label}>
              <strong>{item.value}</strong>
              <small>{item.label}</small>
            </span>
          ))}
        </div>
      </header>

      <nav className="dh-flow-tabs" aria-label="数字人工作流">
        {WORKFLOW_TABS.map((tab, index) => {
          const active = mode === tab.id;
          const complete = index < activeIndex;
          return (
            <button
              className={active ? "active" : complete ? "complete" : ""}
              key={tab.id}
              type="button"
              aria-current={active ? "step" : undefined}
              onClick={() => setMode(tab.id)}
            >
              <span className="dh-flow-step">{tab.step}</span>
              <span>
                <strong>{tab.title}</strong>
                <small>{tab.description}</small>
              </span>
            </button>
          );
        })}
      </nav>

      <section className="dh-workspace-panel" aria-labelledby="dh-current-step-title">
        <div className="dh-panel-heading">
          <div>
            <span className="dh-kicker">{activeTab.step}</span>
            <h3 id="dh-current-step-title">{activeTab.title}</h3>
          </div>
          <div className="dh-panel-actions">
            {mode !== "create" ? (
              <button className="btn btn-xs" type="button" onClick={() => setMode("create")}>新建数字人</button>
            ) : null}
            {mode !== "generate" ? (
              <button className="btn btn-xs btn-primary" type="button" disabled={!readyCount} onClick={() => setMode("generate")}>去生成视频</button>
            ) : null}
          </div>
        </div>

        {mode === "generate" ? (
          <DigitalHumanGenerator app={app} onCreateProfile={() => setMode("create")} />
        ) : null}
        {mode === "profiles" ? (
          <DigitalHumanProfileGrid
            app={app}
            profiles={profiles}
            onCreateProfile={() => setMode("create")}
            onGenerateVideo={() => setMode("generate")}
          />
        ) : null}
        {mode === "create" ? (
          <DigitalHumanEnrollmentPanel app={app} onCreated={() => setMode("profiles")} />
        ) : null}
      </section>
    </div>
  );
}
