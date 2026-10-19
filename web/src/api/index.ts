/**
 * Точка входа в API для экранов:
 *   import { api, useSearchRun, useAsync } from '@/api';
 *   import type { ResultItem, Selection } from '@/api/types';
 *
 * Реализация выбирается в ./instance.ts: имитация или настоящий сервер (./http.ts).
 * Экраны не знают, что именно работает, и не импортируют ничего из ./fake.
 */
export { api, dataSource, IS_MOCKUP, demoAiTexts, demoLinks, demoQueries } from './instance';
export { MonitorApiError, errorMessage, isApiError, type MonitorApi } from './client';
export * from './hooks';
