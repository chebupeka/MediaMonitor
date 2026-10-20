/**
 * Единственное место, где выбирается реализация MonitorApi: имитация мокапа или
 * HTTP-клиент настоящего сервера. Как выбирается — src/api/source.ts (панель
 * «Демо-сценарий» → «Данные», переменная сборки `VITE_API_URL`, иначе имитация).
 *
 * Файл XLSX (`getExportFile`): на сервере — скачивается с сервера, в имитации —
 * собирается в браузере (src/lib/xlsx.ts).
 */
import type { MonitorApi } from './client';
// Имитация мокапа; в веб-версии модуль подменён заглушкой без демо-данных (./mock.web.ts)
import { DEMO_AI_TEXTS, DEMO_LINKS, DEMO_QUERIES, createFakeApi } from '@/api/mock';
import { createHttpApi } from './http';
import { resolveDataSource, type DataSource } from './source';

/** Источник данных этой загрузки страницы. */
export const dataSource: DataSource = resolveDataSource();

export const api: MonitorApi =
  dataSource.kind === 'server' ? createHttpApi(dataSource.url) : createFakeApi();

/**
 * Работаем на имитации (демо-данные мокапа): показываем пометки мокапа, демо-файл
 * импорта и демо-ссылки. На сервере их нет — данные и файлы настоящие.
 */
export const IS_MOCKUP = dataSource.kind === 'fake';

/**
 * Примеры запросов и ссылок для демо (только мокап). Пригодятся экранам для
 * подсказок «попробуйте» и для демо-страницы СМИ. В продукте будут пустыми.
 */
export const demoQueries = DEMO_QUERIES;
export const demoLinks = DEMO_LINKS;
/** Примеры текстов для экрана «Проверка на ИИ» (только мокап). */
export const demoAiTexts = DEMO_AI_TEXTS;
