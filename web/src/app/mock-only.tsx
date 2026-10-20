/**
 * Только для мокапа и расширения: панель «Демо-сценарий», лендинг мокапа, демо-страница СМИ,
 * витрина компонентов. В сборке веб-версии (`npm run build:web`) модуль подменяется
 * заглушкой ./mock-only.web.tsx (vite.config.ts): этих экранов в веб-версии нет, а имитация
 * не попадает в её бандл.
 */
export { subscribeDemo } from '@/api/fake/scenario';
export { DemoPanel } from './DemoPanel';
export { default as GalleryScreen } from './Gallery';
export { default as DemoPageScreen, HostPage } from '@/screens/demo-page';
export { default as LandingScreen } from '@/screens/landing';
