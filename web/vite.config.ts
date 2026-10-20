import { fileURLToPath, URL } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig, loadEnv, type Plugin } from 'vite';
import { viteSingleFile } from 'vite-plugin-singlefile';

// Обычная сборка: `vite build` → dist/ (index.html + assets/).
// Сборка в один файл: `vite build --mode single` → dist/index.html, всё внутри файла.
// Веб-версия для сервера: `vite build --mode web` → dist-web/, адрес /app/, данные — сервер
// на том же адресе (VITE_TARGET=web, VITE_API_URL=/ — по умолчанию, src/lib/build.ts).
// Внешних запросов нет: шрифты — в сборке (src/styles/fonts.css, пакеты @fontsource).
/** Веб-версия — не мокап: заголовок и описание страницы без «мокап» и «демо-данные». */
function webHtml(): Plugin {
  return {
    name: 'mediaradar-web-html',
    transformIndexHtml: (html) =>
      html
        .replace(/<title>[^<]*<\/title>/u, '<title>Медиарадар — найдёт, где о вас написали</title>')
        .replace(/\s*Мокап на демо-данных\./u, ''),
  };
}

export default defineConfig(({ mode }) => {
  const single = mode === 'single';
  const web = mode === 'web';
  // Веб-версия: цель и адрес API — без файла .env (его нет в git; образ сервера задаёт те же
  // VITE_TARGET=web и VITE_API_URL=/). Заданные снаружи значения важнее.
  if (web) {
    process.env.VITE_TARGET ??= 'web';
    process.env.VITE_API_URL ??= '/';
  }
  // Проверка веб-версии на своём компьютере: `npm run build:web && npx vite preview --mode web`
  // → http://localhost:4173/app/, запросы /api и /health уходят на сервер API_PROXY
  // (по умолчанию http://127.0.0.1:8000) — как на стенде, где их принимает Caddy.
  const apiProxy = loadEnv(mode, process.cwd(), '').API_PROXY || 'http://127.0.0.1:8000';
  return {
    base: web ? '/app/' : './',
    plugins: [
      react(),
      ...(single ? [viteSingleFile({ removeViteModuleLoader: true })] : []),
      ...(web ? [webHtml()] : []),
    ],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    css: {
      modules: {
        localsConvention: 'camelCaseOnly',
      },
    },
    build: {
      target: 'es2022',
      outDir: web ? 'dist-web' : 'dist',
      // Один файл неизбежно большой: предупреждение о размере чанка тут не полезно.
      chunkSizeWarningLimit: single ? 4096 : 1024,
      assetsInlineLimit: single ? 100_000_000 : 4096,
      cssCodeSplit: !single,
    },
    server: {
      port: 5173,
      strictPort: false,
    },
    preview: web
      ? {
          proxy: {
            '/api': { target: apiProxy, changeOrigin: true },
            '/health': { target: apiProxy, changeOrigin: true },
          },
        }
      : {},
  };
});
