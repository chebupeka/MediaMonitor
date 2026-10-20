/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * Адрес сервера Медиарадара, например `http://127.0.0.1:8000`. Задан при сборке —
   * интерфейс по умолчанию работает с сервером; не задан — с имитацией (src/api/source.ts).
   */
  readonly VITE_API_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
