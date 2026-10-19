import { fileURLToPath, URL } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';
import { viteSingleFile } from 'vite-plugin-singlefile';

// Обычная сборка: `vite build` → dist/ (index.html + assets/).
// Сборка в один файл: `vite build --mode single` → dist/index.html, всё внутри файла.
// Внешние запросы остаются только к Google Fonts (ссылка в index.html).
export default defineConfig(({ mode }) => {
  const single = mode === 'single';
  return {
    base: './',
    plugins: [react(), ...(single ? [viteSingleFile({ removeViteModuleLoader: true })] : [])],
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
      // Один файл неизбежно большой: предупреждение о размере чанка тут не полезно.
      chunkSizeWarningLimit: single ? 4096 : 1024,
      assetsInlineLimit: single ? 100_000_000 : 4096,
      cssCodeSplit: !single,
    },
    server: {
      port: 5173,
      strictPort: false,
    },
  };
});
