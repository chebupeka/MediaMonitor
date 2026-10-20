/**
 * Фон расширения (Manifest V3: service worker в Chromium и Safari, фоновая страница в Firefox).
 *
 * - Пункты контекстного меню для выделенного текста: «Найти, где это опубликовано» и
 *   «Проверить текст на ИИ». Открывают боковую панель и передают ей текст и действие
 *   (lib/handoff.ts). Два пункта Chrome и Яндекс Браузер сами собирают в подменю
 *   «Медиамонитор».
 * - Клик по значку открывает боковую панель.
 * - Пункт «Открыть во вкладке» в меню значка и такая же кнопка в панели: широкий экран
 *   для большой подборки. Вкладка показывает тот же поиск, что и панель
 *   (src/screens/search/saved.ts).
 *
 * Боковая панель бывает двух видов: chrome.sidePanel (Chrome, Edge) и своя у Firefox —
 * sidebar_action, WXT собирает её из той же точки входа sidepanel. В Яндекс Браузере
 * (research/extension-feasibility.md §3.3) и Safari боковых панелей нет: там и если панель
 * не открылась, тот же интерфейс открывается во вкладке расширения.
 */
import { browser, type Browser } from 'wxt/browser';
import { defineBackground } from 'wxt/utils/define-background';
import { putPendingSelection, type SelectionAction } from '../lib/handoff';
import { isOpenTabMessage } from '../lib/messages';

const MENU_FIND = 'mm-find-published';
const MENU_AI_CHECK = 'mm-check-ai';
const MENU_OPEN_TAB = 'mm-open-tab';

/** Пункт меню по выделению → что сделать в панели. */
const SELECTION_ACTIONS: Record<string, SelectionAction> = {
  [MENU_FIND]: 'find',
  [MENU_AI_CHECK]: 'ai-check',
};

/** Страница расширения с интерфейсом во всю ширину вкладки */
const TAB_PAGE = '/app.html';

/** Боковая панель Firefox. В типах wxt/browser (они от Chrome) её нет. */
interface FirefoxSidebarAction {
  open(): Promise<void>;
  toggle(): Promise<void>;
}

export default defineBackground(() => {
  const sidePanel = browser.sidePanel as typeof browser.sidePanel | undefined;
  const sidebarAction = (browser as unknown as { sidebarAction?: FirefoxSidebarAction })
    .sidebarAction;

  // Меню создаём при установке и обновлении: браузер хранит его между перезапусками.
  browser.runtime.onInstalled.addListener(() => {
    void browser.contextMenus.removeAll().then(() => {
      browser.contextMenus.create({
        id: MENU_FIND,
        title: 'Найти, где это опубликовано',
        contexts: ['selection'],
      });
      browser.contextMenus.create({
        id: MENU_AI_CHECK,
        title: 'Проверить текст на ИИ',
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
  } else if (sidebarAction) {
    // Как в Chrome: значок открывает панель, повторный клик закрывает.
    browser.action.onClicked.addListener(() => {
      sidebarAction.toggle().catch(() => openTab());
    });
  } else {
    browser.action.onClicked.addListener(() => void openTab());
  }

  // Кнопка «Открыть во вкладке» в боковой панели (extension/lib/boot.tsx)
  browser.runtime.onMessage.addListener((message) => {
    if (isOpenTabMessage(message)) void openTab({ refresh: true });
  });

  browser.contextMenus.onClicked.addListener((info, tab) => {
    if (info.menuItemId === MENU_OPEN_TAB) {
      void openTab({ refresh: true });
      return;
    }
    const action = SELECTION_ACTIONS[String(info.menuItemId)];
    if (!action) return;

    // Панель открываем сразу: sidePanel.open() и sidebarAction.open() работают только
    // пока действует жест пользователя, поэтому до любых await.
    void openPanel(tab);
    void readSelection(tab, info.selectionText).then((text) => {
      if (!text) return;
      return putPendingSelection({
        text,
        action,
        pageUrl: tab?.url ?? info.pageUrl,
        pageTitle: tab?.title,
        at: Date.now(),
      });
    });
  });

  function openPanel(tab: Browser.tabs.Tab | undefined): Promise<void> {
    if (!sidePanel && sidebarAction) return sidebarAction.open().catch(() => openTab());
    if (!sidePanel || tab?.windowId === undefined) return openTab();
    return sidePanel.open({ windowId: tab.windowId }).catch(() => openTab());
  }
});

/**
 * Открыть интерфейс во вкладке. Если вкладка расширения уже открыта, переключаемся
 * на неё, а не плодим новые: в Яндекс Браузере и Safari (нет боковых панелей) так работает
 * каждое «Найти, где это опубликовано». Новый запрос вкладка подхватит сама (lib/handoff.ts).
 *
 * `refresh` — для «Открыть во вкладке»: уже открытую вкладку перезагружаем, и она
 * показывает текущий поиск из хранилища сеанса, а не тот, что был в ней раньше. Для
 * выделенного текста не перезагружаем: вкладка сама перезапустится, когда придёт текст.
 */
async function openTab({ refresh = false }: { refresh?: boolean } = {}): Promise<void> {
  const existing = await findTabPage();
  if (existing) {
    await browser.tabs.update(existing.tabId, { active: true });
    await browser.windows.update(existing.windowId, { focused: true });
    if (refresh) await browser.tabs.reload(existing.tabId);
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
