import { useCallback, useEffect, useRef, useState } from 'react';
import { appAlert } from '@/lib/app-alert';
import { dutyOff, dutyOn, dutyStatus } from '@/api/tasks';
import { getRole } from '@/core/auth';
import { waitForAuthBootstrap } from '@/core/auth-flow';
import { getAgentId } from '@/core/im';
import { emitDutyState, loadDutyState, saveDutyState, subscribeDutyState } from '@/core/duty';
import {
  cancelSyncClaimedListAfterDutyOff,
  refreshClaimedConversations,
  syncClaimedListAfterDutyOff,
} from '@/lib/claimed-conversations-store';

const DUTY_TOGGLE_COOLDOWN_MS = 5000;

export function useDutyControls() {
  const isSupervisor = getRole() === 'supervisor';
  const [onDuty, setOnDuty] = useState(false);
  const [dutyCooling, setDutyCooling] = useState(false);
  const coolTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (isSupervisor) return;
    return subscribeDutyState((on) => setOnDuty(on));
  }, [isSupervisor]);

  useEffect(() => {
    if (isSupervisor) return;
    let alive = true;
    void (async () => {
      if (!(await waitForAuthBootstrap())) return;
      const st = await dutyStatus().catch(() => null);
      if (!alive) return;
      if (st?.ok) {
        setOnDuty(st.on_duty);
        await saveDutyState(getAgentId(), st.on_duty).catch(() => {});
        return;
      }
      const persisted = await loadDutyState(getAgentId());
      if (alive) setOnDuty(persisted);
    })();
    return () => {
      alive = false;
    };
  }, [isSupervisor]);

  const startDutyCooldown = useCallback(() => {
    setDutyCooling(true);
    if (coolTimerRef.current) clearTimeout(coolTimerRef.current);
    coolTimerRef.current = setTimeout(() => {
      coolTimerRef.current = null;
      setDutyCooling(false);
    }, DUTY_TOGGLE_COOLDOWN_MS);
  }, []);

  useEffect(
    () => () => {
      if (coolTimerRef.current) clearTimeout(coolTimerRef.current);
    },
    [],
  );

  const applyDutyChange = useCallback(async (next: boolean) => {
    startDutyCooldown();
    setOnDuty(next);
    try {
      const res = next ? await dutyOn() : await dutyOff();
      setOnDuty(res.on_duty);
      emitDutyState(res.on_duty);
      await saveDutyState(getAgentId(), res.on_duty);
      if (res.on_duty) {
        cancelSyncClaimedListAfterDutyOff();
        void refreshClaimedConversations();
        return;
      }
      void syncClaimedListAfterDutyOff({
        reclaimedTaskCount: 'reclaimedTaskCount' in res ? res.reclaimedTaskCount : undefined,
      });
    } catch (e) {
      setOnDuty(!next);
      appAlert(next ? '上班登记失败' : '下班登记失败', e instanceof Error ? e.message : '请稍后重试');
    }
  }, [startDutyCooldown]);

  const handleToggleDuty = useCallback(() => {
    const next = !onDuty;
    if (!next) {
      if (dutyCooling) return;
      appAlert(
        '确认下班',
        '下班后，所有会话任务将被系统回收并重新分配，当前进行中的会话可能会分配给其他客服。确定下班吗？',
        [
          { text: '取消', style: 'cancel' },
          { text: '确认下班', style: 'destructive', onPress: () => void applyDutyChange(false) },
        ],
      );
      return;
    }
    void applyDutyChange(true);
  }, [dutyCooling, onDuty, applyDutyChange]);

  return { isSupervisor, onDuty, setOnDuty, handleToggleDuty, dutyCooling };
}
