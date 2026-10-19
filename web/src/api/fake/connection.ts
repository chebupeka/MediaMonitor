/** Имитация связи с сервером (НТ-23): сценарий «Нет связи» роняет её на несколько секунд. */
import type { ConnectionState } from '../types';

let state: ConnectionState = 'online';
const listeners = new Set<(state: ConnectionState) => void>();
let restoreTimer: ReturnType<typeof setTimeout> | null = null;

export function getConnection(): ConnectionState {
  return state;
}

export function setConnection(next: ConnectionState): void {
  if (next === state) return;
  state = next;
  listeners.forEach((listener) => listener(state));
}

/** Уронить связь на `ms` миллисекунд. */
export function dropConnectionFor(ms: number): void {
  if (restoreTimer) clearTimeout(restoreTimer);
  setConnection('offline');
  restoreTimer = setTimeout(() => {
    restoreTimer = null;
    setConnection('online');
  }, ms);
}

/** Вернуть связь сразу (при выходе из сценария «Нет связи»). */
export function restoreConnection(): void {
  if (restoreTimer) clearTimeout(restoreTimer);
  restoreTimer = null;
  setConnection('online');
}

export function onConnectionChange(listener: (state: ConnectionState) => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
