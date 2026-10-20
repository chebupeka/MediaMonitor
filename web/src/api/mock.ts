/**
 * Имитация мокапа (демо-данные) для src/api/instance.ts. В сборке веб-версии
 * (`npm run build:web`) этот модуль подменяется заглушкой ./mock.web.ts (vite.config.ts):
 * веб-версия работает только с сервером, и демо-наборы не попадают в её бандл.
 */
export { DEMO_AI_TEXTS, DEMO_LINKS, DEMO_QUERIES, createFakeApi } from './fake';
