import AsyncStorage from '@react-native-async-storage/async-storage';

const KEY_PREFIX = 'agent_duty_v1:';

type DutyListener = (onDuty: boolean) => void;
const dutyListeners = new Set<DutyListener>();

/** 订阅上下班状态变更（Store 在会话全部置灰后拉 duty/status 会广播） */
export function subscribeDutyState(cb: DutyListener): () => void {
  dutyListeners.add(cb);
  return () => {
    dutyListeners.delete(cb);
  };
}

export function emitDutyState(onDuty: boolean): void {
  for (const l of dutyListeners) {
    try {
      l(onDuty);
    } catch {
      // ignore
    }
  }
}

function key(agentId: string): string {
  return `${KEY_PREFIX}${agentId}`;
}

export async function loadDutyState(agentId: string): Promise<boolean> {
  try {
    const v = await AsyncStorage.getItem(key(agentId));
    return v === '1';
  } catch {
    return false;
  }
}

export async function saveDutyState(agentId: string, onDuty: boolean): Promise<void> {
  try {
    await AsyncStorage.setItem(key(agentId), onDuty ? '1' : '0');
  } catch {
    // ignore persist errors
  }
}

