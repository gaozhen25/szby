import type { ReactNode } from 'react';
import { Avatar, Typography } from 'antd';
import {
  CheckOutlined,
  ClearOutlined,
  ClockCircleOutlined,
  CloudDownloadOutlined,
  CopyOutlined,
  DeleteOutlined,
  FileTextOutlined,
  InfoCircleOutlined,
  LockOutlined,
  LogoutOutlined,
  PhoneOutlined,
  RightOutlined,
  SkinOutlined,
  UserOutlined,
} from '@/ui/web/antd-icons';
import { ClickSpark } from '@/ui/web/bits/ClickSpark';
import { closeProfileModal, openProfileModal } from '@/lib/profile-modal-bus';
import { useProfile } from '@/features/profile/useProfile';
import {
  CHROME_THEME_OPTIONS,
  setChromeThemeId,
  useChromeThemeId,
} from '@/ui/web/chrome-theme';
import { webColor, webType } from '@/ui/web/theme';

function SettingsItem({
  icon,
  label,
  value,
  chevron,
  onClick,
}: {
  icon: ReactNode;
  label: string;
  value?: string;
  chevron?: boolean;
  onClick: () => void;
}) {
  return (
    <button type="button" className="qh-sider-settings-item" onClick={onClick}>
      <span className="qh-sider-settings-item-icon">{icon}</span>
      <span className="qh-sider-settings-item-label">{label}</span>
      {value ? (
        <span className="qh-sider-settings-item-value" title={value}>
          {value}
        </span>
      ) : null}
      {chevron ? <RightOutlined className="qh-sider-settings-item-chevron" /> : null}
    </button>
  );
}

export function DutyToggleButton({
  onDuty,
  onToggle,
  disabled = false,
}: {
  onDuty: boolean;
  onToggle: () => void;
  disabled?: boolean;
}) {
  const title = onDuty ? '上班中' : '已下班';
  return (
    <div className={`qh-duty-wrap${disabled ? ' is-cooling' : ''}`}>
      <ClickSpark
        sparkColor={onDuty ? '#B9DFFF' : '#FFD0CC'}
        sparkRadius={18}
        sparkSize={6}
        sparkCount={10}
        duration={420}
      >
        <button
          type="button"
          className={`qh-duty-btn${onDuty ? ' is-on' : ' is-off'}`}
          aria-pressed={onDuty}
          aria-label={onDuty ? '上班中，点击下班' : '已下班，点击上班'}
          disabled={disabled}
          onClick={onToggle}
        >
          <span className="qh-duty-btn-glare" aria-hidden />
          <span className="qh-duty-btn-dot" aria-hidden />
          <span className="qh-duty-btn-label">{title}</span>
        </button>
      </ClickSpark>
    </div>
  );
}

function ChromeThemePicker() {
  const id = useChromeThemeId();
  return (
    <div className="qh-chrome-theme">
      <span className="qh-chrome-theme-icon">
        <SkinOutlined />
      </span>
      <span className="qh-chrome-theme-label">界面样式</span>
      <div className="qh-chrome-theme-seg" role="group" aria-label="界面样式">
        {CHROME_THEME_OPTIONS.map((option) => (
          <button
            key={option.id}
            type="button"
            className={id === option.id ? 'is-on' : undefined}
            aria-pressed={id === option.id}
            onClick={() => setChromeThemeId(option.id)}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function SettingsInfoItem({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="qh-sider-settings-item is-info">
      <span className="qh-sider-settings-item-icon">{icon}</span>
      <span className="qh-sider-settings-item-label">{label}</span>
      <span className="qh-sider-settings-item-value" title={value}>
        {value}
      </span>
    </div>
  );
}

function middleEllipsis(value: string, maxLength = 18): string {
  if (value.length <= maxLength) return value;
  const visibleLength = maxLength - 2;
  const startLength = Math.ceil(visibleLength / 2);
  const endLength = Math.floor(visibleLength / 2);
  return `${value.slice(0, startLength)}...${value.slice(-endLength)}`;
}

export { middleEllipsis };

export function SiderAgentIdRow({
  agentId,
  idCopied,
  onCopy,
}: {
  agentId: string;
  idCopied: boolean;
  onCopy: () => void;
}) {
  const hasId = Boolean(agentId && agentId !== '—');
  return (
    <span
      className="qh-sider-agent-id"
      onClick={(e) => {
        e.stopPropagation();
      }}
      onKeyDown={(e) => {
        e.stopPropagation();
      }}
    >
      <span className="qh-sider-agent-id-text" title={agentId}>
        {middleEllipsis(agentId)}
      </span>
      {hasId ? (
        <button
          type="button"
          className={`qh-sider-agent-id-copy${idCopied ? ' is-copied' : ''}`}
          title={idCopied ? '已复制' : '复制 ID'}
          aria-label={idCopied ? '已复制' : '复制 ID'}
          onClick={(e) => {
            e.stopPropagation();
            e.preventDefault();
            onCopy();
          }}
        >
          {idCopied ? <CheckOutlined /> : <CopyOutlined />}
        </button>
      ) : null}
    </span>
  );
}

export function SiderSettingsCard({
  account,
  agentId,
  role,
  phone,
  dutyTime,
  initials,
  online,
  onDuty,
  isSupervisor,
  onToggleDuty,
  dutyCooling = false,
}: {
  account: string;
  agentId: string;
  role: string;
  phone: string;
  dutyTime: string;
  initials: string;
  online: boolean;
  onDuty: boolean;
  isSupervisor: boolean;
  onToggleDuty: () => void;
  dutyCooling?: boolean;
}) {
  const profile = useProfile();

  return (
    <div className="qh-sider-settings-card">
      <div className="qh-sider-settings-head">
        <span className="qh-sider-avatar-wrap">
          <Avatar size={36} style={{ background: webColor.primarySoft, color: webColor.primary, fontWeight: 600 }}>
            {initials}
          </Avatar>
          <span className={`qh-sider-status${online ? ' is-on' : ''}`} />
        </span>
        <span className="qh-sider-account-copy">
          <Typography.Text ellipsis style={{ ...webType.nameLabel, fontWeight: 600 }}>
            {account}
          </Typography.Text>
          <SiderAgentIdRow
            agentId={agentId}
            idCopied={profile.idCopied}
            onCopy={() => void profile.handleCopyAgentId()}
          />
        </span>
      </div>

      {isSupervisor ? null : (
        <div className="qh-sider-settings-duty">
          <DutyToggleButton onDuty={onDuty} onToggle={onToggleDuty} disabled={dutyCooling} />
        </div>
      )}

      <div className="qh-sider-settings-group">
        <SettingsInfoItem icon={<UserOutlined />} label="角色" value={role} />
        <SettingsInfoItem icon={<PhoneOutlined />} label="手机号" value={phone} />
        <SettingsInfoItem icon={<ClockCircleOutlined />} label="上班时段" value={dutyTime} />
        <ChromeThemePicker />
        <SettingsItem
          icon={<LockOutlined />}
          label="修改密码"
          chevron
          onClick={() => {
            closeProfileModal();
            if (profile.tryOpenResetPassword()) openProfileModal('reset-password');
          }}
        />
      </div>
      <div className="qh-sider-settings-group">
        <SettingsItem
          icon={<DeleteOutlined />}
          label="清除缓存"
          onClick={() => {
            closeProfileModal();
            profile.handleClearConversationCache();
          }}
        />
        <SettingsItem
          icon={<FileTextOutlined />}
          label="导出诊断日志"
          onClick={() => {
            closeProfileModal();
            profile.handleExportLocalLogs();
          }}
        />
        <SettingsItem
          icon={<ClearOutlined />}
          label="清除本地日志"
          onClick={() => {
            closeProfileModal();
            profile.handleClearLocalLogs();
          }}
        />
      </div>
      <div className="qh-sider-settings-group">
        <SettingsItem
          icon={<InfoCircleOutlined />}
          label="关于"
          onClick={() => {
            closeProfileModal();
            profile.handleAbout();
          }}
        />
        <SettingsItem
          icon={<CloudDownloadOutlined />}
          label="检查更新"
          value={`v${profile.appVersion}`}
          onClick={() => {
            closeProfileModal();
            profile.handleCheckUpdate();
          }}
        />
      </div>
      <div className="qh-sider-settings-group">
        <SettingsItem
          icon={<LogoutOutlined />}
          label="退出登录"
          chevron
          onClick={() => {
            closeProfileModal();
            profile.handleLogoutPress();
          }}
        />
      </div>
    </div>
  );
}
