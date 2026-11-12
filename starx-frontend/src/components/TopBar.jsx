import { useEffect, useRef, useState } from "react";

import ThemeToggle from "./ThemeToggle";

export default function TopBar({ app, theme, setTheme }) {
  const [showAccount, setShowAccount] = useState(false);
  const [showStartMenu, setShowStartMenu] = useState(false);
  const [showDataMenu, setShowDataMenu] = useState(false);
  const startCloseTimerRef = useRef(0);
  const dataCloseTimerRef = useRef(0);

  useEffect(() => () => {
    window.clearTimeout(startCloseTimerRef.current);
    window.clearTimeout(dataCloseTimerRef.current);
  }, []);

  const openStartMenu = () => {
    window.clearTimeout(startCloseTimerRef.current);
    setShowDataMenu(false);
    setShowStartMenu(true);
  };
  const closeStartMenuSoon = () => {
    window.clearTimeout(startCloseTimerRef.current);
    startCloseTimerRef.current = window.setTimeout(() => setShowStartMenu(false), 120);
  };

  const openDataMenu = () => {
    window.clearTimeout(dataCloseTimerRef.current);
    setShowStartMenu(false);
    setShowDataMenu(true);
  };
  const closeDataMenuSoon = () => {
    window.clearTimeout(dataCloseTimerRef.current);
    dataCloseTimerRef.current = window.setTimeout(() => setShowDataMenu(false), 120);
  };

  return (
    <header className="bar">
      <div className="bar-left">
        <div className="logo">✦</div>
        <span className="brand">STARX<span>AI · 内容生产平台</span></span>
      </div>
      
      <nav className="bar-nav">
        {/* 开始 - 带下拉菜单 */}
        <div 
          className="nav-dropdown-wrapper"
          onMouseEnter={openStartMenu}
          onMouseLeave={closeStartMenuSoon}
        >
          <button 
            type="button"
            className={`nav-item ${["account", "report", "topic"].includes(app.activePage) ? "active" : ""}`}
            aria-expanded={showStartMenu}
            aria-haspopup="menu"
          >
            开始
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M6 9l6 6 6-6"/>
            </svg>
          </button>
          {showStartMenu && (
            <div className="nav-dropdown" role="menu" onMouseEnter={openStartMenu}>
              <button type="button" role="menuitem" onClick={() => { app.setActivePage("account"); app.setShowAddAccountModal(true); setShowStartMenu(false); }}>
                <span className="dropdown-icon">＋</span>
                <span className="dropdown-content">
                  <strong>新建账号</strong>
                  <small>创建新的运营账号</small>
                </span>
              </button>
              <button type="button" role="menuitem" onClick={() => { app.setActivePage("report"); setShowStartMenu(false); }}>
                <span className="dropdown-icon">📄</span>
                <span className="dropdown-content">
                  <strong>账号报告</strong>
                  <small>查看分析报告</small>
                </span>
              </button>
              <button type="button" role="menuitem" onClick={() => { app.setActivePage("topic"); setShowStartMenu(false); }}>
                <span className="dropdown-icon">📋</span>
                <span className="dropdown-content">
                  <strong>选题中心</strong>
                  <small>浏览今日选题</small>
                </span>
              </button>
            </div>
          )}
        </div>

        {/* 创作 */}
        <button 
          type="button"
          className={`nav-item ${app.activePage === "creation" ? "active" : ""}`}
          onClick={() => app.startBlankCreation?.()}
        >
          创作
        </button>

        {/* 数据复盘 - 带下拉菜单 */}
        <div 
          className="nav-dropdown-wrapper"
          onMouseEnter={openDataMenu}
          onMouseLeave={closeDataMenuSoon}
        >
          <button 
            type="button"
            className={`nav-item ${["dashboard", "competitor", "hotspot"].includes(app.activePage) ? "active" : ""}`}
            aria-expanded={showDataMenu}
            aria-haspopup="menu"
          >
            数据复盘
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M6 9l6 6 6-6"/>
            </svg>
          </button>
          {showDataMenu && (
            <div className="nav-dropdown" role="menu" onMouseEnter={openDataMenu}>
              <button type="button" role="menuitem" onClick={() => { app.setActivePage("dashboard"); setShowDataMenu(false); }}>
                <span className="dropdown-icon">📊</span>
                <span className="dropdown-content">
                  <strong>数据看板</strong>
                  <small>查看运营数据</small>
                </span>
              </button>
              <button type="button" role="menuitem" onClick={() => { app.setActivePage("competitor"); setShowDataMenu(false); }}>
                <span className="dropdown-icon">🔍</span>
                <span className="dropdown-content">
                  <strong>竞品监控</strong>
                  <small>监控竞品动态</small>
                </span>
              </button>
              <button type="button" role="menuitem" onClick={() => { app.setActivePage("hotspot"); setShowDataMenu(false); }}>
                <span className="dropdown-icon">♨</span>
                <span className="dropdown-content">
                  <strong>榜单聚合</strong>
                  <small>抖音热点宝话题榜</small>
                </span>
              </button>
            </div>
          )}
        </div>

        {/* 流程管理 */}
        <button 
          type="button"
          className={`nav-item ${app.activePage === "process" ? "active" : ""}`}
          onClick={() => app.setActivePage("process")}
        >
          流程
        </button>

        {/* 素材库 */}
        <button 
          type="button"
          className={`nav-item ${app.activePage === "material" ? "active" : ""}`}
          onClick={() => app.setActivePage("material")}
        >
          素材
        </button>
      </nav>

      <div className="bar-right">
        <ThemeToggle theme={theme} onChange={setTheme} />
        <div className="account-switch" onClick={() => setShowAccount(!showAccount)}>
          <div className="avatars">
            {app.accounts.slice(0, 3).map((account) => (
              <div className="avatar" key={account.id}>{account.avatar}</div>
            ))}
          </div>
          <span className="account-name">{app.currentAccount?.name}</span>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M6 9l6 6 6-6"/>
          </svg>
          
          {showAccount && (
            <div className="account-drop" onClick={(e) => e.stopPropagation()}>
              {app.accounts.map((account) => (
                <button
                  type="button"
                  key={account.id}
                  className={account.id === app.currentAccountId ? "current" : ""}
                  onClick={() => { app.switchAccount(account.id); setShowAccount(false); }}
                >
                  <i>{account.avatar}</i>
                  <span>
                    <strong>{account.name}</strong>
                    <small>{account.description}</small>
                  </span>
                  <em>{account.type}</em>
                </button>
              ))}
              <hr />
              <button type="button" className="manage" onClick={() => { app.setActivePage("account"); setShowAccount(false); }}>
                账号档案管理
              </button>
              <button type="button" className="manage logout" onClick={app.logout}>
                退出企业工作台
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
