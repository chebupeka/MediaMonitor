/**
 * Запуск интерфейса мокапа на странице расширения: в боковой панели или во вкладке.
 *
 * Интерфейс тот же, что у сайта-мокапа (src/app/App). Стартовый экран, раскладку и
 * запрос App читает из параметров адреса (src/app/url-hints.ts) в момент загрузки
 * модуля, поэтому App импортируется только после того, как параметры выставлены.
 * Параметры меняются только в адресе страницы расширения и никуда не отправляются.
 *
 * До загрузки App подставляем возможности расширения (src/lib/host.ts): хранилище сеанса
 * общее для панели и вкладки, поэтому поиск переживает закрытие панели и переносится во
 * вкладку; кнопка «Открыть во вкладке» просит фон открыть или обновить вкладку.
 */
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { browser } from 'wxt/browser';
import '@/styles/fonts.css';
import '@/styles/tokens.css';
import '@/styles/base.css';
import { applyPrefs, readPrefs } from '@/app/prefs';
import { setHost } from '@/lib/host';
import { onPendingSelection, takePendingSelection } from './handoff';
import { OPEN_TAB_MESSAGE } from './messages';

function installExtensionHost(layout: 'panel' | 'site'): void {
  const session = browser.storage.session as typeof browser.storage.session | undefined;
  setHost({
    ...(session && {
      session: {
        get: async (key) => (await session.get(key))[key],
        set: (key, value) => session.set({ [key]: value }).catch(() => undefined),
      },
    }),
    openInTab:
      layout === 'panel'
        ? async () => {
            await browser.runtime.sendMessage({ type: OPEN_TAB_MESSAGE });
          }
        : null,
  });
}

/** `panel` — узкая боковая панель; `site` — вкладка во всю ширину */
export async function boot(layout: 'panel' | 'site'): Promise<void> {
  // Тема и версия для слабовидящих — сразу, до ожидания выделения: страница не мигает
  applyPrefs(readPrefs());
  installExtensionHost(layout);
  const pending = await takePendingSelection().catch(() => null);

  // «Проверить текст на ИИ» открывает экран проверки, остальное — «Поиск».
  const screen = pending?.action === 'ai-check' ? 'ai-check' : 'search';
  const hints = new URLSearchParams({ screen, layout });
  // С текстом экран сразу запускает поиск или проверку (src/app/App.tsx).
  if (pending) hints.set('q', pending.text);
  window.history.replaceState(null, '', `${window.location.pathname}?${hints.toString()}`);

  const { App } = await import('@/app/App');
  const root = document.getElementById('root');
  if (!root) throw new Error('Нет элемента #root');
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );

  // Новое выделение, пока панель открыта: перезапускаем интерфейс с новым запросом.
  onPendingSelection(() => window.location.reload());
}
