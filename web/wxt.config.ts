import react from '@vitejs/plugin-react';
import { loadEnv } from 'vite';
import { defineConfig, type TargetBrowser, type UserManifest } from 'wxt';

// Сборка браузерного расширения (Manifest V3) из того же кода интерфейса, что и мокап.
// Точки входа — в extension/entrypoints, значки — в extension/public.
// `npm run ext:build` → .output/chrome-mv3/ (папка для «Загрузить распакованное»),
// `npm run ext:build:firefox` → .output/firefox-mv3/, `npm run ext:build:safari` → .output/safari-mv3/,
// `npm run ext:zip` → .output/*.zip.

/**
 * Адрес сервера Медиарадара из сборки (`VITE_API_URL` в окружении или в .env*), как его
 * понимает src/api/source.ts: только http(s), без запроса, фрагмента и логина.
 * `npm run ext:build` с `VITE_API_URL=http://127.0.0.1:8000` — расширение работает с сервером.
 */
function apiUrl(mode: string): URL | null {
  const raw = (
    process.env.VITE_API_URL ??
    loadEnv(mode, process.cwd(), 'VITE_').VITE_API_URL ??
    ''
  ).trim();
  if (!raw) return null;
  try {
    const url = new URL(raw);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
    if (url.search || url.hash || url.username || url.password) return null;
    return url;
  } catch {
    return null;
  }
}

/**
 * Доступ к серверу и политика безопасности страниц расширения (панель, вкладка).
 * - host_permissions — только адрес сервера из сборки: запросы к нему идут без CORS. Порт в
 *   шаблоне не пишем — Firefox порты в шаблонах не принимает, без порта подходит любой.
 * - CSP: свои скрипты без eval; сеть — только к себе и к серверу; шрифты Google Fonts
 *   (пока они не лежат в пакете); стили в атрибутах нужны React и точкам. В `ext:dev` —
 *   ещё дев-сервер WXT (перезагрузка по сокету).
 */
function serverAccess(mode: string, dev: boolean): UserManifest {
  const api = apiUrl(mode);
  const connect = [
    "'self'",
    ...(api ? [api.origin] : []),
    ...(dev ? ['http://localhost:*', 'ws://localhost:*'] : []),
  ].join(' ');
  const csp = [
    "default-src 'self'",
    "script-src 'self' 'wasm-unsafe-eval'",
    "object-src 'self'",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    "img-src 'self' data: blob:",
    `connect-src ${connect}`,
  ].join('; ');
  return {
    ...(api ? { host_permissions: [`${api.protocol}//${api.hostname}/*`] } : {}),
    content_security_policy: { extension_pages: csp },
  };
}

/** Ключи манифеста, которые понимает только свой браузер: чужие он показывает предупреждением. */
function browserSpecific(browser: TargetBrowser): UserManifest {
  if (browser === 'firefox') {
    return {
      browser_specific_settings: {
        gecko: {
          // Постоянный id: под ним расширение живёт на addons.mozilla.org, после публикации не меняется.
          id: 'mediamonitor@chebupeka.github.io',
          // 140 — текущий ESR. С него Firefox понимает data_collection_permissions,
          // а storage.session (115) и runtime.getContexts (127) есть и раньше.
          strict_min_version: '140.0',
          // Выделенный на странице текст уходит на сервер поиска (пока — в имитацию мокапа).
          data_collection_permissions: { required: ['websiteContent'] },
        },
      },
    };
  }
  if (browser === 'safari') {
    // storage.session, через который фон передаёт выделение интерфейсу, — с Safari 16.4.
    return { browser_specific_settings: { safari: { strict_min_version: '16.4' } } };
  }
  // Chrome, Edge, Opera, Яндекс Браузер:
  // sidePanel.open() появился в Chrome 116 (research/extension-feasibility.md §3.3)
  return { minimum_chrome_version: '116' };
}

export default defineConfig({
  // WXT всегда направляет псевдоним `@` на srcDir — это та же папка src/, что и у мокапа.
  srcDir: 'src',
  // Путь от srcDir: точки входа расширения лежат рядом с src/, а не внутри.
  entrypointsDir: '../extension/entrypoints',
  publicDir: 'extension/public',
  outDir: '.output',
  // Без автоимпортов: всё, что берём из WXT, импортируем явно — так понятнее и линтеру, и людям.
  imports: false,
  // Только Manifest V3, и в Firefox, и в Safari. По умолчанию WXT собирает их на MV2, а там
  // нет `browser.action` и пункта меню на значке — фон падает при запуске.
  manifestVersion: 3,
  manifest: ({ browser, mode, command }) => ({
    name: 'Медиарадар',
    description:
      'Поиск публикаций во ВКонтакте, Одноклассниках и MAX по Красноярскому краю: выделите текст новости — и увидите, где она опубликована.',
    ...browserSpecific(browser),
    ...serverAccess(mode, command === 'serve'),
    // contextMenus — пункт «Найти, где это опубликовано»; storage — передать выделенный текст панели;
    // activeTab + scripting — прочитать выделение целиком на вкладке, где нажали пункт меню.
    // Доступа к сайтам заранее не просим: только к серверу из сборки (serverAccess).
    permissions: ['contextMenus', 'storage', 'activeTab', 'scripting'],
    action: {
      default_title: 'Открыть Медиарадар',
    },
    icons: {
      16: '/icon/16.png',
      32: '/icon/32.png',
      48: '/icon/48.png',
      128: '/icon/128.png',
    },
  }),
  vite: () => ({
    plugins: [react()],
    // Как в vite.config.ts мокапа: экраны обращаются к классам CSS-модулей в camelCase.
    css: {
      modules: {
        localsConvention: 'camelCaseOnly',
      },
    },
    build: {
      target: 'es2022',
    },
  }),
});
