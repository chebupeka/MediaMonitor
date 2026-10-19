/**
 * Точка входа в API для экранов:
 *   import { api, useSearchRun, useAsync } from '@/api';
 *   import type { ResultItem, Selection } from '@/api/types';
 *
 * Реализация выбирается в ./instance.ts (сейчас имитация). Экраны не знают,
 * имитация это или настоящий сервер, и не импортируют ничего из ./fake.
 */
export { api, IS_MOCKUP, demoLinks, demoQueries } from './instance';
export { MonitorApiError, errorMessage, isApiError, type MonitorApi } from './client';
export * from './hooks';
