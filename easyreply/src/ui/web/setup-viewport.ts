import { registerAppOverlayHost } from '@/lib/app-overlay-host';
import { applyChromeTheme, chromeThemeRootCss } from '@/ui/web/chrome-theme';
import { initPaneWidths } from '@/ui/web/pane-resize';
import { webColor, webFontSize, webLayout, webPageBg, webType } from '@/ui/web/theme';

const CSS_ID = 'qh-web-desktop-css';

const DESKTOP_CSS = `
    :root {
      ${chromeThemeRootCss()}
    }
    html, body, #root {
      height: 100%;
      margin: 0;
      overflow: hidden;
      background: ${webColor.bg};
    }
    .qh-web-shell.ant-layout {
      height: 100vh !important;
      max-height: 100vh;
      min-height: 100vh;
    }
    .qh-web-main.ant-layout-content {
      display: flex !important;
      flex-direction: column;
      height: 100vh !important;
      max-height: 100vh;
      min-height: 0;
      min-width: 0;
      overflow: hidden;
      background: ${webPageBg.main};
    }
    input::placeholder,
    textarea::placeholder,
    .ant-input::placeholder,
    .ant-input-affix-wrapper .ant-input::placeholder,
    .ant-input-outlined::placeholder,
    .ant-input-filled::placeholder,
    .ant-input-borderless::placeholder,
    .ant-input-css-var::placeholder {
      font-size: ${webType.placeholder.fontSize}px !important;
      font-weight: ${webType.placeholder.fontWeight} !important;
      line-height: ${webType.placeholder.lineHeight} !important;
      color: ${webColor.placeholder};
      opacity: 1;
    }
    .qh-web-shell .ant-layout-sider,
    .qh-web-shell .ant-layout-sider-children {
      background: var(--qh-sider-bg) !important;
      border-inline-end: none !important;
    }
    .qh-web-shell .ant-layout-sider {
      position: relative;
      flex: 0 0 var(--qh-pane-sider, ${webLayout.siderWidth}px) !important;
      width: var(--qh-pane-sider, ${webLayout.siderWidth}px) !important;
      max-width: var(--qh-pane-sider, ${webLayout.siderWidth}px) !important;
      min-width: var(--qh-pane-sider, ${webLayout.siderWidth}px) !important;
    }
    .qh-web-shell .ant-layout-sider-trigger {
      display: none !important;
    }
    .qh-web-shell .ant-layout-sider-children {
      display: flex !important;
      flex-direction: column;
      height: 100%;
      min-height: 0;
      overflow-x: hidden;
    }
    .qh-web-shell .qh-sider-nav.ant-menu {
      flex: 1 1 auto;
      min-height: 0;
      min-width: 0;
      overflow-x: hidden;
      overflow-y: auto;
    }
    .qh-web-shell .qh-sider-nav-rest.ant-menu {
      flex: 0 0 auto;
    }
    .qh-web-shell .qh-sider-nav .ant-menu-item {
      display: flex !important;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      box-sizing: border-box;
      width: auto !important;
      max-width: 100%;
      height: auto !important;
      line-height: 1.25 !important;
      margin-inline: 6px !important;
      padding: 10px 6px !important;
      white-space: normal;
      text-align: center;
    }
    .qh-web-shell .qh-sider-nav .ant-menu-item .ant-menu-item-icon {
      margin-inline-end: 0 !important;
      line-height: 1;
    }
    .qh-web-shell .qh-sider-nav .ant-menu-item .ant-menu-title-content {
      margin-inline-start: 0 !important;
      width: 100%;
      max-width: 100%;
      overflow: hidden;
      text-align: center;
      white-space: normal;
      word-break: break-word;
    }
    .qh-web-shell .qh-sider-nav .ant-menu-item .anticon {
      margin-inline-end: 0 !important;
    }
    .qh-sider-brand {
      flex: 0 0 auto;
      align-items: stretch;
      min-width: 0;
      padding: 12px 8px 10px;
    }
    .qh-sider-brand .ant-typography {
      margin: 0;
      width: 100%;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      text-align: center;
    }
    .qh-sider-brand-actor {
      display: flex;
      flex-direction: column;
      align-items: center;
      width: 100%;
      min-width: 0;
      gap: 6px;
    }
    .qh-sider-brand-actor-avatar.ant-avatar {
      --qh-sider-avatar: clamp(32px, calc(var(--qh-pane-sider, ${webLayout.siderWidth}px) * 0.42), 64px);
      width: var(--qh-sider-avatar) !important;
      height: var(--qh-sider-avatar) !important;
      flex: 0 0 var(--qh-sider-avatar);
      border-radius: 50% !important;
      overflow: hidden;
    }
    .qh-sider-brand-actor-avatar.ant-avatar img {
      width: 100%;
      height: 100%;
      object-fit: cover;
    }
    .qh-sider-brand-actor-avatar.ant-avatar .ant-avatar-string {
      font-size: calc(var(--qh-sider-avatar) * 0.38);
      font-weight: 600;
      line-height: 1;
    }
    .qh-sider-brand-actor-meta {
      flex: 0 1 auto;
      width: 100%;
      min-width: 0;
      align-items: center;
      gap: 4px;
    }
    .qh-sider-brand-actor-name {
      width: 100%;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      text-align: center;
      color: ${webColor.nameLabel};
      font-size: clamp(12px, calc(var(--qh-pane-sider, ${webLayout.siderWidth}px) * 0.18), 16px);
      font-weight: 500;
      line-height: 1.35;
      padding-top: 1px;
    }
    .qh-sider-qq-status-list {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 3px;
      max-width: 100%;
      overflow: visible;
    }
    .qh-sider-qq-status {
      appearance: none;
      -webkit-appearance: none;
      display: inline-flex;
      align-items: center;
      align-self: center;
      gap: 5px;
      max-width: 100%;
      margin: 0;
      padding: 0;
      overflow: visible;
      border: none;
      background: transparent;
      cursor: pointer;
      color: #9aa0a6;
      font-size: 11px;
      font-weight: 400;
      line-height: 14px;
    }
    .qh-sider-qq-status:disabled {
      cursor: default;
    }
    .qh-sider-qq-status.is-on {
      color: #12b76a;
    }
    .qh-sider-qq-status.is-off {
      color: #f04438;
    }
    .qh-sider-qq-status.is-receiving {
      color: #d4a017;
    }
    .qh-sider-qq-status.is-paused {
      color: #1a1a1a;
    }
    .qh-sider-qq-status-dot {
      position: relative;
      flex-shrink: 0;
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #c5c9ce;
    }
    .qh-sider-qq-status.is-on .qh-sider-qq-status-dot {
      background: #15d173;
      box-shadow: 0 0 6px rgba(21, 209, 115, 0.85);
    }
    .qh-sider-qq-status.is-off .qh-sider-qq-status-dot {
      background: #f04438;
      box-shadow: 0 0 6px rgba(240, 68, 56, 0.75);
    }
    .qh-sider-qq-status.is-receiving .qh-sider-qq-status-dot {
      background: #ffcc33;
      box-shadow: 0 0 6px rgba(255, 204, 51, 0.9);
    }
    .qh-sider-qq-status.is-paused .qh-sider-qq-status-dot {
      background: #1a1a1a;
      box-shadow: none;
    }
    .qh-sider-qq-status.is-on .qh-sider-qq-status-dot::before,
    .qh-sider-qq-status.is-on .qh-sider-qq-status-dot::after,
    .qh-sider-qq-status.is-receiving .qh-sider-qq-status-dot::before,
    .qh-sider-qq-status.is-receiving .qh-sider-qq-status-dot::after {
      content: '';
      position: absolute;
      inset: -2px;
      border-radius: 50%;
      border: 1.5px solid rgba(21, 209, 115, 0.55);
      animation: qh-qq-online-ring 1.8s ease-out infinite;
    }
    .qh-sider-qq-status.is-receiving .qh-sider-qq-status-dot::before,
    .qh-sider-qq-status.is-receiving .qh-sider-qq-status-dot::after {
      border-color: rgba(255, 204, 51, 0.65);
    }
    .qh-sider-qq-status.is-on .qh-sider-qq-status-dot::after,
    .qh-sider-qq-status.is-receiving .qh-sider-qq-status-dot::after {
      animation-delay: 0.9s;
    }
    @keyframes qh-qq-online-ring {
      0% { transform: scale(1); opacity: 0.65; }
      100% { transform: scale(2.6); opacity: 0; }
    }
    .qh-sider-account {
      appearance: none;
      -webkit-appearance: none;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 0;
      box-sizing: border-box;
      width: auto;
      max-width: 100%;
      margin: 6px 6px 10px;
      margin-top: auto;
      padding: 10px 6px;
      border: none;
      border-radius: var(--qh-row-radius);
      background: transparent;
      text-align: center;
      cursor: pointer;
      color: inherit;
      line-height: 1.25;
    }
    .qh-sider-account .anticon {
      margin: 0;
      line-height: 1;
    }
    .qh-sider-account:hover,
    .qh-sider-account.is-open {
      background: ${webColor.sidebarSelected};
    }
    .qh-sider-avatar-wrap {
      position: relative;
      flex: 0 0 auto;
    }
    .qh-sider-status {
      position: absolute;
      right: -1px;
      bottom: -1px;
      width: 10px;
      height: 10px;
      border: 2px solid ${webColor.surface};
      border-radius: 50%;
      background: ${webColor.textRemind};
      box-sizing: border-box;
    }
    .qh-sider-status.is-on {
      background: ${webColor.success};
    }
    .qh-sider-account-copy {
      display: block;
      width: 100%;
      min-width: 0;
      max-width: 100%;
    }
    .qh-sider-account-name {
      display: block;
      width: 100%;
      max-width: 100%;
      margin: 0;
      color: ${webColor.nameLabel};
      font-size: ${webFontSize.nameLabel}px;
      font-weight: 400;
      line-height: 20px;
      text-align: center;
      white-space: nowrap;
      overflow: hidden;
    }
    .qh-sider-agent-id {
      display: flex;
      align-items: center;
      gap: 3px;
      min-width: 0;
      max-width: 100%;
    }
    .qh-sider-agent-id-text {
      flex: 0 1 auto;
      min-width: 0;
      color: ${webColor.subLabel};
      font-size: ${webFontSize.subLabel}px;
      line-height: 16px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: clip;
    }
    .qh-sider-agent-id-copy {
      appearance: none;
      -webkit-appearance: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      flex: 0 0 18px;
      width: 18px;
      height: 18px;
      margin-top: -1px;
      padding: 0;
      border: none;
      border-radius: 4px;
      background: transparent;
      color: ${webColor.subLabel};
      font-size: 11px;
      cursor: pointer;
    }
    .qh-sider-agent-id-copy:hover {
      color: ${webColor.nameLabel};
      background: ${webColor.sidebarSelected};
    }
    .qh-sider-agent-id-copy.is-copied {
      color: ${webColor.primary};
    }
    .qh-sider-account-chevron {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      flex: 0 0 auto;
      width: auto;
      height: auto;
      padding: 0;
      border-radius: 0;
      background: transparent;
      color: ${webColor.text};
      font-size: 12px;
      line-height: 1;
      box-shadow: none;
      transition: transform 0.18s ease;
    }
    .qh-sider-account-chevron .anticon {
      font-size: 12px;
      font-weight: 700;
    }
    .qh-sider-account-chevron.is-open {
      transform: rotate(180deg);
    }
    .qh-sider-settings.ant-popover {
      padding: 0 0 8px;
    }
    .qh-sider-settings .ant-popover-container {
      min-width: 0;
      min-height: 0;
      padding: 0 !important;
      overflow: hidden;
      border: 1px solid ${webColor.separator};
      border-radius: 16px;
      box-shadow: 0 12px 36px rgba(44, 47, 53, 0.14);
    }
    .qh-sider-settings .ant-popover-inner {
      padding: 0;
      overflow: hidden;
      border-radius: 16px;
      box-shadow: none;
    }
    .qh-sider-settings-card {
      width: 236px;
      max-height: calc(100vh - 24px);
      padding: 10px 0 6px;
      overflow-y: auto;
    }
    .qh-sider-settings-head {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 0 12px 10px;
    }
    .qh-sider-settings-duty {
      margin: 0 12px;
      padding: 8px 0;
      border-top: 1px solid ${webColor.separator};
    }
    .qh-sider-settings-duty .qh-duty-btn {
      height: 36px;
    }
    .qh-sider-settings-group {
      margin: 0 5px;
      padding: 2px 0;
      border-top: 1px solid ${webColor.separator};
    }
    .qh-sider-settings-item {
      box-sizing: border-box;
      appearance: none;
      -webkit-appearance: none;
      display: flex;
      align-items: center;
      gap: 10px;
      width: 100%;
      min-height: 36px;
      margin: 0;
      padding: 6px 12px;
      border: none;
      border-radius: 8px;
      background: transparent;
      color: ${webColor.nameLabel};
      font: inherit;
      text-align: left;
      cursor: pointer;
    }
    .qh-sider-settings-item:hover {
      background: ${webColor.convHover};
    }
    .qh-sider-settings-item.is-info {
      cursor: default;
    }
    .qh-sider-settings-item.is-info:hover {
      background: transparent;
    }
    .qh-sider-settings-item-icon {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      flex: 0 0 18px;
      width: 18px;
      color: ${webColor.nameLabel};
      font-size: 15px;
    }
    .qh-sider-settings-item-label {
      flex: 1 1 auto;
      min-width: 0;
      font-size: ${webFontSize.md}px;
      line-height: 20px;
    }
    .qh-sider-settings-item-value {
      flex: 0 0 auto;
      max-width: 120px;
      margin-left: 8px;
      overflow: hidden;
      color: ${webColor.subLabel};
      font-size: ${webFontSize.sm}px;
      line-height: 20px;
      text-align: right;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .qh-sider-settings-item-chevron {
      flex-shrink: 0;
      margin-left: 4px;
      color: ${webColor.textRemind};
      font-size: 10px;
    }
    .qh-chrome-theme {
      display: flex;
      align-items: center;
      gap: 10px;
      width: 100%;
      min-height: 36px;
      margin: 0;
      padding: 6px 12px;
      box-sizing: border-box;
    }
    .qh-chrome-theme-icon {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      flex: 0 0 18px;
      width: 18px;
      color: ${webColor.nameLabel};
      font-size: 15px;
    }
    .qh-chrome-theme-label {
      flex: 1 1 auto;
      min-width: 0;
      font-size: ${webFontSize.md}px;
      line-height: 20px;
      color: ${webColor.nameLabel};
    }
    .qh-chrome-theme-seg {
      display: flex;
      flex: 0 0 auto;
      padding: 2px;
      border-radius: 8px;
      background: ${webColor.search};
    }
    .qh-chrome-theme-seg button {
      appearance: none;
      -webkit-appearance: none;
      height: 24px;
      padding: 0 8px;
      border: none;
      border-radius: 6px;
      background: transparent;
      color: ${webColor.subLabel};
      font: inherit;
      font-size: ${webFontSize.sm}px;
      line-height: 22px;
      cursor: pointer;
    }
    .qh-chrome-theme-seg button.is-on {
      background: ${webColor.surface};
      color: ${webColor.nameLabel};
      font-weight: 600;
      box-shadow: 0 1px 2px rgba(44, 47, 53, 0.08);
    }
    .qh-duty-wrap,
    .qh-intake-wrap {
      width: 100%;
      min-width: 0;
      filter: drop-shadow(0 2px 4px rgba(40, 36, 32, 0.12));
      transition: filter 280ms cubic-bezier(0.16, 1, 0.3, 1);
    }
    .qh-duty-wrap:hover,
    .qh-intake-wrap:hover {
      filter: drop-shadow(0 6px 12px rgba(40, 36, 32, 0.18));
    }
    .qh-duty-wrap.is-cooling:hover,
    .qh-intake-wrap.is-cooling:hover {
      filter: drop-shadow(0 2px 4px rgba(40, 36, 32, 0.12));
    }
    .qh-duty-wrap .qh-click-spark,
    .qh-intake-wrap .qh-click-spark {
      width: 100%;
    }
    .qh-duty-wrap.is-cooling,
    .qh-intake-wrap.is-cooling {
      pointer-events: none;
    }
    .qh-duty-btn,
    .qh-intake-btn {
      appearance: none;
      -webkit-appearance: none;
      position: relative;
      isolation: isolate;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 5px;
      width: 100%;
      height: 32px;
      padding: 0 8px;
      overflow: hidden;
      border: 1px solid rgba(255, 255, 255, 0.58);
      border-radius: 999px;
      color: #2C2F35;
      font: inherit;
      font-size: ${webFontSize.timestamp}px;
      font-weight: 400;
      line-height: 1;
      letter-spacing: 0.02em;
      cursor: pointer;
      box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.78),
        inset 0 -1px 1px rgba(50, 44, 38, 0.1),
        inset 0 8px 14px rgba(255, 255, 255, 0.18);
      transition:
        color 280ms cubic-bezier(0.16, 1, 0.3, 1),
        border-color 280ms cubic-bezier(0.16, 1, 0.3, 1),
        background-color 280ms cubic-bezier(0.16, 1, 0.3, 1),
        box-shadow 280ms cubic-bezier(0.16, 1, 0.3, 1),
        transform 280ms cubic-bezier(0.16, 1, 0.3, 1);
    }
    .qh-duty-btn {
      background-color: #FFD4D0;
      background-image:
        radial-gradient(120% 90% at 18% 0%, rgba(255, 255, 255, 0.55) 0%, transparent 46%),
        linear-gradient(165deg, #FFE8E6 0%, #FFC8C4 100%);
    }
    .qh-intake-btn {
      background-color: #FFFFD0;
      background-image:
        radial-gradient(120% 90% at 18% 0%, rgba(255, 255, 255, 0.55) 0%, transparent 46%),
        linear-gradient(165deg, #FFFFD0 0%, #D2CDFF 100%);
    }
    .qh-duty-btn::before,
    .qh-intake-btn::before {
      content: '';
      position: absolute;
      width: 78%;
      height: 160%;
      top: -95%;
      left: 8%;
      border-radius: 50%;
      background: radial-gradient(circle, rgba(255, 255, 255, 0.62) 0%, transparent 70%);
      pointer-events: none;
      transition: transform 520ms cubic-bezier(0.16, 1, 0.3, 1);
    }
    .qh-duty-btn:disabled,
    .qh-intake-btn:disabled {
      opacity: 0.55;
      cursor: not-allowed;
      transform: none;
    }
    .qh-duty-btn:hover,
    .qh-intake-btn:hover {
      transform: translateY(-1px);
      border-color: rgba(255, 255, 255, 0.78);
      box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.88),
        inset 0 -1px 1px rgba(50, 44, 38, 0.1),
        inset 0 10px 18px rgba(255, 255, 255, 0.22);
    }
    .qh-duty-btn:hover {
      background-color: #FFD4D0;
    }
    .qh-intake-btn:hover {
      background-color: #FFFFD0;
    }
    .qh-duty-btn:hover::before,
    .qh-intake-btn:hover::before {
      transform: translate(12%, 55%) scale(1.18);
    }
    .qh-duty-btn:disabled:hover,
    .qh-intake-btn:disabled:hover {
      transform: none;
      border-color: rgba(255, 255, 255, 0.58);
      box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.78),
        inset 0 -1px 1px rgba(50, 44, 38, 0.1),
        inset 0 8px 14px rgba(255, 255, 255, 0.18);
    }
    .qh-duty-btn.is-on:disabled:hover {
      background-color: #CFFFBD;
    }
    .qh-duty-btn.is-off:disabled:hover {
      background-color: #FFD4D0;
    }
    .qh-intake-btn.is-on:disabled:hover {
      background-color: #FFFFD0;
    }
    .qh-duty-btn:active,
    .qh-intake-btn:active {
      transform: translateY(1px) scale(0.98);
      box-shadow:
        inset 0 2px 6px rgba(40, 34, 28, 0.16),
        inset 0 1px 0 rgba(255, 255, 255, 0.35);
    }
    .qh-duty-btn:focus-visible {
      outline: 2px solid #B9DFFF;
      outline-offset: 2px;
    }
    .qh-intake-btn:focus-visible {
      outline: 2px solid #D2CDFF;
      outline-offset: 2px;
    }
    .qh-duty-btn.is-off {
      border-color: rgba(255, 180, 176, 0.9);
      color: #2C2F35;
    }
    .qh-duty-btn.is-on {
      border-color: rgba(185, 223, 255, 0.85);
      background-color: #CFFFBD;
      background-image:
        radial-gradient(120% 90% at 18% 0%, rgba(255, 255, 255, 0.7) 0%, transparent 48%),
        linear-gradient(165deg, #CFFFBD 0%, #B9DFFF 100%);
      color: #2C2F35;
      animation: qh-duty-on-in 420ms cubic-bezier(0.16, 1, 0.3, 1);
    }
    .qh-intake-btn.is-on {
      border-color: rgba(210, 205, 255, 0.85);
      background-color: #FFFFD0;
      background-image:
        radial-gradient(120% 90% at 18% 0%, rgba(255, 255, 255, 0.7) 0%, transparent 48%),
        linear-gradient(165deg, #FFFFD0 0%, #D2CDFF 100%);
      color: #2C2F35;
      animation: qh-intake-on-in 420ms cubic-bezier(0.16, 1, 0.3, 1);
    }
    .qh-duty-btn.is-on:hover {
      background-color: #CFFFBD;
    }
    .qh-duty-btn.is-off:hover {
      background-color: #FFD4D0;
    }
    .qh-intake-btn.is-on:hover {
      background-color: #FFFFD0;
    }
    .qh-duty-btn.is-on:active {
      background-color: #B9DFFF;
    }
    .qh-duty-btn.is-off:active {
      background-color: #FFC8C4;
    }
    .qh-intake-btn.is-on:active {
      background-color: #D2CDFF;
    }
    .qh-duty-btn-glare,
    .qh-intake-btn-glare {
      position: absolute;
      inset: 0;
      border-radius: inherit;
      pointer-events: none;
      z-index: 1;
      background: linear-gradient(
        115deg,
        transparent 28%,
        rgba(255, 255, 255, 0.08) 40%,
        rgba(255, 255, 255, 0.62) 50%,
        rgba(255, 255, 255, 0.1) 60%,
        transparent 72%
      );
      background-size: 220% 100%;
      background-repeat: no-repeat;
      background-position: 130% 0;
      mix-blend-mode: screen;
      opacity: 0.85;
      transition: background-position 560ms cubic-bezier(0.16, 1, 0.3, 1);
    }
    .qh-duty-btn:hover .qh-duty-btn-glare,
    .qh-intake-btn:hover .qh-intake-btn-glare {
      background-position: -45% 0;
    }
    .qh-duty-btn-dot {
      position: relative;
      z-index: 2;
      flex-shrink: 0;
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #f04438;
      box-shadow: 0 0 6px rgba(240, 68, 56, 0.75);
    }
    .qh-duty-btn.is-on .qh-duty-btn-dot {
      background: #15d173;
      box-shadow: 0 0 6px rgba(21, 209, 115, 0.85);
    }
    .qh-duty-btn.is-on .qh-duty-btn-dot::before,
    .qh-duty-btn.is-on .qh-duty-btn-dot::after {
      content: '';
      position: absolute;
      inset: -2px;
      border-radius: 50%;
      border: 1.5px solid rgba(21, 209, 115, 0.55);
      animation: qh-qq-online-ring 1.8s ease-out infinite;
    }
    .qh-duty-btn.is-on .qh-duty-btn-dot::after {
      animation-delay: 0.9s;
    }
    .qh-duty-btn-icons,
    .qh-intake-btn-icons {
      position: relative;
      z-index: 2;
      flex: 0 0 16px;
      width: 16px;
      height: 16px;
    }
    .qh-intake-btn-icons {
      flex: 0 0 20px;
      width: 20px;
      height: 20px;
    }
    .qh-duty-btn-icons .anticon,
    .qh-intake-btn-icons .anticon {
      position: absolute;
      inset: 0;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 16px;
      transition:
        opacity 180ms cubic-bezier(0.16, 1, 0.3, 1),
        transform 220ms cubic-bezier(0.16, 1, 0.3, 1);
    }
    .qh-intake-btn-icons .anticon {
      font-size: 18px;
    }
    .qh-intake-btn-icons .is-play {
      font-size: 22px;
    }
    .qh-intake-play-outline svg {
      display: block;
    }
    .qh-intake-play-outline path {
      stroke-width: 1.2px;
      vector-effect: non-scaling-stroke;
    }
    .qh-duty-btn-icons .is-wifi,
    .qh-intake-btn-icons .is-play {
      opacity: 0;
      transform: scale(0.55) rotate(-24deg);
    }
    .qh-duty-btn.is-on .qh-duty-btn-icons .is-wifi,
    .qh-intake-btn.is-on .qh-intake-btn-icons .is-play {
      opacity: 1;
      transform: none;
    }
    .qh-duty-btn-icons .is-moon,
    .qh-intake-btn-icons .is-pause {
      opacity: 1;
      transform: none;
    }
    .qh-duty-btn.is-on .qh-duty-btn-icons .is-moon,
    .qh-intake-btn.is-on .qh-intake-btn-icons .is-pause {
      opacity: 0;
      transform: scale(0.55) rotate(24deg);
    }
    .qh-duty-btn-label,
    .qh-intake-btn-label {
      position: relative;
      z-index: 2;
      min-width: 0;
      white-space: nowrap;
    }
    @keyframes qh-duty-on-in {
      0% { background-color: #CFFFBD; }
      100% { background-color: #CFFFBD; }
    }
    @keyframes qh-intake-on-in {
      0% { background-color: #FFFFD0; }
      100% { background-color: #FFFFD0; }
    }
    @media (prefers-reduced-motion: reduce) {
      .qh-duty-wrap,
      .qh-intake-wrap,
      .qh-duty-btn,
      .qh-intake-btn,
      .qh-duty-btn::before,
      .qh-intake-btn::before,
      .qh-duty-btn-glare,
      .qh-intake-btn-glare,
      .qh-duty-btn-icons .anticon,
      .qh-intake-btn-icons .anticon,
      .qh-duty-btn.is-on .qh-duty-btn-dot::before,
      .qh-duty-btn.is-on .qh-duty-btn-dot::after,
      .qh-sider-qq-status.is-on .qh-sider-qq-status-dot::before,
      .qh-sider-qq-status.is-on .qh-sider-qq-status-dot::after,
      .qh-sider-qq-status.is-receiving .qh-sider-qq-status-dot::before,
      .qh-sider-qq-status.is-receiving .qh-sider-qq-status-dot::after {
        transition: none;
        animation: none;
      }
      .qh-duty-btn:hover,
      .qh-intake-btn:hover {
        transform: none;
      }
    }
    .qh-web-shell .ant-menu {
      background: transparent !important;
    }
    .qh-web-shell .ant-menu-item:hover,
    .qh-web-shell .ant-menu-item-active,
    .qh-web-shell .ant-menu-item:active,
    .qh-web-shell .ant-menu-item-selected {
      background: ${webColor.sidebarSelected} !important;
      color: ${webColor.nameLabel} !important;
    }
    .qh-web-shell .ant-menu-item-selected .anticon,
    .qh-web-shell .ant-menu-item-selected .qh-sider-chat-icon .anticon,
    .qh-web-shell .ant-menu-item-active .anticon,
    .qh-web-shell .ant-menu-item:active .anticon {
      color: ${webColor.nameLabel} !important;
    }
    .qh-sider-chat-icon {
      position: relative;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      line-height: 1;
    }
    .qh-sider-chat-icon .anticon {
      margin-inline-end: 0 !important;
    }
    .qh-sider-chat-dot {
      position: absolute;
      top: -3px;
      right: -3px;
      width: 7px;
      height: 7px;
      margin: 0;
      border-radius: 50%;
      pointer-events: none;
    }
    .qh-web-main :has(.qh-page-frame),
    .qh-web-main :has(.qh-chat-split),
    .qh-web-main :has(.qh-annotator-split),
    .qh-web-main :has(.qh-profile-page) {
      flex: 1 1 auto;
      min-height: 0;
      min-width: 0;
      width: 100%;
      height: 100%;
      display: flex;
      flex-direction: column;
      align-items: stretch;
    }
    .qh-page-frame {
      flex: 1 1 auto;
      min-height: 0;
      height: 100%;
      display: flex;
      flex-direction: column;
      background: ${webPageBg.page};
    }
    .qh-pane-resize {
      position: absolute;
      top: 0;
      right: 0;
      z-index: 12;
      width: 6px;
      height: 100%;
      cursor: col-resize;
      touch-action: none;
      user-select: none;
    }
    .qh-pane-resize::after {
      content: '';
      position: absolute;
      top: 10px;
      bottom: 10px;
      left: 2px;
      width: 2px;
      border-radius: 1px;
      background: transparent;
    }
    .qh-pane-resize:hover::after,
    body.qh-pane-resizing .qh-pane-resize:hover::after {
      background: ${webColor.primary};
      opacity: 0.45;
    }
    body.qh-pane-resizing,
    body.qh-pane-resizing * {
      cursor: col-resize !important;
      user-select: none !important;
    }
    .qh-chat-split {
      display: flex;
      flex-direction: row;
      flex: 1 1 auto;
      align-self: stretch;
      width: 100%;
      height: 100%;
      min-width: 0;
      min-height: 0;
      gap: var(--qh-pane-gap);
      padding: var(--qh-split-padding);
      box-sizing: border-box;
      overflow: hidden;
      border-radius: var(--qh-split-radius);
      background: var(--qh-sider-bg);
    }
    .qh-actor-list-pane {
      position: relative;
      display: flex;
      flex-direction: column;
      flex: 0 0 var(--qh-pane-actor, ${webLayout.pane2Pct}vw);
      width: var(--qh-pane-actor, ${webLayout.pane2Pct}vw);
      max-width: none;
      min-width: ${webLayout.paneActorMin}px;
      min-height: 0;
      overflow: hidden;
      border-radius: var(--qh-actor-pane-radius);
      background: var(--qh-actor-pane-bg);
    }
    .qh-chat-list-pane {
      position: relative;
      display: flex;
      flex-direction: column;
      flex: 0 0 var(--qh-pane-conv, ${webLayout.pane3Pct}vw);
      width: var(--qh-pane-conv, ${webLayout.pane3Pct}vw);
      max-width: none;
      min-width: 0;
      min-height: 0;
      overflow: hidden;
      border-radius: var(--qh-actor-pane-radius);
      background: var(--qh-conv-pane-bg);
    }
    .qh-chat-room-pane {
      display: flex;
      flex-direction: column;
      flex: 1 1 auto;
      align-self: stretch;
      width: auto;
      min-width: 0;
      min-height: 0;
      overflow: hidden;
      border-radius: var(--qh-chat-pane-radius);
      background: var(--qh-chat-pane-bg);
    }
    .qh-annotator-split {
      display: flex;
      flex-direction: row;
      flex: 1 1 auto;
      align-self: stretch;
      width: 100%;
      height: 100%;
      min-width: 0;
      min-height: 0;
      gap: var(--qh-pane-gap);
      padding: var(--qh-split-padding);
      box-sizing: border-box;
      overflow: hidden;
      border-radius: var(--qh-split-radius);
      background: var(--qh-sider-bg);
    }
    .qh-annotator-list-pane {
      position: relative;
      display: flex;
      flex-direction: column;
      flex: 0 0 var(--qh-pane-actor, ${webLayout.pane2Pct}vw);
      width: var(--qh-pane-actor, ${webLayout.pane2Pct}vw);
      max-width: none;
      min-width: 0;
      min-height: 0;
      overflow: hidden;
      border-radius: var(--qh-actor-pane-radius);
      background: var(--qh-actor-pane-bg);
    }
    .qh-annotator-detail-pane {
      position: relative;
      display: flex;
      flex-direction: column;
      flex: 1 1 auto;
      align-self: stretch;
      width: auto;
      min-width: 0;
      min-height: 0;
      overflow: hidden;
      border-radius: var(--qh-conv-pane-radius);
      background: var(--qh-conv-pane-bg);
    }
    .qh-annotator-split--with-chat .qh-annotator-detail-pane {
      flex: 0 0 var(--qh-pane-conv, ${webLayout.pane3Pct}vw);
      width: var(--qh-pane-conv, ${webLayout.pane3Pct}vw);
      max-width: none;
    }
    .qh-annotator-chat-pane {
      display: flex;
      flex-direction: column;
      flex: 1 1 auto;
      align-self: stretch;
      width: auto;
      min-width: 0;
      min-height: 0;
      overflow: hidden;
      border-radius: var(--qh-chat-pane-radius);
      background: var(--qh-chat-pane-bg);
    }
    @media (max-width: ${webLayout.compactTightMaxWidth}px) {
      .qh-chat-split,
      .qh-annotator-split {
        padding: var(--qh-split-padding);
        gap: var(--qh-pane-gap);
      }
      .qh-sider-brand {
        padding: 10px 6px 8px !important;
      }
      .qh-sider-account {
        padding: 10px 6px !important;
      }
    }
    .qh-annotator-filters {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      padding: 0 12px 10px;
      flex-shrink: 0;
    }
    .qh-annotator-chip {
      appearance: none;
      -webkit-appearance: none;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      height: 28px;
      padding: 0 10px;
      border: 1px solid ${webColor.separator};
      border-radius: 14px;
      background: ${webColor.surface};
      color: ${webColor.subLabel};
      font-family: inherit;
      font-size: 13px;
      line-height: 1;
      cursor: pointer;
    }
    .qh-annotator-chip:hover {
      background: ${webColor.convHover};
    }
    .qh-annotator-chip:focus-visible {
      outline: 2px solid ${webColor.primary};
      outline-offset: 2px;
    }
    .qh-annotator-chip.is-active {
      background: ${webColor.primarySoft};
      border-color: ${webColor.primary}73;
      color: ${webColor.primaryPressed};
    }
    .qh-annotator-chip-count {
      font-variant-numeric: tabular-nums;
      font-weight: 600;
      color: ${webColor.nameLabel};
    }
    .qh-annotator-chip.is-active .qh-annotator-chip-count {
      color: ${webColor.primary};
    }
    .qh-annotator-status {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 600;
      line-height: 16px;
      flex-shrink: 0;
    }
    .qh-annotator-status-dot {
      width: 6px;
      height: 6px;
      border-radius: 3px;
    }
    .qh-annotator-detail-header {
      display: flex;
      flex-direction: column;
      gap: 10px;
      padding: 10px 16px 12px;
      border-bottom: 1px solid ${webColor.separator};
      flex-shrink: 0;
      background: var(--qh-chat-pane-bg);
    }
    .qh-profile-page {
      display: flex;
      flex-direction: column;
      flex: 1 1 auto;
      align-self: stretch;
      width: 100%;
      height: 100%;
      min-width: 0;
      min-height: 0;
      background: ${webPageBg.profile};
    }
    .qh-profile-body {
      display: flex;
      justify-content: center;
      align-items: center;
      flex: 1 1 auto;
      min-height: 0;
      overflow-y: auto;
      overscroll-behavior: contain;
      padding: 32px 24px;
    }
    .qh-profile-column {
      width: 100%;
      max-width: 560px;
      margin-block: auto;
    }
    .ant-modal-body .qh-profile-column {
      max-width: none;
      margin-block: 0;
    }
    .ant-modal-body .qh-profile-identity {
      padding-top: 0;
    }
    .qh-profile-identity {
      display: flex;
      align-items: center;
      gap: 14px;
      padding: 8px 4px 20px;
    }
    .qh-profile-role {
      display: inline-flex;
      align-items: center;
      flex-shrink: 0;
      padding: 2px 8px;
      border-radius: 999px;
      background: ${webColor.primarySoft};
      color: ${webColor.primary};
      font-size: 12px;
      font-weight: 600;
      line-height: 16px;
    }
    .qh-profile-id {
      word-break: break-all;
    }
    .qh-profile-group {
      overflow: hidden;
      margin-bottom: 10px;
      border: 1px solid ${webColor.separator};
      border-radius: 10px;
      background: ${webColor.surface};
    }
    .qh-profile-row {
      display: flex;
      align-items: center;
      gap: 12px;
      width: 100%;
      min-height: 48px;
      margin: 0;
      padding: 10px 16px;
      border: none;
      background: transparent;
      color: inherit;
      font: inherit;
      text-align: left;
    }
    button.qh-profile-row {
      appearance: none;
      -webkit-appearance: none;
      cursor: pointer;
    }
    button.qh-profile-row:hover {
      background: ${webColor.convHover};
    }
    button.qh-profile-row:focus-visible {
      outline: 2px solid ${webColor.primary};
      outline-offset: -2px;
    }
    .qh-profile-row + .qh-profile-row {
      border-top: 1px solid ${webColor.separator};
    }
    .qh-profile-row-icon {
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
      width: 28px;
      height: 28px;
      border-radius: 7px;
      background: ${webColor.primarySoft};
      color: ${webColor.primary};
      font-size: 14px;
    }
    .qh-profile-row-label {
      flex: 1 1 auto;
      min-width: 0;
      font-size: ${webFontSize.md}px;
      line-height: 20px;
      color: ${webColor.nameLabel};
    }
    .qh-profile-row-value {
      flex-shrink: 0;
      max-width: 52%;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 13px;
      line-height: 18px;
      font-variant-numeric: tabular-nums;
      color: ${webColor.subLabel};
    }
    .qh-profile-row-chevron {
      flex-shrink: 0;
      color: ${webColor.textRemind};
      font-size: 12px;
    }
    .qh-profile-logout.ant-btn {
      height: 44px;
      margin-top: 16px;
      border: none;
      border-radius: 10px;
      font-size: ${webFontSize.md}px;
      font-weight: 600;
    }
    .qh-auth-split {
      position: fixed;
      inset: 0;
      z-index: 1;
      width: 100%;
      min-width: 0;
      background: ${webPageBg.login};
    }
    .qh-auth-pond-canvas {
      position: absolute;
      inset: 0;
      display: block;
      width: 100%;
      height: 100%;
    }
    .qh-auth-main {
      position: relative;
      z-index: 1;
      display: flex;
      align-items: center;
      justify-content: center;
      width: 100%;
      height: 100%;
      min-width: 0;
      min-height: 0;
      overflow: auto;
      padding: 40px 24px;
      background: transparent;
    }
    .qh-auth-column {
      width: 100%;
      max-width: 400px;
      padding: 36px 32px 28px;
      background: rgba(255, 255, 255, 0.86);
      border: 1px solid rgba(255, 255, 255, 0.72);
      border-radius: 20px;
      box-shadow: 0 18px 44px rgba(19, 78, 74, 0.1);
      backdrop-filter: blur(16px);
    }
    .qh-auth-head {
      display: flex;
      flex-direction: column;
      align-items: center;
      margin-bottom: 28px;
      text-align: center;
    }
    .qh-auth-logo-frame {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 64px;
      height: 64px;
      overflow: hidden;
      background: ${webColor.surface};
      border-radius: 16px;
      box-shadow: 0 8px 20px rgba(19, 78, 74, 0.1);
    }
    .qh-auth-logo {
      width: 100%;
      height: 100%;
      object-fit: cover;
      transform: scale(1.22);
    }
    .qh-auth-product.ant-typography {
      margin: 12px 0 0 !important;
      font-size: 20px !important;
      line-height: 26px !important;
      font-weight: 500 !important;
      letter-spacing: 0.4px;
    }
    .qh-auth-eyebrow {
      margin-top: 4px;
      color: #7A9693;
      font-size: 13px;
      font-weight: 400;
      line-height: 20px;
    }
    .qh-auth-form-title {
      margin: 0 0 18px;
      color: ${webColor.nameLabel};
      font-size: 15px;
      font-weight: 500;
      line-height: 22px;
      letter-spacing: 0.2px;
    }
    .qh-auth-column .ant-form-item {
      margin-bottom: 16px;
    }
    .qh-auth-column .ant-form-item-label > label {
      color: ${webColor.text};
      font-size: 13px;
      font-weight: 400;
    }
    .qh-auth-column .ant-input-affix-wrapper {
      height: 44px;
      min-height: 44px;
      max-height: 44px;
      box-sizing: border-box;
      padding-top: 0;
      padding-bottom: 0;
      display: inline-flex;
      align-items: center;
      border-radius: 10px;
      font-weight: 400;
      transition: border-color 180ms ease, box-shadow 180ms ease;
    }
    .qh-auth-column .ant-input-affix-wrapper .ant-input {
      height: auto !important;
      min-height: 0 !important;
      line-height: 22px;
      padding-block: 0;
    }
    .qh-auth-column .ant-input.ant-input-lg {
      height: 44px;
      min-height: 44px;
      box-sizing: border-box;
      border-radius: 10px;
      font-weight: 400;
      transition: border-color 180ms ease, box-shadow 180ms ease;
    }
    .qh-auth-column .ant-input-affix-wrapper .ant-input.ant-input-lg {
      height: auto !important;
      min-height: 0 !important;
      border-radius: 0;
    }
    .qh-auth-column .ant-input-affix-wrapper:hover,
    .qh-auth-column .ant-input:hover {
      border-color: ${webColor.primary};
    }
    .qh-auth-column .ant-input-affix-wrapper-focused,
    .qh-auth-column .ant-input-affix-wrapper:focus,
    .qh-auth-column .ant-input:focus,
    .qh-auth-column .ant-input-focused {
      border-color: ${webColor.primary};
      box-shadow: 0 0 0 3px rgba(90, 178, 172, 0.18);
    }
    .qh-auth-submit.ant-btn {
      height: 44px;
      margin-top: 8px;
      border: none;
      border-radius: 10px;
      font-weight: 500;
      transition: background-color 180ms ease, box-shadow 180ms ease, transform 160ms ease;
    }
    .qh-auth-submit.ant-btn:not(:disabled):hover {
      background: ${webColor.primaryPressed} !important;
      box-shadow: 0 6px 16px rgba(90, 178, 172, 0.28);
    }
    .qh-auth-submit.ant-btn:not(:disabled):active {
      background: ${webColor.primaryPressed} !important;
      transform: translateY(1px);
    }
    .qh-auth-submit.ant-btn:disabled,
    .qh-auth-submit.ant-btn[disabled] {
      color: ${webColor.textRemind} !important;
      background: ${webColor.separator} !important;
      box-shadow: none;
      opacity: 1;
    }
    .qh-auth-switch {
      display: flex;
      justify-content: center;
      align-items: baseline;
      gap: 2px;
      margin-top: 14px;
      color: #8A9E9C;
      font-size: 13px;
      font-weight: 400;
      line-height: 20px;
    }
    .qh-auth-link {
      margin: 0;
      padding: 0;
      border: none;
      background: none;
      color: ${webColor.primary};
      font-size: 13px;
      font-weight: 400;
      line-height: inherit;
      cursor: pointer;
      transition: color 160ms ease;
    }
    .qh-auth-link:hover,
    .qh-auth-link:focus {
      color: ${webColor.primaryPressed};
    }
    .qh-auth-link:focus-visible {
      outline: 2px solid ${webColor.primary};
      outline-offset: 2px;
      border-radius: 4px;
    }
    .qh-auth-agreement {
      display: block;
      margin-top: 14px;
      color: #7A9693;
      font-size: ${webFontSize.hint}px;
      font-weight: 400;
      line-height: 18px;
      text-align: center;
    }
    @media (max-width: 768px) {
      .qh-auth-main {
        align-items: flex-start;
        padding: 28px 16px 40px;
      }
      .qh-auth-column {
        padding: 28px 20px 22px;
        border-radius: 16px;
      }
      .qh-auth-logo-frame {
        width: 56px;
        height: 56px;
        border-radius: 14px;
      }
      .qh-auth-product.ant-typography {
        font-size: 18px !important;
        line-height: 24px !important;
      }
    }
    @media (prefers-reduced-motion: reduce) {
      .qh-auth-column .ant-input-affix-wrapper,
      .qh-auth-column .ant-input,
      .qh-auth-submit.ant-btn,
      .qh-auth-link {
        transition: none;
      }
      .qh-sticker-chip {
        transition: none;
      }
      .qh-sticker-chips {
        scroll-behavior: auto;
      }
      .qh-sticker-breath .ant-popover-inner {
        animation: none;
      }
      .qh-chat-bubble-hover-time {
        transition: none;
      }
    }
    .qh-chat-room {
      flex: 1 1 auto;
      align-self: stretch;
      width: 100%;
      min-width: 0;
      min-height: 0;
      height: 100%;
    }
    .qh-chat-body {
      flex: 1 1 auto;
      min-height: 0;
      min-width: 0;
      overflow: visible;
    }
    .qh-proactive-hint-host {
      position: absolute;
      top: 8px;
      left: 12px;
      right: 12px;
      z-index: 20;
      pointer-events: none;
    }
    .qh-proactive-hint-host.is-entering {
      animation: qh-proactive-hint-in 260ms cubic-bezier(0.22, 1, 0.36, 1) both;
    }
    .qh-proactive-hint-host.is-leaving {
      animation: qh-proactive-hint-out 200ms cubic-bezier(0.4, 0, 1, 1) both;
    }
    @keyframes qh-proactive-hint-in {
      from {
        opacity: 0;
        transform: translateY(-8px);
      }
      to {
        opacity: 1;
        transform: translateY(0);
      }
    }
    @keyframes qh-proactive-hint-out {
      from {
        opacity: 1;
        transform: translateY(0);
      }
      to {
        opacity: 0;
        transform: translateY(-6px);
      }
    }
    .qh-proactive-hint-card {
      pointer-events: auto;
      border-radius: 10px;
      border: 1px solid ${webColor.separator};
      box-shadow: 0 4px 16px rgba(15, 23, 42, 0.08);
      overflow: hidden;
    }
    .qh-proactive-hint-header {
      padding: 4px 10px;
      min-height: 32px;
      border-bottom: 1px solid ${webColor.separator};
    }
    .qh-proactive-hint-title {
      flex-shrink: 0;
      font-size: 12px;
      font-weight: 400;
      line-height: 18px;
      color: ${webColor.proactive};
    }
    .qh-proactive-hint-count {
      margin: 0 !important;
      padding-inline: 5px !important;
      font-size: 11px !important;
      font-weight: 700;
      line-height: 16px !important;
      color: ${webColor.warning};
      background: ${webColor.warningSoft} !important;
    }
    .qh-proactive-hint-body {
      max-height: 168px;
      overflow-y: auto;
      padding: 2px 10px 6px;
    }
    .qh-proactive-hint-item {
      padding: 6px 0;
      width: 100%;
    }
    .qh-proactive-hint-item.is-divided {
      border-bottom: 1px solid ${webColor.separator};
    }
    .qh-proactive-hint-item-main {
      display: flex;
      align-items: center;
      gap: 8px;
      width: 100%;
    }
    .qh-proactive-hint-item-text {
      flex: 1 1 auto;
      min-width: 0;
    }
    .qh-proactive-hint-content-row {
      display: flex;
      align-items: center;
      gap: 4px;
      min-width: 0;
      width: 100%;
    }
    .qh-proactive-hint-content-group {
      display: inline-flex;
      align-items: center;
      gap: 2px;
      flex: 1 1 auto;
      min-width: 0;
      max-width: 100%;
    }
    .qh-proactive-hint-sep {
      flex-shrink: 0;
      color: ${webColor.textRemind};
      font-size: 12px;
      line-height: 18px;
      user-select: none;
    }
    .qh-proactive-hint-fill {
      display: inline-flex;
      max-width: 100%;
      margin: 0;
      padding: 0;
      border: none;
      background: transparent;
      text-align: left;
      cursor: pointer;
      min-width: 0;
    }
    .qh-proactive-hint-fill.is-task {
      flex-shrink: 0;
      max-width: 38%;
    }
    .qh-proactive-hint-fill.is-content {
      flex: 0 1 auto;
      min-width: 0;
      max-width: 100%;
    }
    .qh-proactive-hint-fill:hover {
      opacity: 0.72;
    }
    .qh-proactive-hint-index {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 16px;
      height: 16px;
      border-radius: 999px;
      background: ${webColor.primarySoft};
      color: ${webColor.primary};
      font-size: 10px;
      font-weight: 700;
      flex-shrink: 0;
    }
    .qh-proactive-hint-task,
    .qh-proactive-hint-task.ant-typography {
      font-size: 13px;
      font-weight: 400;
      line-height: 18px;
      color: ${webColor.nameLabel} !important;
      white-space: nowrap;
    }
    .qh-proactive-hint-content,
    .qh-proactive-hint-content.ant-typography {
      font-size: 13px;
      line-height: 18px;
      color: ${webColor.textDetail} !important;
      white-space: nowrap;
    }
    .qh-proactive-hint-copy.ant-btn {
      flex-shrink: 0;
      width: 20px;
      height: 20px;
      padding: 0;
      color: ${webColor.subLabel};
    }
    .qh-proactive-hint-copy.is-copied.ant-btn {
      color: ${webColor.primary};
      background: ${webColor.primarySoft};
    }
    .qh-proactive-hint-send.ant-btn {
      flex-shrink: 0;
      height: 24px;
      padding-inline: 8px;
      font-size: 12px;
      line-height: 1;
    }
    .qh-proactive-hint-close.ant-btn {
      flex-shrink: 0;
      width: 24px;
      height: 24px;
      padding: 0;
      color: ${webColor.subLabel};
    }
    .qh-conv-toolbar {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-shrink: 0;
      width: 100%;
      padding: 8px 12px 10px;
      background: var(--qh-conv-pane-bg);
    }
    .qh-conv-toolbar .qh-conv-search {
      flex: 1 1 auto;
      min-width: 0;
      width: auto;
    }
    .qh-conv-search.ant-input-affix-wrapper {
      height: 36px;
      padding: 0 14px !important;
      border: none !important;
      border-radius: var(--qh-search-radius);
      background: var(--qh-search-bg) !important;
      box-shadow: none !important;
    }
    .qh-conv-search.ant-input-affix-wrapper:hover,
    .qh-conv-search.ant-input-affix-wrapper:focus,
    .qh-conv-search.ant-input-affix-wrapper-focused {
      border: none !important;
      box-shadow: none !important;
      background: var(--qh-search-bg) !important;
    }
    .qh-conv-search .ant-input {
      background: transparent !important;
      color: ${webColor.text};
    }
    .qh-conv-search .ant-input::placeholder {
      color: ${webColor.placeholder};
      font-size: ${webType.placeholder.fontSize}px;
      font-weight: ${webType.placeholder.fontWeight};
    }
    .qh-conv-search .ant-input-prefix {
      margin-inline-end: 6px;
      color: ${webColor.placeholder};
    }
    .qh-overlay-scroll {
      position: relative;
      flex: 1 1 0%;
      min-height: 0;
      height: 0;
      overflow: hidden;
    }
    .qh-overlay-scroll-viewport.qh-conv-scroller {
      height: 100%;
      max-height: 100%;
      flex: none;
    }
    .qh-overlay-scroll-thumb {
      position: absolute;
      top: 0;
      right: 2px;
      width: 4px;
      border-radius: 4px;
      background: ${webColor.textRemind};
      opacity: 0;
      pointer-events: none;
      z-index: 6;
      transition: opacity 160ms ease;
      will-change: transform, height;
    }
    .qh-overlay-scroll.is-scrollable:hover .qh-overlay-scroll-thumb,
    .qh-overlay-scroll.is-scrolling .qh-overlay-scroll-thumb {
      opacity: 0.55;
      pointer-events: auto;
    }
    .qh-overlay-scroll.is-scrollable:hover .qh-overlay-scroll-thumb:hover,
    .qh-overlay-scroll.is-scrolling .qh-overlay-scroll-thumb:hover {
      opacity: 0.8;
    }
    .qh-conv-scroller {
      /* flex-basis:0 才能在分栏里拿到确定高度，否则窗口化会按 0 高只画出 overscan 行 */
      flex: 1 1 0%;
      min-height: 0;
      height: 0;
      overflow-x: hidden;
      overflow-y: auto;
      overscroll-behavior: contain;
      /* 不预留滚动条槽位；浮层 thumb 由 .qh-overlay-scroll 绘制 */
      scrollbar-gutter: auto;
      scrollbar-width: none;
      -ms-overflow-style: none;
    }
    .qh-conv-scroller::-webkit-scrollbar {
      width: 0;
      height: 0;
      display: none;
    }
    .qh-conv-row.ant-btn {
      position: relative;
      display: flex;
      align-items: center;
      justify-content: flex-start;
      gap: 12px;
      width: 100%;
      height: ${webLayout.convRowHeight}px;
      box-sizing: border-box;
      margin: 0;
      padding: ${webLayout.convRowPadY}px ${webLayout.convRowPadRight}px ${webLayout.convRowPadY + webLayout.convRowPadBottom}px ${webLayout.convRowPadX}px;
      border: none !important;
      border-radius: 0;
      outline: none !important;
      background: transparent;
      box-shadow: none !important;
      text-align: left;
      white-space: normal;
      color: inherit;
      font: inherit;
    }
    .qh-conv-row.ant-btn > * {
      position: relative;
      z-index: 1;
    }
    .qh-conv-row.ant-btn::before {
      content: '';
      position: absolute;
      top: 0;
      right: ${webLayout.convRowSelectedInset}px;
      bottom: ${webLayout.convRowPadBottom}px;
      left: ${webLayout.convRowSelectedInset}px;
      z-index: 0;
      pointer-events: none;
      border-radius: var(--qh-row-radius);
      background: var(--qh-row-idle-bg);
    }
    .qh-conv-row.ant-btn:hover,
    .qh-conv-row.ant-btn:focus,
    .qh-conv-row.ant-btn:focus-visible,
    .qh-conv-row.ant-btn:active {
      border: none !important;
      outline: none !important;
      box-shadow: none !important;
      background: transparent !important;
      color: inherit !important;
    }
    .qh-conv-row.ant-btn:hover::before,
    .qh-conv-row.ant-btn:focus::before,
    .qh-conv-row.ant-btn:focus-visible::before,
    .qh-conv-row.ant-btn:active::before {
      background: var(--qh-row-hover-bg);
    }
    .qh-conv-row.ant-btn.is-active,
    .qh-conv-row.ant-btn.is-active:hover,
    .qh-conv-row.ant-btn.is-active:focus,
    .qh-conv-row.ant-btn.is-active:active {
      background: transparent !important;
    }
    .qh-conv-row.ant-btn.is-active::before,
    .qh-conv-row.ant-btn.is-active:hover::before,
    .qh-conv-row.ant-btn.is-active:focus::before,
    .qh-conv-row.ant-btn.is-active:active::before {
      background: var(--qh-row-selected-bg);
    }
    .qh-conv-row.ant-btn {
      --qh-row-name: var(--qh-row-idle-name);
      --qh-row-sub: var(--qh-row-idle-sub);
      --qh-row-time: var(--qh-row-idle-time);
    }
    .qh-conv-row.ant-btn.is-active {
      --qh-row-name: var(--qh-row-selected-name);
      --qh-row-sub: var(--qh-row-selected-sub);
      --qh-row-time: var(--qh-row-selected-time);
    }
    .qh-conv-row .qh-conv-name.ant-typography {
      color: var(--qh-row-name) !important;
    }
    .qh-conv-row .qh-conv-sub.ant-typography,
    .qh-conv-row .qh-conv-sub {
      color: var(--qh-row-sub) !important;
    }
    .qh-conv-row .qh-conv-time.ant-typography {
      color: var(--qh-row-time) !important;
    }
    .qh-conv-row.ant-btn.is-batch-selected::before,
    .qh-conv-row.ant-btn.is-batch-selected:hover::before,
    .qh-conv-row.ant-btn.is-batch-selected:focus::before,
    .qh-conv-row.ant-btn.is-batch-selected:active::before {
      background: rgba(90, 178, 172, 0.12);
    }
    .qh-conv-row.ant-btn::after,
    .qh-conv-row.ant-btn .ant-wave {
      display: none !important;
    }
    .qh-actor-list-pane .qh-conv-row.ant-btn::after,
    .qh-chat-list-pane .qh-conv-row.ant-btn::after {
      content: '';
      display: block !important;
      position: absolute;
      left: ${webLayout.convRowPadX + webLayout.convAvatarSize + 12}px;
      right: ${webLayout.convRowSelectedInset}px;
      bottom: 0;
      z-index: 1;
      height: 1px;
      pointer-events: none;
      background: var(--qh-row-divider);
    }
    .qh-actor-list-pane .qh-conv-row.ant-btn.is-active::after,
    .qh-chat-list-pane .qh-conv-row.ant-btn.is-active::after {
      display: none !important;
    }
    .qh-actor-list-pane.is-compact .qh-actor-row-meta,
    .qh-actor-list-pane.is-compact .qh-actor-row-status {
      display: none !important;
    }
    .qh-actor-list-pane.is-compact .qh-conv-row.ant-btn {
      justify-content: center;
      gap: 0;
    }
    .qh-actor-list-pane.is-compact .qh-conv-row.ant-btn::after {
      display: none !important;
    }
    .qh-conv-row.ant-btn.is-muted {
      opacity: 0.5;
    }
    .qh-conv-avatar {
      flex: 0 0 ${webLayout.convAvatarSize}px;
      width: ${webLayout.convAvatarSize}px;
      min-width: ${webLayout.convAvatarSize}px;
      height: ${webLayout.convAvatarSize}px;
    }
    .qh-conv-avatar .ant-avatar {
      flex-shrink: 0;
      border: none !important;
      outline: none !important;
      box-shadow: none !important;
      overflow: hidden;
    }
    .qh-conv-row .ant-avatar {
      border-radius: 50% !important;
      overflow: hidden;
    }
    .qh-chat-room .ant-avatar {
      border-radius: var(--qh-avatar-radius) !important;
      overflow: hidden;
    }
    .qh-conv-row .ant-avatar .ant-avatar-string,
    .qh-chat-room .ant-avatar .ant-avatar-string {
      border-radius: inherit;
    }
    .qh-conv-avatar .ant-avatar img,
    .qh-conv-row .ant-avatar img,
    .qh-chat-room .ant-avatar img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      border-radius: inherit;
    }
    .qh-conv-avatar .ant-avatar img {
      transform: scale(1.06);
    }
    .qh-chat-room .ant-listy-item,
    .qh-chat-list-pane .ant-listy-item {
      border: none !important;
      box-shadow: none !important;
      overflow: visible;
    }
    .qh-chat-room .ant-listy-item,
    .qh-chat-room .ant-listy-item:hover,
    .qh-chat-room .ant-listy-item:focus,
    .qh-chat-room .ant-listy-item:active {
      background: transparent !important;
      cursor: default;
    }
    .qh-chat-room .ant-listy-item:has(.qh-chat-time) {
      padding-top: 5px !important;
      padding-bottom: 5px !important;
    }
    .qh-chat-time,
    .qh-chat-time .ant-typography,
    .qh-chat-time-btn {
      font-weight: ${webType.timestamp.fontWeight} !important;
      color: var(--qh-chat-time) !important;
    }
    .qh-conv-time.ant-typography {
      font-weight: ${webType.timestamp.fontWeight} !important;
    }
    .qh-chat-time-btn {
      margin: 0;
      padding: 0;
      border: none;
      background: transparent;
      cursor: pointer;
      font-size: ${webType.timestamp.fontSize}px;
      line-height: ${webType.timestamp.lineHeight};
      font-family: inherit;
    }
    .qh-chat-bubble-cluster {
      position: relative;
      max-width: 100%;
    }
    .qh-chat-bubble-wrap {
      max-width: 100%;
      min-width: 0;
    }
    .qh-chat-bubble-hover-time {
      position: absolute;
      top: auto;
      bottom: 0;
      transform: none;
      opacity: 0;
      pointer-events: none;
      white-space: nowrap;
      font-size: 10px;
      line-height: 10px;
      font-weight: 400;
      color: var(--qh-chat-time);
      transition: opacity 120ms ease;
    }
    .qh-chat-bubble-cluster.is-mine .qh-chat-bubble-hover-time {
      right: calc(100% + 2px);
    }
    .qh-chat-bubble-cluster.is-peer .qh-chat-bubble-hover-time {
      left: calc(100% + 2px);
    }
    .qh-chat-bubble-cluster:hover .qh-chat-bubble-hover-time {
      opacity: 1;
    }
    .qh-chat-link.ant-typography {
      color: ${webColor.link};
      text-decoration: underline;
      word-break: break-all;
    }
    .qh-chat-link.ant-typography.is-mine {
      color: var(--qh-mine-bubble-fg) !important;
    }
    .qh-chat-link.ant-typography:hover {
      opacity: 0.82;
    }
    .qh-emoji-text {
      color: inherit;
    }
    .qh-emoji-text.is-bubble {
      white-space: pre-wrap;
      word-break: break-word;
    }
    .qh-emoji-text.is-preview {
      display: block;
      overflow: hidden;
      min-width: 0;
      white-space: nowrap;
      text-overflow: ellipsis;
      line-height: 16px;
    }
    .qh-emoji-text img {
      display: inline-block;
      width: ${webFontSize.emojiGlyph}px;
      height: ${webFontSize.emojiGlyph}px;
      margin: 0 1px;
      vertical-align: -4px;
      object-fit: contain;
      pointer-events: none;
    }
    .qh-emoji-text.is-pure img {
      width: ${webFontSize.emojiPure}px;
      height: ${webFontSize.emojiPure}px;
      vertical-align: -5px;
    }
    .qh-emoji-text.is-preview img {
      width: ${webFontSize.emojiPreview}px;
      height: ${webFontSize.emojiPreview}px;
      vertical-align: -2px;
    }
    .qh-chat-room .ant-listy,
    .qh-chat-room .ant-listy-holder {
      width: 100%;
      min-width: 0;
      scrollbar-gutter: auto;
      scrollbar-width: thin;
      scrollbar-color: transparent transparent;
    }
    .qh-chat-room .ant-listy *,
    .qh-chat-room .ant-listy-holder * {
      scrollbar-width: inherit;
      scrollbar-color: inherit;
    }
    .qh-chat-room-pane:hover .qh-chat-room .ant-listy,
    .qh-chat-room-pane:hover .qh-chat-room .ant-listy-holder {
      scrollbar-color: ${webColor.textRemind} transparent;
    }
    .qh-voice-player {
      display: flex;
      align-items: center;
      gap: 6px;
      box-sizing: border-box;
      max-width: 100%;
      height: 36px;
      padding: 0 8px;
      border-radius: 10px;
      background: ${webColor.voiceBg};
      user-select: none;
    }
    .qh-voice-play.ant-btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      box-sizing: border-box;
      flex: 0 0 18px;
      width: 18px !important;
      min-width: 18px !important;
      max-width: 18px !important;
      height: 18px !important;
      padding: 0 !important;
      border: 0;
      aspect-ratio: 1;
      overflow: hidden;
      color: ${webColor.onPrimary};
      background: ${webColor.voice};
      margin-right: 3px;
    }
    .qh-voice-play.ant-btn:hover,
    .qh-voice-play.ant-btn:active {
      color: ${webColor.onPrimary} !important;
      background: ${webColor.voicePressed} !important;
    }
    .qh-voice-play.ant-btn .anticon {
      font-size: ${webFontSize.voicePlayIcon}px;
    }
    .qh-voice-slider.ant-slider,
    .qh-voice-slider.ant-slider-horizontal {
      flex: 1 1 auto;
      min-width: 0;
      height: 12px !important;
      margin: 0 !important;
      padding-block: 0 !important;
    }
    .qh-voice-slider .ant-slider-rail,
    .qh-voice-slider .ant-slider-track,
    .qh-voice-slider .ant-slider-tracks {
      top: 50% !important;
      height: 2px !important;
      border-radius: 1px;
      transform: translateY(-50%) !important;
    }
    .qh-voice-slider .ant-slider-rail {
      background: ${webColor.voiceRail} !important;
    }
    .qh-voice-slider .ant-slider-track,
    .qh-voice-slider .ant-slider-tracks {
      background: ${webColor.voice} !important;
    }
    .qh-voice-slider .ant-slider-handle {
      width: 12px !important;
      height: 12px !important;
      inset-block-start: 0 !important;
    }
    .qh-voice-slider .ant-slider-handle::before {
      display: none;
    }
    .qh-voice-slider .ant-slider-handle::after {
      width: 12px !important;
      height: 12px !important;
      inset-inline-start: 0 !important;
      inset-block-start: 0 !important;
      border: 0;
      border-radius: 50%;
      background: ${webColor.surface};
      outline: none !important;
      box-shadow: ${webColor.voiceHandleShadow} !important;
    }
    .qh-voice-slider .ant-slider-handle:hover::after,
    .qh-voice-slider .ant-slider-handle:active::after,
    .qh-voice-slider .ant-slider-handle:focus::after {
      width: 12px !important;
      height: 12px !important;
      inset-inline-start: 0 !important;
      inset-block-start: 0 !important;
      outline: none !important;
      box-shadow: ${webColor.voiceHandleShadow} !important;
    }
    .qh-voice-time.ant-typography {
      flex: 0 0 auto;
      min-width: 22px;
      color: ${webColor.voice};
      font-size: ${webFontSize.voiceTime}px;
      line-height: 1;
      font-variant-numeric: tabular-nums;
      font-feature-settings: "tnum";
    }
    .qh-chat-video.ant-btn {
      position: relative;
      display: block;
      overflow: hidden;
      height: auto;
      padding: 0;
      border: 0;
      border-radius: 8px;
      background: ${webColor.videoBg};
    }
    .qh-chat-video.ant-btn:hover,
    .qh-chat-video.ant-btn:active {
      background: ${webColor.videoBg} !important;
      color: inherit !important;
    }
    .qh-chat-video.ant-btn:hover .qh-chat-video-play {
      background: ${webColor.videoOverlayStrong};
    }
    .qh-chat-video.ant-btn:focus-visible {
      outline: 2px solid ${webColor.primary};
      outline-offset: 2px;
    }
    .qh-chat-video .ant-image,
    .qh-chat-video .qh-chat-video-cover {
      display: block;
      width: 100%;
      height: 100%;
    }
    .qh-chat-video .ant-image-img {
      width: 100%;
      height: 100%;
      object-fit: cover;
    }
    .qh-chat-video-play {
      position: absolute;
      top: 50%;
      left: 50%;
      width: 44px;
      height: 44px;
      margin: -22px 0 0 -22px;
      border-radius: 50%;
      background: ${webColor.videoOverlay};
      color: ${webColor.onPrimary};
      font-size: ${webFontSize.videoPlayIcon}px;
      pointer-events: none;
    }
    .qh-chat-video-duration.ant-typography {
      position: absolute;
      right: 8px;
      bottom: 8px;
      padding: 2px 6px;
      border-radius: 4px;
      background: ${webColor.videoOverlayStrong};
      color: ${webColor.onPrimary};
      font-size: ${webFontSize.videoDuration}px;
      line-height: 14px;
      font-variant-numeric: tabular-nums;
      pointer-events: none;
    }
    .qh-chat-file.ant-btn {
      display: flex;
      align-items: center;
      justify-content: flex-start;
      gap: 10px;
      box-sizing: border-box;
      height: auto;
      min-width: 168px;
      max-width: 420px;
      padding: 10px 12px;
      border: 0;
      border-radius: 10px;
      box-shadow: none;
      text-align: left;
      white-space: normal;
      font: inherit;
    }
    .qh-chat-file.ant-btn.is-mine {
      background: var(--qh-mine-bubble);
      color: var(--qh-mine-bubble-fg);
    }
    .qh-chat-file.ant-btn.is-peer {
      background: var(--qh-peer-bubble);
      color: ${webColor.text};
    }
    .qh-chat-file.ant-btn.is-mine:hover,
    .qh-chat-file.ant-btn.is-mine:active {
      background: var(--qh-mine-bubble-hover) !important;
      color: var(--qh-mine-bubble-fg) !important;
    }
    .qh-chat-file.ant-btn.is-peer:hover,
    .qh-chat-file.ant-btn.is-peer:active {
      background: var(--qh-peer-bubble) !important;
      color: ${webColor.text} !important;
      filter: brightness(0.97);
    }
    .qh-chat-file.ant-btn:focus-visible {
      outline: 2px solid ${webColor.primary};
      outline-offset: 2px;
    }
    .qh-chat-file-icon {
      display: flex;
      align-items: center;
      justify-content: center;
      flex: 0 0 36px;
      width: 36px;
      height: 36px;
      border-radius: 6px;
      font-size: ${webFontSize.fileIcon}px;
    }
    .qh-chat-file.is-mine .qh-chat-file-icon {
      background: color-mix(in srgb, var(--qh-mine-bubble-fg) 18%, transparent);
      color: var(--qh-mine-bubble-fg);
    }
    .qh-chat-file.is-peer .qh-chat-file-icon {
      background: ${webColor.primarySoft};
      color: ${webColor.primary};
    }
    .qh-chat-file.is-peer .qh-chat-file-icon.is-pdf {
      background: ${webColor.filePdfBg};
      color: ${webColor.filePdf};
    }
    .qh-chat-file.is-peer .qh-chat-file-icon.is-word {
      background: ${webColor.fileWordBg};
      color: ${webColor.fileWord};
    }
    .qh-chat-file.is-peer .qh-chat-file-icon.is-excel {
      background: ${webColor.fileExcelBg};
      color: ${webColor.fileExcel};
    }
    .qh-chat-file.is-peer .qh-chat-file-icon.is-ppt {
      background: ${webColor.filePptBg};
      color: ${webColor.filePpt};
    }
    .qh-chat-file.is-peer .qh-chat-file-icon.is-zip {
      background: ${webColor.fileZipBg};
      color: ${webColor.fileZip};
    }
    .qh-chat-file.is-peer .qh-chat-file-icon.is-image {
      background: ${webColor.fileImageBg};
      color: ${webColor.fileImage};
    }
    .qh-chat-file-meta {
      display: flex;
      flex-direction: column;
      min-width: 0;
      flex: 1 1 auto;
    }
    .qh-chat-file-name.ant-typography {
      display: -webkit-box;
      overflow: hidden;
      -webkit-box-orient: vertical;
      -webkit-line-clamp: 2;
      color: inherit;
      font-size: ${webType.fileName.fontSize}px;
      font-weight: ${webType.fileName.fontWeight};
      line-height: ${webType.fileName.lineHeight};
      word-break: break-all;
    }
    .qh-chat-file-size.ant-typography {
      margin-top: 2px;
      color: inherit;
      font-size: ${webType.fileSize.fontSize}px;
      line-height: ${webType.fileSize.lineHeight};
      opacity: 0.72;
    }
    .qh-composer-actions .ant-space {
      column-gap: 4px !important;
    }
    .qh-composer-action.ant-btn {
      width: ${webLayout.composerActionBtn}px;
      height: ${webLayout.composerActionBtn}px;
      padding: 0;
      color: ${webColor.nameLabel};
    }
    .qh-composer-action.ant-btn .anticon {
      font-size: ${webFontSize.composerActionIcon}px;
    }
    .qh-web-composer {
      width: 100%;
    }
    .qh-web-composer > div {
      width: 100% !important;
      min-height: ${webLayout.composerInputMin}px !important;
      max-height: ${webLayout.composerInputMax}px !important;
      border: 1px solid ${webColor.separator};
      border-radius: 10px !important;
      background: ${webColor.surface} !important;
      overflow: hidden;
    }
    .qh-web-composer > div:focus-within {
      border-color: ${webColor.primary};
    }
    .qh-web-composer .qh-chat-composer {
      min-height: ${webLayout.composerInputMin}px !important;
      max-height: ${webLayout.composerInputMax}px !important;
      padding: 8px 11px !important;
      font-size: ${webFontSize.md}px !important;
      line-height: 22px !important;
      border-radius: 10px !important;
      background: ${webColor.surface} !important;
    }
    .qh-web-composer .qh-chat-composer-placeholder {
      left: 11px;
      top: 8px;
      font-size: ${webType.placeholder.fontSize}px !important;
      font-weight: ${webType.placeholder.fontWeight} !important;
      line-height: ${webType.placeholder.lineHeight} !important;
    }
    .qh-emoji-popover .ant-popover-inner {
      padding: 0;
      background: var(--qh-chat-pane-bg);
      box-shadow: ${webLayout.cardShadow};
    }
    .qh-emoji-panel {
      width: ${webLayout.emojiPanelWidth}px;
      height: ${webLayout.emojiPanelHeight}px;
      overflow: hidden;
      background: var(--qh-chat-pane-bg);
    }
    .qh-emoji-body {
      flex: 1 1 auto;
      min-height: 0;
      overflow-y: auto;
      padding: 8px 6px 4px;
    }
    .qh-click-spark {
      position: relative;
      display: block;
      flex: 0 0 auto;
      min-width: 0;
    }
    .qh-click-spark-canvas {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      display: block;
      pointer-events: none;
      z-index: 2;
    }
    .qh-sticker-chips {
      display: flex;
      flex-wrap: nowrap;
      align-items: center;
      gap: 6px;
      overflow-x: auto;
      overflow-y: hidden;
      box-sizing: border-box;
      padding: 4px 8px 8px;
      scroll-behavior: smooth;
    }
    .qh-sticker-chips::-webkit-scrollbar {
      height: 4px;
    }
    .qh-sticker-chips::-webkit-scrollbar-thumb {
      border-radius: 2px;
      background: ${webColor.separator};
    }
    .qh-sticker-chip {
      flex-shrink: 0;
      height: 26px;
      padding: 0 10px;
      border: none;
      border-radius: 8px;
      background: transparent;
      color: ${webColor.subLabel};
      font-size: ${webFontSize.sm}px;
      font-weight: 400;
      line-height: 26px;
      cursor: pointer;
      transition:
        color 180ms cubic-bezier(0.16, 1, 0.3, 1),
        background-color 180ms cubic-bezier(0.16, 1, 0.3, 1);
    }
    .qh-sticker-chip.is-active {
      color: ${webColor.primary};
      background: ${webColor.primarySoft};
    }
    .qh-sticker-chip-hint {
      flex-shrink: 0;
      color: ${webColor.subLabel};
      font-size: ${webFontSize.sm}px;
      line-height: 26px;
    }
    .qh-emoji-grid {
      display: grid;
      grid-template-columns: repeat(${webLayout.emojiGridCols}, 1fr);
    }
    .qh-emoji-cell {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 100%;
      aspect-ratio: 1;
      padding: 0;
      border: none;
      border-radius: 8px;
      background: transparent;
      font-size: ${webFontSize.emojiGlyph}px;
      line-height: 1;
      cursor: pointer;
    }
    .qh-emoji-cell:hover {
      background: ${webColor.convHover};
    }
    .qh-emoji-cell img {
      width: ${webFontSize.emojiGlyph}px;
      height: ${webFontSize.emojiGlyph}px;
      object-fit: contain;
      pointer-events: none;
    }
    .qh-emoji-stickers {
      padding: 4px 6px 8px;
    }
    .qh-sticker-add-cell,
    .qh-sticker-send-cell,
    .qh-sticker-manage-cell {
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 0;
      border-radius: 8px;
      cursor: pointer;
    }
    .qh-sticker-add-cell {
      width: ${webLayout.emojiSticker}px;
      height: ${webLayout.emojiSticker}px;
      border: 1px dashed ${webColor.subLabel};
      background: ${webColor.search};
      color: ${webColor.nameLabel};
    }
    .qh-sticker-add-cell:hover:not(:disabled) {
      background: ${webColor.convHover};
    }
    .qh-sticker-add-cell:disabled {
      opacity: 0.45;
      cursor: not-allowed;
    }
    .qh-sticker-send-cell {
      width: ${webLayout.emojiSticker}px;
      height: ${webLayout.emojiSticker}px;
      border: none;
      background: transparent;
      overflow: hidden;
    }
    .qh-sticker-send-cell:hover {
      background: ${webColor.convHover};
    }
    .qh-sticker-send-cell img {
      width: ${webLayout.emojiSticker}px;
      height: ${webLayout.emojiSticker}px;
      object-fit: contain;
      pointer-events: none;
    }
    .qh-sticker-breath {
      z-index: 1100;
    }
    .qh-sticker-breath .ant-popover-inner,
    .qh-sticker-breath .ant-popover-inner-content,
    .qh-sticker-breath .ant-popover-container {
      padding: 0 !important;
      background: transparent !important;
      box-shadow: none !important;
    }
    .qh-sticker-breath .ant-popover-inner {
      overflow: visible;
      border-radius: 0;
      animation: qh-sticker-breathe 2.6s cubic-bezier(0.45, 0, 0.55, 1) infinite;
      transform-origin: center bottom;
    }
    .qh-sticker-breath-preview {
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 0;
      line-height: 0;
    }
    .qh-sticker-breath-preview img {
      display: block;
      width: ${webLayout.emojiSticker * 2}px;
      height: ${webLayout.emojiSticker * 2}px;
      object-fit: contain;
      pointer-events: none;
      filter:
        drop-shadow(0 2px 3px rgba(44, 47, 53, 0.16))
        drop-shadow(0 10px 18px rgba(44, 47, 53, 0.28));
    }
    .qh-sticker-breath-card {
      width: 240px;
      max-height: 220px;
      overflow-y: auto;
      padding: 10px 12px 12px;
    }
    .qh-sticker-breath-title.ant-typography {
      display: block;
      margin: 0 0 8px;
      color: ${webColor.nameLabel};
      font-size: ${webFontSize.md}px;
      font-weight: 600;
      line-height: 20px;
    }
    .qh-sticker-breath-field + .qh-sticker-breath-field {
      margin-top: 8px;
    }
    .qh-sticker-breath-label {
      display: block;
      margin-bottom: 2px;
      color: ${webColor.primary};
      font-size: ${webFontSize.subLabel}px;
      font-weight: 600;
      line-height: 16px;
    }
    .qh-sticker-breath-value {
      display: block;
      color: ${webColor.text};
      font-size: ${webFontSize.sm}px;
      line-height: 18px;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .qh-sticker-breath-value.is-empty {
      color: ${webColor.textRemind};
    }
    .qh-sticker-breath-tags {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
    }
    .qh-sticker-breath-tag {
      max-width: 100%;
      padding: 1px 7px;
      border-radius: 8px;
      background: ${webColor.primarySoft};
      color: ${webColor.primary};
      font-size: ${webFontSize.subLabel}px;
      line-height: 18px;
    }
    @keyframes qh-sticker-breathe {
      0%,
      100% {
        transform: translateY(0) scale(1);
      }
      50% {
        transform: translateY(-2px) scale(1.02);
      }
    }
    .qh-sticker-manage-grid {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      max-height: min(52vh, 420px);
      overflow-y: auto;
      padding: 4px 2px 8px;
    }
    .qh-sticker-manage-grid .ant-upload {
      display: block;
      width: 72px;
      height: 72px;
    }
    .qh-sticker-manage-add {
      width: 72px;
      height: 72px;
    }
    .qh-sticker-manage-cell {
      position: relative;
      width: 72px;
      height: 72px;
      border: none;
      background: ${webColor.search};
      overflow: hidden;
    }
    .qh-sticker-manage-cell:hover {
      background: ${webColor.convHover};
    }
    .qh-sticker-manage-cell img {
      width: 60px;
      height: 60px;
      object-fit: contain;
      pointer-events: none;
    }
    .qh-sticker-check {
      position: absolute;
      top: 4px;
      right: 4px;
      display: flex;
      align-items: center;
      justify-content: center;
      width: 18px;
      height: 18px;
      border: 1.5px solid #fff;
      border-radius: 9px;
      background: rgba(0, 0, 0, 0.18);
      color: #fff;
      font-size: 10px;
    }
    .qh-sticker-manage-cell.is-selected .qh-sticker-check {
      background: ${webColor.primary};
    }
    .qh-sticker-modal .ant-modal-body {
      padding-top: 12px;
      min-height: 220px;
    }
    button.ant-modal-close {
      -webkit-appearance: none !important;
      appearance: none !important;
      width: 22px !important;
      height: 22px !important;
      min-width: 22px !important;
      min-height: 22px !important;
      inset-inline-end: 16px !important;
      top: 16px !important;
      padding: 0 !important;
      margin: 0 !important;
      border: 0 none !important;
      border-radius: 4px !important;
      background: transparent !important;
      box-shadow: none !important;
      outline: none !important;
      color: ${webColor.subLabel} !important;
    }
    button.ant-modal-close:hover {
      background: ${webColor.search} !important;
      color: ${webColor.text} !important;
    }
    button.ant-modal-close .ant-modal-close-x,
    button.ant-modal-close .anticon {
      display: flex !important;
      align-items: center;
      justify-content: center;
      font-size: 14px !important;
      line-height: 1 !important;
    }
    .qh-emoji-tabs {
      flex-shrink: 0;
      height: ${webLayout.emojiTabBar}px;
      padding: 0 8px;
      gap: 4px;
      border-top: 1px solid ${webColor.separator};
      background: var(--qh-chat-pane-bg);
    }
    .qh-emoji-tab.ant-btn {
      width: 36px;
      height: 32px;
      padding: 0;
      border: none !important;
      border-radius: 8px;
      color: ${webColor.subLabel};
    }
    .qh-emoji-tab.ant-btn.is-active {
      background: ${webColor.convHover} !important;
      color: ${webColor.nameLabel};
    }
    .qh-chat-quote {
      max-width: 100%;
      min-width: 0;
      cursor: default;
    }
    .qh-chat-quote.is-peer {
      padding: 2px 0 2px 8px;
      border-left: 2px solid ${webColor.subLabel};
    }
    .qh-chat-quote.is-mine {
      padding: 2px 8px 2px 0;
      border-right: 2px solid ${webColor.subLabel};
    }
    .qh-chat-quote-tooltip .ant-tooltip-container {
      color: ${webColor.text} !important;
    }
    .qh-chat-quote-tooltip-body {
      max-height: 220px;
      overflow-y: auto;
      overscroll-behavior: contain;
      padding-right: 6px;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .qh-chat-quote-tooltip-body::-webkit-scrollbar {
      width: 6px;
    }
    .qh-chat-quote-tooltip-body::-webkit-scrollbar-thumb {
      background: rgba(44, 47, 53, 0.22);
      border-radius: 4px;
    }
`;

/** 桌面 Web：铺满视口，去掉手机框背景。热更新只改 textContent，不要卸掉 style 节点。 */
export function ensureWebDesktopCss(): void {
  if (typeof document === 'undefined') return;
  document.querySelectorAll('style[id^="qh-web-desktop-css"]').forEach((el) => {
    if (el.id !== CSS_ID) el.remove();
  });
  let style = document.getElementById(CSS_ID) as HTMLStyleElement | null;
  if (!style) {
    style = document.createElement('style');
    style.id = CSS_ID;
    document.head.appendChild(style);
  }
  style.textContent = DESKTOP_CSS;
  applyChromeTheme();
  initPaneWidths();
}

export function removeWebDesktopCss(): void {
  if (typeof document === 'undefined') return;
  document.getElementById(CSS_ID)?.remove();
}

if (typeof document !== 'undefined') {
  ensureWebDesktopCss();
}

export function bindOverlayHost(node: HTMLElement | null): void {
  registerAppOverlayHost(node);
}
