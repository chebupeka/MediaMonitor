import react from '@vitejs/plugin-react';
import { defineConfig } from 'wxt';

// Сборка браузерного расширения (Manifest V3) из того же кода интерфейса, что и мокап.
// Точки входа — в extension/entrypoints, значки — в extension/public.
// `npm run ext:build` → .output/chrome-mv3/ (папка для «Загрузить распакованное»),
// `npm run ext:zip` → .output/*.zip.
export default defineConfig({
  // WXT всегда направляет псевдоним `@` на srcDir — это та же папка src/, что и у мокапа.
  srcDir: 'src',
  // Путь от srcDir: точки входа расширения лежат рядом с src/, а не внутри.
  entrypointsDir: '../extension/entrypoints',
  publicDir: 'extension/public',
  outDir: '.output',
  // Без автоимпортов: всё, что берём из WXT, импортируем явно — так понятнее и линтеру, и людям.
  imports: false,
  manifest: {
    name: 'Медиамонитор',
    description:
      'Поиск публикаций во ВКонтакте, Одноклассниках и MAX по Красноярскому краю: выделите текст новости — и увидите, где она опубликована.',
    // sidePanel.open() появился в Chrome 116 (research/extension-feasibility.md §3.3)
    minimum_chrome_version: '116',
    // contextMenus — пункт «Найти, где это опубликовано»; storage — передать выделенный текст панели;
    // activeTab + scripting — прочитать выделение целиком на вкладке, где нажали пункт меню.
    // Доступа к сайтам заранее не просим: сервер ещё не развёрнут, адрес добавим вместе с ним.
    permissions: ['contextMenus', 'storage', 'activeTab', 'scripting'],
    action: {
      default_title: 'Открыть Медиамонитор',
    },
    icons: {
      16: '/icon/16.png',
      32: '/icon/32.png',
      48: '/icon/48.png',
      128: '/icon/128.png',
    },
  },
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
