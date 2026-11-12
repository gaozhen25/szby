const TOOL_ITEMS = [
  { id: "ai", icon: "🎨", title: "AI对话生图", description: "对话式生成图片" },
  { id: "person-replacement", icon: "🎭", title: "AI 人物替换", description: "把场景人物换成目标人物" },
  { id: "script", icon: "📝", title: "脚本改写", description: "快速整理视频脚本" },
  { id: "check", icon: "🚫", title: "违禁词检测", description: "检查并替换风险词" },
  { id: "digital-human", icon: "🧑‍💼", title: "数字人工作室", description: "克隆声音并生成口播视频" },
];

export default function ToolboxNav({ activeTool, onSelect }) {
  return (
    <aside className="toolbox-nav glass-card" aria-label="工具箱导航">
      <div className="toolbox-brand">✨ 工具箱</div>
      {TOOL_ITEMS.map((tool) => (
        <button
          key={tool.id}
          type="button"
          className={`toolbox-nav-item ${activeTool === tool.id ? "active" : ""}`}
          aria-current={activeTool === tool.id ? "page" : undefined}
          onClick={() => onSelect(tool.id)}
        >
          <span aria-hidden="true">{tool.icon}</span>
          <span>
            <strong>{tool.title}</strong>
            <small>{tool.description}</small>
          </span>
        </button>
      ))}
    </aside>
  );
}
