/** Сообщения от страниц расширения фону. */

/** Боковая панель просит открыть интерфейс во вкладке: текущий поиск уже в хранилище сеанса. */
export const OPEN_TAB_MESSAGE = 'mm:open-tab';

export function isOpenTabMessage(message: unknown): boolean {
  return (
    typeof message === 'object' &&
    message !== null &&
    (message as { type?: unknown }).type === OPEN_TAB_MESSAGE
  );
}
