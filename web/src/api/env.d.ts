/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * Адрес сервера Медиарадара, например `http://127.0.0.1:8000`, или `/` — тот же адрес,
   * откуда открыта страница (веб-версия). Задан при сборке — интерфейс по умолчанию работает
   * с сервером; не задан — с имитацией (src/api/source.ts).
   */
  readonly VITE_API_URL?: string;
  /** `web` — веб-версия для сервера (`npm run build:web`, src/lib/build.ts) */
  readonly VITE_TARGET?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
