import { Redirect, useLocalSearchParams } from 'expo-router';
import { useIsDesktopWeb } from '@/lib/web-desktop';
import NativeChatRoom from './[id].tsx';

function paramStr(value?: string | string[]): string | undefined {
  if (Array.isArray(value)) return value[0];
  return value || undefined;
}

/** 桌面 Web：聊天详情并入 Tab 两栏；窄屏使用手机端独立聊天页 */
export default function ChatIdWebRedirect() {
  const isDesktop = useIsDesktopWeb();
  const params = useLocalSearchParams<{
    id: string;
    annotatorId?: string;
    supervisor?: string;
  }>();

  if (!isDesktop) {
    return <NativeChatRoom />;
  }

  const id = paramStr(params.id);
  if (!id) return <Redirect href="/(tabs)/chat" />;

  const next: Record<string, string> = { id };
  const annotatorId = paramStr(params.annotatorId);
  const supervisor = paramStr(params.supervisor);
  if (annotatorId) next.annotatorId = annotatorId;
  if (supervisor) next.supervisor = supervisor;

  return (
    <Redirect
      href={{
        pathname: '/(tabs)/chat',
        params: next,
      }}
    />
  );
}
