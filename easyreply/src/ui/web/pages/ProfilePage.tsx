/**
 * THESIS: 账号身份一眼可见，设置按组扫完；拒绝全宽堆叠 Card。
 * OWN-WORLD: 与聊天页同一套色值、字号、选中悬停、10px 圆角。
 * STORY: 先认人，再改密码 / 清缓存 / 关于，最后退出。
 * FIRST VIEWPORT: 弹窗内从账号身份开始，其下是分组设置行。
 * FORM: 侧栏底部账号条上浮菜单。
 */
import { useEffect, type ReactNode } from 'react';
import { Avatar, Button, Flex, Typography } from 'antd';
import {
  BugOutlined,
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
  UserOutlined,
} from '@/ui/web/antd-icons';
import { isProductionEnv } from '@/lib/api-host';
import { openProfileModal } from '@/lib/profile-modal-bus';
import { useProfile } from '@/features/profile/useProfile';
import { webColor, webType } from '@/ui/web/theme';

function ProfileRow({
  icon,
  label,
  value,
  onClick,
  showChevron = true,
}: {
  icon: ReactNode;
  label: string;
  value?: string;
  onClick?: () => void;
  showChevron?: boolean;
}) {
  const inner = (
    <>
      <span className="qh-profile-row-icon">{icon}</span>
      <span className="qh-profile-row-label">{label}</span>
      {value ? <span className="qh-profile-row-value">{value}</span> : null}
      {onClick && showChevron ? <RightOutlined className="qh-profile-row-chevron" /> : null}
    </>
  );
  if (onClick) {
    return (
      <button type="button" className="qh-profile-row" onClick={onClick}>
        {inner}
      </button>
    );
  }
  return <div className="qh-profile-row">{inner}</div>;
}

export function ProfilePanel({ active = true }: { active?: boolean }) {
  const p = useProfile();

  useEffect(() => {
    if (active) void p.loadUser();
  }, [active, p.loadUser]);

  return (
    <div className="qh-profile-column">
      <div className="qh-profile-identity">
        <Avatar size={48} icon={<UserOutlined />} style={{ background: webColor.primary, flexShrink: 0 }} />
        <Flex vertical flex={1} style={{ minWidth: 0 }} gap={6}>
          <Flex align="center" gap={8} style={{ minWidth: 0 }}>
            <Typography.Text ellipsis style={{ ...webType.paneTitle, flex: '0 1 auto', minWidth: 0 }}>
              {p.displayAccount}
            </Typography.Text>
            <span className="qh-profile-role">{p.displayRole}</span>
          </Flex>
          <Flex align="flex-start" gap={4}>
            <Typography.Text className="qh-profile-id" style={webType.subLabel}>
              ID: {p.agentId || '—'}
            </Typography.Text>
            {p.agentId ? (
              <Button
                type="text"
                size="small"
                icon={p.idCopied ? <CheckOutlined /> : <CopyOutlined />}
                onClick={() => void p.handleCopyAgentId()}
                title={p.idCopied ? '已复制' : '复制 ID'}
                aria-label={p.idCopied ? '已复制' : '复制 ID'}
                style={{
                  width: 24,
                  height: 24,
                  padding: 0,
                  color: p.idCopied ? webColor.primary : webColor.subLabel,
                }}
              />
            ) : null}
          </Flex>
        </Flex>
      </div>

      <div className="qh-profile-group">
        <ProfileRow icon={<UserOutlined />} label="角色" value={p.displayRole} />
        <ProfileRow icon={<PhoneOutlined />} label="手机号" value={p.displayPhone} />
        <ProfileRow icon={<ClockCircleOutlined />} label="上班时段" value={p.displayDutyTime} />
        <ProfileRow
          icon={<LockOutlined />}
          label="修改密码"
          onClick={() => {
            if (p.tryOpenResetPassword()) openProfileModal('reset-password');
          }}
        />
      </div>

      <div className="qh-profile-group">
        <ProfileRow
          icon={<DeleteOutlined />}
          label="清除缓存"
          onClick={p.handleClearConversationCache}
        />
        <ProfileRow
          icon={<FileTextOutlined />}
          label="导出诊断日志"
          onClick={p.handleExportLocalLogs}
        />
        <ProfileRow
          icon={<ClearOutlined />}
          label="清除本地日志"
          onClick={p.handleClearLocalLogs}
        />
      </div>

      <div className="qh-profile-group">
        <ProfileRow icon={<InfoCircleOutlined />} label="关于" onClick={p.handleAbout} />
        <ProfileRow
          icon={<CloudDownloadOutlined />}
          label="检查更新"
          value={`v${p.appVersion}`}
          showChevron={false}
          onClick={p.handleCheckUpdate}
        />
        {isProductionEnv ? null : (
          <ProfileRow icon={<BugOutlined />} label="Sentry 测试上报" onClick={p.handleSentryProbe} />
        )}
      </div>

      <Button
        type="primary"
        block
        className="qh-profile-logout"
        icon={<LogoutOutlined />}
        onClick={p.handleLogoutPress}
      >
        退出登录
      </Button>
    </div>
  );
}

export default ProfilePanel;
