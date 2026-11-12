import { Redirect, useLocalSearchParams } from 'expo-router';
import { useIsDesktopWeb } from '@/lib/web-desktop';
import NativeSessions from './sessions.tsx';

function paramStr(value?: string | string[]): string | undefined {
  if (Array.isArray(value)) return value[0];
  return value || undefined;
}

/** 桌面 Web：标注员会话并入主管 Tab 两栏；窄屏使用手机端独立页 */
export default function AnnotatorSessionsWebRedirect() {
  const isDesktop = useIsDesktopWeb();
  const params = useLocalSearchParams<{ agentId: string; name?: string }>();

  if (!isDesktop) {
    return <NativeSessions />;
  }

  const agentId = paramStr(params.agentId);
  if (!agentId) return <Redirect href="/(tabs)/annotators" />;

  const next: Record<string, string> = { agentId };
  const name = paramStr(params.name);
  if (name) next.name = name;

  return (
    <Redirect
      href={{
        pathname: '/(tabs)/annotators',
        params: next,
      }}
    />
  );
}
