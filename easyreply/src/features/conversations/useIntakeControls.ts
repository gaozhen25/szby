import { useCallback, useEffect, useState } from 'react';
import { appAlert } from '@/lib/app-alert';
import { intakeSet, intakeStatus } from '@/api/tasks';
import { getRole } from '@/core/auth';
import { waitForAuthBootstrap } from '@/core/auth-flow';
import { refreshClaimedConversations } from '@/lib/claimed-conversations-store';

export function useIntakeControls() {
  const isSupervisor = getRole() === 'supervisor';
  const [intakePaused, setIntakePaused] = useState(false);
  const [intakeReason, setIntakeReason] = useState('');
  const [intakeLoading, setIntakeLoading] = useState(!isSupervisor);
  const [intakeToggling, setIntakeToggling] = useState(false);
  const [pauseModalVisible, setPauseModalVisible] = useState(false);
  const [pauseReasonDraft, setPauseReasonDraft] = useState('');

  const refreshIntakeStatus = useCallback(async () => {
    if (isSupervisor) return;
    const st = await intakeStatus().catch(() => null);
    if (st?.ok) {
      setIntakePaused(!!st.intake_paused);
      setIntakeReason(st.reason?.trim() ?? '');
    }
  }, [isSupervisor]);

  useEffect(() => {
    if (isSupervisor) return;
    let alive = true;
    void (async () => {
      try {
        if (!(await waitForAuthBootstrap())) return;
        await refreshIntakeStatus();
      } finally {
        if (alive) setIntakeLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [isSupervisor, refreshIntakeStatus]);

  const applyIntakeChange = useCallback(async (paused: boolean, reason?: string) => {
    setIntakeToggling(true);
    try {
      const res = await intakeSet({
        paused,
        reason: paused ? reason : undefined,
      });
      setIntakePaused(!!res.intake_paused);
      setIntakeReason(res.reason?.trim() ?? '');
      if (!res.intake_paused) {
        void refreshClaimedConversations();
      }
    } catch (e) {
      appAlert(
        paused ? '暂停接待失败' : '恢复接待失败',
        e instanceof Error ? e.message : '请稍后重试',
      );
      await refreshIntakeStatus();
    } finally {
      setIntakeToggling(false);
    }
  }, [refreshIntakeStatus]);

  const handleToggleIntake = useCallback(() => {
    if (intakeLoading || intakeToggling) return;
    void applyIntakeChange(!intakePaused);
  }, [intakeLoading, intakeToggling, intakePaused, applyIntakeChange]);

  const confirmPauseIntake = useCallback(() => {
    setPauseModalVisible(false);
    void applyIntakeChange(true, pauseReasonDraft.trim() || undefined);
  }, [applyIntakeChange, pauseReasonDraft]);

  const cancelPauseIntake = useCallback(() => {
    setPauseModalVisible(false);
    setPauseReasonDraft('');
  }, []);

  return {
    isSupervisor,
    intakePaused,
    intakeReason,
    intakeLoading,
    intakeToggling,
    pauseModalVisible,
    pauseReasonDraft,
    setPauseReasonDraft,
    handleToggleIntake,
    confirmPauseIntake,
    cancelPauseIntake,
    refreshIntakeStatus,
  };
}
