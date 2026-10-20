import react from '@vitejs/plugin-react';
import { loadEnv } from 'vite';
import { defineConfig, type TargetBrowser, type UserManifest } from 'wxt';

// Сборка браузерного расширения (Manifest V3) из того же кода интерфейса, что и мокап.
// Точки входа — в extension/entrypoints, значки — в extension/public.
// `npm run ext:build` → .output/chrome-mv3/ (папка для «Загрузить распакованное»),
// `npm run ext:build:firefox` → .output/firefox-mv3/, `npm run ext:build:safari` → .output/safari-mv3/,
// `npm run ext:zip` → .output/mediaradar-chrome.zip (этот архив раздаёт сервер на
// /download/mediaradar-chrome.zip, server/Dockerfile), `ext:zip:firefox` → mediaradar-firefox.zip.

/** Стенд Медиарадара: с ним работает расширение, если адрес сервера не задан при сборке. */
const STAND_API_URL = 'http://109.196.167.227:8000';

/**
 * Публичная часть ключа расширения (поле `key` манифеста, только Chromium). С ним у
 * расширения, установленного из папки, постоянный id `ecfimhlhegicelkhnikbgiecipmbihjh` —
 * на любом компьютере и после переустановки: `chrome-extension://<id>` можно вписать в
 * `CORS_ORIGINS`, а данные расширения не теряются при установке нового архива.
 * Закрытая часть ключа в репозитории не хранится: она нужна, только чтобы подписать .crx.
 */
const CHROME_PUBLIC_KEY =
  'MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA7UQOrO+ZbyUy/ulV0Hp11JvisBok2vniec8PPiogcQ6tgvuK5jQIxnaj1YcnAFL7oIDrw4fH7IVGl6+3ZjmvAJ+fbYjzrgMjAlp6HTjhk6BN+zEPSQ01Hu+aTq1tH9EVHdz8cVR9yLPcacEhA5FoJrrNjustci7I87tSZADWGpe+HYazS7k0ObYEMm/z9zlGz4CNwlzlEea8TxIZbadzwf41Gr2arimL6ve2nlUd4bYwoKs5I2MFzeIBAK4YOZKYa2MdPO3OZa1WFERQw+Zmfqjs+AAwwSUICya1bFV01a1PkatU5xankgzcQC75EX3x3ctHmWMZbxspkz6JAbKDFwIDAQAB';

/**
 * Адрес сервера Медиарадара для сборки, как его понимает src/api/source.ts: только http(s),
 * без запроса, фрагмента и логина. Откуда берётся: `VITE_API_URL` в окружении, затем в .env*,
 * иначе — стенд (STAND_API_URL). `VITE_API_URL=none` — сборка без сервера, на имитации мокапа.
 * `VITE_API_URL=http://127.0.0.1:8000 npm run ext:build` — расширение для локального сервера.
 */
function apiUrl(mode: string): URL | null {
  const raw = (
    process.env.VITE_API_URL ??
    loadEnv(mode, process.cwd(), 'VITE_').VITE_API_URL ??
    STAND_API_URL
  ).trim();
  if (!raw || raw === 'none') return null;
  try {
    const url = new URL(raw);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
    if (url.search || url.hash || url.username || url.password) return null;
    return url;
  } catch {
    return null;
  }
}

/** Адрес сервера для кода интерфейса (`import.meta.env.VITE_API_URL`), без `/` в конце. */
function apiUrlForApp(mode: string): string {
  const api = apiUrl(mode);
  return api ? `${api.origin}${api.pathname}`.replace(/\/+$/u, '') : 'none';
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
    "style-src 'self' 'unsafe-inline'",
    // Шрифты — в пакете расширения (src/styles/fonts.css), внешних запросов нет
    "font-src 'self'",
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
  // sidePanel.open() появился в Chrome 116 (research/extension-feasibility.md §3.3);
  // key — постоянный id при установке из папки (CHROME_PUBLIC_KEY).
  return { minimum_chrome_version: '116', key: CHROME_PUBLIC_KEY };
}

export default defineConfig({
  // WXT всегда направляет псевдоним `@` на srcDir — это та же папка src/, что и у мокапа.
  srcDir: 'src',
  // Путь от srcDir: точки входа расширения лежат рядом с src/, а не внутри.
  entrypointsDir: '../extension/entrypoints',
  publicDir: 'extension/public',
  outDir: '.output',
  // Имя архива без версии — mediaradar-chrome.zip, mediaradar-firefox.zip: под этими именами
  // их раздаёт сервер (/download/…). `ext:zip:firefox` кладёт рядом и архив исходников
  // для проверки на addons.mozilla.org.
  zip: {
    artifactTemplate: '{{name}}-{{browser}}.zip',
  },
  // Без автоимпортов: всё, что берём из WXT, импортируем явно — так понятнее и линтеру, и людям.
  imports: false,
  // Только Manifest V3, и в Firefox, и в Safari. По умолчанию WXT собирает их на MV2, а там
  // нет `browser.action` и пункта меню на значке — фон падает при запуске.
  manifestVersion: 3,
  manifest: ({ browser, mode, command }) => ({
    name: 'Медиарадар',
    // Подпись продукта — в начале; в Chrome Web Store описание не длиннее 132 знаков
    description:
      'Найдёт, где о вас написали во ВКонтакте, Одноклассниках и MAX по Красноярскому краю: выделите текст новости и увидите все посты.',
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
  vite: ({ mode }) => ({
    plugins: [react()],
    // Адрес сервера — в код интерфейса (src/api/source.ts), тот же, что в host_permissions
    // и CSP манифеста: по умолчанию стенд, даже если VITE_API_URL не задан.
    define: {
      'import.meta.env.VITE_API_URL': JSON.stringify(apiUrlForApp(mode)),
    },
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
