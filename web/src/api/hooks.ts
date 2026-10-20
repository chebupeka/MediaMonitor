/**
 * React-хуки поверх контракта. Пользоваться необязательно, но они избавляют
 * экраны от одинакового кода: загрузка данных, поток хода поиска, состояние связи.
 */
import { useCallback, useEffect, useReducer, useRef, useState, useSyncExternalStore } from 'react';
import { api } from './instance';
import { errorMessage, isApiError, plainApiError } from './client';
import type {
  ApiError,
  ConnectionState,
  PlatformId,
  PlatformStatus,
  ResultGroup,
  ResultItem,
  SearchConditions,
  SearchEvent,
  SearchRequest,
  SearchRun,
  Selection,
  SelectionCounts,
  SelectionNotice,
  TopicUnderstanding,
} from './types';

// ============================================================================
// useAsync — загрузка данных с состояниями «загрузка / успех / ошибка»
// ============================================================================

export interface AsyncState<T> {
  status: 'loading' | 'success' | 'error';
  data: T | null;
  error: ApiError | null;
  /** Загрузить заново (кнопка «Повторить»). */
  reload: () => void;
}

function toApiError(value: unknown): ApiError {
  return isApiError(value)
    ? plainApiError(value)
    : { code: 'server', message: errorMessage(value) };
}

/**
 * Загрузить данные при появлении экрана. `loader` должен быть стабильным —
 * оберните его в `useCallback`:
 * `const sources = useAsync(useCallback(() => api.listSources(), []));`
 */
export function useAsync<T>(loader: () => Promise<T>): AsyncState<T> {
  const [token, setToken] = useState(0);
  const [state, setState] = useState<Omit<AsyncState<T>, 'reload'>>({
    status: 'loading',
    data: null,
    error: null,
  });

  useEffect(() => {
    let alive = true;
    setState((prev) => ({ status: 'loading', data: prev.data, error: null }));
    loader().then(
      (data) => {
        if (alive) setState({ status: 'success', data, error: null });
      },
      (error: unknown) => {
        if (alive)
          setState((prev) => ({ status: 'error', data: prev.data, error: toApiError(error) }));
      },
    );
    return () => {
      alive = false;
    };
  }, [loader, token]);

  const reload = useCallback(() => setToken((t) => t + 1), []);
  return { ...state, reload };
}

// ============================================================================
// useConnection — есть ли связь с сервером (НТ-23)
// ============================================================================

export function useConnection(): ConnectionState {
  return useSyncExternalStore(
    (onChange) => api.onConnectionChange(onChange),
    () => api.getConnection(),
  );
}

// ============================================================================
// useSearchRun — поиск и его ход (НТ-2)
// ============================================================================

export type SearchPhase = 'idle' | 'queued' | 'running' | 'done' | 'stopped' | 'failed';

export interface SearchRunState {
  phase: SearchPhase;
  searchId: string | null;
  /** Условия выполненного поиска (НТ-1) */
  conditions: SearchConditions | null;
  statuses: PlatformStatus[];
  /** Какой источник площадки проверяется сейчас (для «VK: проверяем „Канск сегодня“») */
  currentSource: Partial<Record<PlatformId, string | null>>;
  /** Все пришедшие записи в порядке прихода (`arrival`) */
  items: ResultItem[];
  groups: ResultGroup[];
  counts: SelectionCounts | null;
  topic: TopicUnderstanding | null;
  notices: SelectionNotice[];
  /** Очередь (НТ-6): сколько поисков впереди */
  queue: { ahead: number; etaSec: number } | null;
  /** Связь пропала во время поиска; поиск продолжается на сервере (НТ-23) */
  connectionLost: string | null;
  /** Нейросеть недоступна (SC-08) */
  aiUnavailable: string | null;
  error: ApiError | null;
  /** Итоговая подборка после `finished` / `stopped` */
  selection: Selection | null;
}

const INITIAL: SearchRunState = {
  phase: 'idle',
  searchId: null,
  conditions: null,
  statuses: [],
  currentSource: {},
  items: [],
  groups: [],
  counts: null,
  topic: null,
  notices: [],
  queue: null,
  connectionLost: null,
  aiUnavailable: null,
  error: null,
  selection: null,
};

type Action =
  | { type: 'start'; searchId: string }
  | { type: 'retry'; platform: PlatformId }
  /** `runId` — id поиска у потока: на сервере он известен до события `started` (очередь). */
  | { type: 'event'; event: SearchEvent; runId: string }
  | { type: 'excluded'; ids: string[]; excluded: boolean; counts: SelectionCounts }
  | { type: 'added'; item: ResultItem }
  | { type: 'restore'; selection: Selection }
  | { type: 'reset' };

/**
 * Слить пришедшие записи с уже показанными. Запись с известным id — это обновление той же
 * карточки (например, пришла оценка проверки на ИИ): заменяется на своём месте, сохраняет
 * свой `arrival` и не считается новой — список не сдвигается, дублей нет. Новые id — в конец.
 */
export function mergeItems(current: ResultItem[], incoming: ResultItem[]): ResultItem[] {
  const index = new Map(current.map((item, i) => [item.id, i]));
  const next = [...current];
  for (const item of incoming) {
    const at = index.get(item.id);
    const known = at === undefined ? undefined : next[at];
    if (at === undefined || known === undefined) {
      index.set(item.id, next.length);
      next.push(item);
    } else {
      next[at] = { ...item, arrival: known.arrival };
    }
  }
  return next;
}

function regroup(groups: ResultGroup[], items: ResultItem[]): ResultGroup[] {
  const byId = new Map(items.map((i) => [i.id, i]));
  return groups.map((group) => {
    const countsByPlatform: Record<PlatformId, number> = { vk: 0, ok: 0, max: 0, site: 0, dzen: 0 };
    const countsByType = { verbatim: 0, shortened: 0, retold: 0, repost: 0 };
    for (const id of group.itemIds) {
      const item = byId.get(id);
      if (!item || item.excluded) continue;
      countsByPlatform[item.publication.platform] += 1;
      if (item.placementType) countsByType[item.placementType] += 1;
    }
    return { ...group, countsByPlatform, countsByType };
  });
}

function fromSelection(
  state: SearchRunState,
  selection: Selection,
  phase: SearchPhase,
): SearchRunState {
  return {
    ...state,
    phase,
    conditions: selection.conditions,
    statuses: selection.statuses,
    items: selection.items,
    groups: selection.groups,
    counts: selection.counts,
    topic: selection.topic ?? state.topic,
    notices: selection.notices,
    // Подборка открыта заново (обновили страницу): события «нейросеть недоступна» не было —
    // берём ту же пометку из подборки.
    aiUnavailable:
      state.aiUnavailable ??
      (selection.aiAvailable
        ? null
        : (selection.notices.find((n) => n.code === 'ai-unavailable')?.message ?? null)),
    queue: null,
    currentSource: {},
    selection,
  };
}

function reducer(state: SearchRunState, action: Action): SearchRunState {
  switch (action.type) {
    case 'reset':
      return INITIAL;
    case 'start':
      // На сервере id приходит ответом на запуск — до этого он пустой, потом его
      // принесёт событие `started` (conditions.searchId).
      return { ...INITIAL, phase: 'running', searchId: action.searchId || null };
    case 'restore': {
      const s = action.selection;
      const base = { ...INITIAL, searchId: s.searchId };
      // Поиск ещё идёт: снимок на экран сразу, итоговой подборки пока нет — её принесёт поток.
      if (s.phase === 'running') return { ...fromSelection(base, s, 'running'), selection: null };
      return fromSelection(base, s, s.phase === 'stopped' ? 'stopped' : 'done');
    }
    case 'retry':
      return { ...state, phase: 'running', error: null };
    case 'excluded': {
      const ids = new Set(action.ids);
      const items = state.items.map((i) =>
        ids.has(i.id) ? { ...i, excluded: action.excluded } : i,
      );
      return {
        ...state,
        items,
        counts: action.counts,
        groups: regroup(state.groups, items),
        statuses: state.statuses.map((s) => ({
          ...s,
          found: action.counts.byPlatform[s.platform],
        })),
      };
    }
    case 'added': {
      const items = mergeItems(state.items, [action.item]);
      return { ...state, items };
    }
    case 'event': {
      const e = action.event;
      if (!state.searchId && action.runId) state = { ...state, searchId: action.runId };
      switch (e.type) {
        case 'queued':
          return { ...state, phase: 'queued', queue: { ahead: e.ahead, etaSec: e.etaSec } };
        case 'started':
          return {
            ...state,
            phase: 'running',
            searchId: e.conditions.searchId || state.searchId,
            queue: null,
            conditions: e.conditions,
            statuses: e.statuses,
          };
        case 'topic':
          return { ...state, topic: e.topic };
        case 'platform': {
          const exists = state.statuses.some((s) => s.platform === e.status.platform);
          return {
            ...state,
            statuses: exists
              ? state.statuses.map((s) => (s.platform === e.status.platform ? e.status : s))
              : [...state.statuses, e.status],
            currentSource: { ...state.currentSource, [e.status.platform]: e.currentSource },
          };
        }
        case 'items':
          return {
            ...state,
            items: mergeItems(state.items, e.items),
            groups: e.groups,
            counts: e.counts,
          };
        case 'ai-unavailable':
          return { ...state, aiUnavailable: e.message };
        case 'connection-lost':
          return { ...state, connectionLost: e.message };
        case 'connection-restored':
          return { ...state, connectionLost: null };
        case 'finished':
          return fromSelection(state, e.selection, 'done');
        case 'stopped':
          return fromSelection(state, e.selection, 'stopped');
        case 'failed':
          // Не удался повтор площадки — подборка остаётся, ошибка видна в `error`.
          if (state.selection)
            return {
              ...state,
              phase: state.selection.phase === 'stopped' ? 'stopped' : 'done',
              error: e.error,
              queue: null,
            };
          return { ...state, phase: 'failed', error: e.error, queue: null };
      }
    }
  }
  return state;
}

export interface SearchRunControls {
  state: SearchRunState;
  /**
   * Запустить поиск. Если поиск уже идёт, второй не запускается (НТ-2) —
   * сначала `stop()` или передайте `{ replace: true }`.
   * Возвращает true, если поиск запущен.
   */
  start: (request: SearchRequest, options?: { replace?: boolean }) => boolean;
  stop: () => void;
  /** «Повторить» по площадке (ТЗ-Ф44) */
  retryPlatform: (platform: PlatformId) => void;
  /** Исключить или вернуть записи (ТЗ-Ф48). Отклоняется `ApiError` при сбое. */
  setExcluded: (itemIds: string[], excluded: boolean) => Promise<void>;
  /** Добавить публикацию по ссылке (П8). */
  addByUrl: (url: string) => Promise<ResultItem>;
  /**
   * Показать поиск по id: панель закрыли и открыли, поиск перенесли во вкладку, страницу
   * обновили, открыли из «Недавних». Законченный — его подборка; идущий — подключаемся к его
   * потоку (`attachSearch`), поиск не перезапускается, «Остановить» работает. Если за это
   * время запустили новый поиск, старый не показываем. Возвращает true, если поиск на экране.
   */
  restore: (searchId: string) => Promise<boolean>;
  reset: () => void;
}

/**
 * Поиск с потоком событий. Новые записи копятся в `state.items` в порядке прихода;
 * как их показывать, не сдвигая читаемое («+5 новых — показать»), решает экран
 * по полю `arrival`.
 */
export function useSearchRun(): SearchRunControls {
  const [state, dispatch] = useReducer(reducer, INITIAL);
  const runRef = useRef<SearchRun | null>(null);
  const unsubscribeRef = useRef<(() => void) | null>(null);
  const searchIdRef = useRef<string | null>(null);
  /** Сколько событий текущего потока уже учтено: при повторной подписке их пропускаем. */
  const seenRef = useRef(0);
  /** Поиск, запущенный в этом такте, и его запрос (см. `start`). */
  const launchRef = useRef<{ key: string; run: SearchRun } | null>(null);

  /**
   * Подписаться на поток. Подписка сначала отдаёт историю — уже учтённые события
   * пропускаем, поэтому переподписка ничего не задваивает.
   */
  const listen = useCallback((run: SearchRun) => {
    unsubscribeRef.current?.();
    let skip = seenRef.current;
    unsubscribeRef.current = run.subscribe((event) => {
      if (event.type === 'started' && event.conditions.searchId) {
        searchIdRef.current = event.conditions.searchId;
      }
      if (skip > 0) {
        skip -= 1;
        return;
      }
      seenRef.current += 1;
      dispatch({ type: 'event', event, runId: run.searchId });
    });
  }, []);

  const attach = useCallback(
    (run: SearchRun) => {
      unsubscribeRef.current?.();
      unsubscribeRef.current = null;
      runRef.current = run;
      searchIdRef.current = run.searchId || null;
      seenRef.current = 0;
      listen(run);
    },
    [listen],
  );

  // Экран (пере)монтирован. StrictMode в разработке монтирует дважды и между этим
  // отписывает: если поток уже есть, а подписки нет — подписываемся снова, без
  // повторного запуска поиска и без задвоенных событий.
  useEffect(() => {
    const run = runRef.current;
    if (run && !unsubscribeRef.current) listen(run);
    return () => {
      // Уход с экрана не останавливает поиск на сервере, только отписывает экран.
      unsubscribeRef.current?.();
      unsubscribeRef.current = null;
    };
  }, [listen]);

  const start = useCallback(
    (request: SearchRequest, options?: { replace?: boolean }): boolean => {
      // Тот же запрос ещё раз в этом же такте — это повтор эффекта (StrictMode в разработке
      // вызывает эффекты дважды), а не новый поиск: второй запуск дал бы лишнюю запись
      // в «Недавних». Поиск уже идёт — возвращаем его.
      const key = JSON.stringify(request);
      const launched = launchRef.current;
      if (launched && launched.key === key && launched.run === runRef.current) return true;
      const current = runRef.current;
      if (current && !current.closed) {
        if (!options?.replace) return false;
        current.stop();
      }
      const run = api.startSearch(request);
      dispatch({ type: 'start', searchId: run.searchId });
      attach(run);
      launchRef.current = { key, run };
      queueMicrotask(() => {
        if (launchRef.current?.run === run) launchRef.current = null;
      });
      return true;
    },
    [attach],
  );

  const stop = useCallback(() => {
    runRef.current?.stop();
  }, []);

  const retryPlatform = useCallback(
    (platform: PlatformId) => {
      const searchId = searchIdRef.current;
      if (!searchId) return;
      const run = api.retryPlatform(searchId, platform);
      dispatch({ type: 'retry', platform });
      attach(run);
    },
    [attach],
  );

  const setExcluded = useCallback(async (itemIds: string[], excluded: boolean) => {
    const searchId = searchIdRef.current;
    if (!searchId) return;
    const counts = await api.setExcluded(searchId, itemIds, excluded);
    dispatch({ type: 'excluded', ids: itemIds, excluded, counts });
  }, []);

  const addByUrl = useCallback(async (url: string) => {
    const searchId = searchIdRef.current;
    if (!searchId) throw new Error('Поиск ещё не запущен');
    const item = await api.addByUrl(searchId, url);
    dispatch({ type: 'added', item });
    const selection = await api.getSelection(searchId);
    dispatch({
      type: 'excluded',
      ids: [],
      excluded: false,
      counts: selection.counts,
    });
    return item;
  }, []);

  const restore = useCallback(
    async (searchId: string): Promise<boolean> => {
      const busy = () => runRef.current !== null && !runRef.current.closed;
      if (busy()) return false;
      let selection: Selection;
      try {
        selection = await api.getSelection(searchId);
      } catch {
        return false;
      }
      if (busy()) return false;
      searchIdRef.current = searchId;
      dispatch({ type: 'restore', selection });
      // Идёт — подключаемся к потоку: снимок, затем ход и итог (повторы снимка сливаются).
      if (selection.phase === 'running') attach(api.attachSearch(searchId));
      return true;
    },
    [attach],
  );

  const reset = useCallback(() => {
    runRef.current?.stop();
    unsubscribeRef.current?.();
    unsubscribeRef.current = null;
    runRef.current = null;
    searchIdRef.current = null;
    seenRef.current = 0;
    launchRef.current = null;
    dispatch({ type: 'reset' });
  }, []);

  return { state, start, stop, retryPlatform, setExcluded, addByUrl, restore, reset };
}
