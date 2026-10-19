/**
 * Запуск интерфейса мокапа на странице расширения: в боковой панели или во вкладке.
 *
 * Интерфейс тот же, что у сайта-мокапа (src/app/App). Стартовый экран, раскладку и
 * запрос App читает из параметров адреса (src/app/url-hints.ts) в момент загрузки
 * модуля, поэтому App импортируется только после того, как параметры выставлены.
 * Параметры меняются только в адресе страницы расширения и никуда не отправляются.
 */
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@/styles/tokens.css';
import '@/styles/base.css';
import { onPendingSelection, takePendingSelection } from './handoff';

/** `panel` — узкая боковая панель; `site` — вкладка во всю ширину */
export async function boot(layout: 'panel' | 'site'): Promise<void> {
  const pending = await takePendingSelection().catch(() => null);

  const hints = new URLSearchParams({ screen: 'search', layout });
  // С запросом экран «Поиск» сразу запускает поиск (src/app/App.tsx).
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
