import type { MockConversation } from '@/mock/data';
import { APP_ENV } from '@/lib/api-host';

const SEED_FLAG = 'qh.seedTestConversations';

/** 测试环境、且接口还没有已领取任务时，注入本地样例会话，方便点「接待者」。 */
export function shouldSeedTestConversations(): boolean {
  if (APP_ENV !== 'test') return false;
  if (typeof localStorage === 'undefined') return true;
  return localStorage.getItem(SEED_FLAG) !== '0';
}

export function buildSeedTestConversations(): MockConversation[] {
  return [
    {
      id: 'seed-liu-chen',
      from: '刘教练',
      to: '陈晨',
      platform: '微信',
      preview: '今天的训练打卡了吗？',
      time: '刚刚',
      unread: 2,
      avatarColor: '#7FB0D8',
      categoryId: 'lose-weight',
      imConversationID: 'si_wecom_actor_liu_aud_chen',
      hasRedDot: true,
      actorPlatformID: 'actor_liu',
      actorPlatformNickname: '刘教练',
      audiencePlatformID: 'aud_chen',
      audiencePlatformNickname: '陈晨',
    },
    {
      id: 'seed-liu-zhou',
      from: '刘教练',
      to: '周周',
      platform: '微信',
      preview: '饮食记录发我看一下',
      time: '昨天',
      unread: 0,
      avatarColor: '#B8A8E8',
      categoryId: 'lose-weight',
      imConversationID: 'si_wecom_actor_liu_aud_zhou',
      actorPlatformID: 'actor_liu',
      actorPlatformNickname: '刘教练',
      audiencePlatformID: 'aud_zhou',
      audiencePlatformNickname: '周周',
    },
    {
      id: 'seed-wang-lin',
      from: '王教练',
      to: '林林',
      platform: '微信',
      preview: '晚上 8 点直播见',
      time: '10:21',
      unread: 1,
      avatarColor: '#E8A598',
      categoryId: 'lose-weight',
      imConversationID: 'si_wecom_actor_wang_aud_lin',
      hasRedDot: true,
      actorPlatformID: 'actor_wang',
      actorPlatformNickname: '王教练',
      audiencePlatformID: 'aud_lin',
      audiencePlatformNickname: '林林',
    },
    {
      id: 'seed-wang-wu',
      from: '王教练',
      to: '吴楠',
      platform: '抖音',
      preview: '拉伸动作再发一条视频',
      time: '周三',
      unread: 0,
      avatarColor: '#E8A0B0',
      categoryId: 'coach-liu',
      imConversationID: 'si_wecom_actor_wang_aud_wu',
      actorPlatformID: 'actor_wang',
      actorPlatformNickname: '王教练',
      audiencePlatformID: 'aud_wu',
      audiencePlatformNickname: '吴楠',
    },
    {
      id: 'seed-kui-huang',
      from: '小葵',
      to: '荒',
      platform: '微信',
      preview: '你不想理我就算了',
      time: '刚刚',
      unread: 1,
      avatarColor: '#E8D4A0',
      categoryId: 'noi',
      imConversationID: 'si_wecom_actor_kui_aud_huang',
      hasRedDot: true,
      actorPlatformID: 'actor_kui',
      actorPlatformNickname: '小葵',
      audiencePlatformID: 'aud_huang',
      audiencePlatformNickname: '荒',
    },
  ];
}
