/**
 * Единственное место, где выбирается реализация MonitorApi.
 * Сейчас — имитация. Для настоящего сервера меняется только этот файл.
 */
import type { MonitorApi } from './client';
import { DEMO_LINKS, DEMO_QUERIES, createFakeApi } from './fake';

export const api: MonitorApi = createFakeApi();

/** Это мокап на демо-данных: показываем пометку «Демо-данные». */
export const IS_MOCKUP = true;

/**
 * Примеры запросов и ссылок для демо (только мокап). Пригодятся экранам для
 * подсказок «попробуйте» и для демо-страницы СМИ. В продукте будут пустыми.
 */
export const demoQueries = DEMO_QUERIES;
export const demoLinks = DEMO_LINKS;
