/**
 * Веб-версия на сервере: имитации мокапа в ней нет — данные только с сервера
 * (src/api/source.ts). Заглушка подменяет ./mock.ts в сборке `web` (vite.config.ts), поэтому
 * имитация и демо-наборы не попадают в бандл веб-версии.
 */
import type { MonitorApi } from './client';
import type * as Mock from './mock';

export const DEMO_QUERIES: typeof Mock.DEMO_QUERIES = [];

export const DEMO_AI_TEXTS: typeof Mock.DEMO_AI_TEXTS = [];

/** Демо-ссылки показываются только на имитации; здесь — пустые строки той же формы. */
export const DEMO_LINKS = {
  addByUrl: '',
  sourceOk: '',
  sourceClosed: '',
  sourcePostLink: '',
  sourceNotRegional: '',
  sourceNotSupported: '',
  sourceDuplicate: '',
} as unknown as typeof Mock.DEMO_LINKS;

export function createFakeApi(): MonitorApi {
  throw new Error('В веб-версии имитации нет: данные — только с сервера.');
}
