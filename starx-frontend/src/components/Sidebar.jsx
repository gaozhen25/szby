const items = [
  ["account", "♙", "账号档案"],
  ["report", "▤", "账号报告"],
  ["topic", "♧", "选题中心"],
  ["creation", "♢", "内容创作"],
  ["process", "⌘", "流程管理"],
  ["competitor", "⌕", "竞品监控"],
  ["hotspot", "♨", "榜单聚合"],
  ["dashboard", "▥", "数据看板"],
  ["toolbox", "⌕", "工具箱"],
];

export default function Sidebar({ activePage, setActivePage, onOpenCreation }) {
  return (
    <nav className="side">
      {items.map(([key, icon, label]) => (
        <button
          key={key}
          className={`side-item ${activePage === key ? "on" : ""}`}
          onClick={() => key === "creation" ? onOpenCreation?.() : setActivePage(key)}
        >
          <span>{icon}</span>
          {label}
        </button>
      ))}
    </nav>
  );
}
