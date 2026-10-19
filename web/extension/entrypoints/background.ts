/**
 * Фон расширения (service worker, Manifest V3).
 *
 * - Пункт контекстного меню «Найти, где это опубликовано» для выделенного текста:
 *   открывает боковую панель и передаёт ей текст (lib/handoff.ts).
 * - Клик по значку открывает боковую панель.
 * - Пункт «Открыть во вкладке» в меню значка: широкий экран для большой подборки.
 *
 * Поддержка боковых панелей (chrome.sidePanel) в Яндекс Браузере не подтверждена
 * (research/extension-feasibility.md §3.3). Если API нет или панель не открылась,
 * тот же интерфейс открывается во вкладке расширения.
 */
import { browser, type Browser } from 'wxt/browser';
import { defineBackground } from 'wxt/utils/define-background';
import { putPendingSelection } from '../lib/handoff';

const MENU_FIND = 'mm-find-published';
const MENU_OPEN_TAB = 'mm-open-tab';

/** Страница расширения с интерфейсом во всю ширину вкладки */
const TAB_PAGE = '/app.html';

export default defineBackground(() => {
  const sidePanel = browser.sidePanel as typeof browser.sidePanel | undefined;

  // Меню создаём при установке и обновлении: браузер хранит его между перезапусками.
  browser.runtime.onInstalled.addListener(() => {
    void browser.contextMenus.removeAll().then(() => {
      browser.contextMenus.create({
        id: MENU_FIND,
        title: 'Найти, где это опубликовано',
        contexts: ['selection'],
      });
      browser.contextMenus.create({
        id: MENU_OPEN_TAB,
        title: 'Открыть во вкладке',
        contexts: ['action'],
      });
    });
  });

  if (sidePanel) {
    void sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {
      browser.action.onClicked.addListener(() => void openTab());
    });
  } else {
    browser.action.onClicked.addListener(() => void openTab());
  }

  browser.contextMenus.onClicked.addListener((info, tab) => {
    if (info.menuItemId === MENU_OPEN_TAB) {
      void openTab();
      return;
    }
    if (info.menuItemId !== MENU_FIND) return;

    // Панель открываем сразу: sidePanel.open() работает только пока действует
    // жест пользователя, поэтому до любых await.
    void openPanel(tab);
    void readSelection(tab, info.selectionText).then((text) => {
      if (!text) return;
      return putPendingSelection({
        text,
        pageUrl: tab?.url ?? info.pageUrl,
        pageTitle: tab?.title,
        at: Date.now(),
      });
    });
  });

  function openPanel(tab: Browser.tabs.Tab | undefined): Promise<void> {
    if (!sidePanel || tab?.windowId === undefined) return openTab();
    return sidePanel.open({ windowId: tab.windowId }).catch(() => openTab());
  }
});

/**
 * Открыть интерфейс во вкладке. Если вкладка расширения уже открыта, переключаемся
 * на неё, а не плодим новые: в Яндекс Браузере (нет боковых панелей) так работает
 * каждое «Найти, где это опубликовано». Новый запрос вкладка подхватит сама (lib/handoff.ts).
 */
async function openTab(): Promise<void> {
  const existing = await findTabPage();
  if (existing) {
    await browser.tabs.update(existing.tabId, { active: true });
    await browser.windows.update(existing.windowId, { focused: true });
    return;
  }
  // Путь без схемы браузер достраивает до адреса внутри расширения.
  await browser.tabs.create({ url: TAB_PAGE });
}

/** Открытая вкладка с интерфейсом. runtime.getContexts — Chrome 116+, без лишних разрешений. */
async function findTabPage(): Promise<{ tabId: number; windowId: number } | null> {
  try {
    // documentUrls сравнивает адрес целиком, а у страницы в адресе параметры —
    // поэтому берём все вкладки расширения и отбираем по началу адреса.
    // origin фона — это chrome-extension://<id>, адрес страницы строим от него.
    const page = new URL(TAB_PAGE, self.location.origin).href;
    const contexts = await browser.runtime.getContexts({ contextTypes: ['TAB'] });
    const found = contexts.find(
      (c) => c.documentUrl?.startsWith(page) && c.tabId >= 0 && c.windowId >= 0,
    );
    return found ? { tabId: found.tabId, windowId: found.windowId } : null;
  } catch {
    return null;
  }
}

/**
 * Выделение целиком, с переносами строк. `selectionText` из меню приходит без
 * переносов, поэтому сначала читаем выделение на самой странице (activeTab даёт
 * на это право после клика по пункту меню). На служебных страницах и в PDF
 * чтение не сработает — тогда берём `selectionText`.
 */
async function readSelection(
  tab: Browser.tabs.Tab | undefined,
  fallback: string | undefined,
): Promise<string> {
  if (tab?.id !== undefined) {
    try {
      const [frame] = await browser.scripting.executeScript({
        target: { tabId: tab.id },
        func: () => window.getSelection()?.toString() ?? '',
      });
      const text = typeof frame?.result === 'string' ? frame.result.trim() : '';
      if (text) return text;
    } catch {
      // нет доступа к странице — ниже возьмём текст из меню
    }
  }
  return (fallback ?? '').trim();
}
