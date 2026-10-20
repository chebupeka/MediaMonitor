/**
 * Навигация между экранами: текущий экран, его параметры и история для «Назад».
 *
 * Два режима:
 * - **в памяти** — мокап (публикуется и одним файлом) и расширение: адрес страницы не меняется;
 * - **по адресу** (`urlRouting`, веб-версия на сервере, решение Р-В4) — каждый переход пишет
 *   `/app/<раздел>` в историю браузера (src/app/routes.ts): «Назад» и «Вперёд» браузера
 *   ходят по разделам, F5 оставляет на том же экране. Переход по истории браузера открывает
 *   экран без параметров действия: поиск заново не запускается.
 *
 * Экран получает параметры в props (`ScreenProps<'search'>`), переходит дальше
 * через `useNavigation().navigate('spread', { searchId, groupId })`.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import type { SearchRequest } from '@/api/types';
import { routeFromLocation, urlFor } from './routes';

export type ScreenId =
  | 'landing' // Л. Лендинг
  | 'search' // П1–П3, П7: поиск, ход, подборка, состояния
  | 'spread' // П4: распространение новости
  | 'ai-check' // проверка текста на ИИ (04-decisions.md, «Проверка текста на ИИ»)
  | 'sources' // П5: источники
  | 'recent' // П6: недавние поиски
  | 'how' // П8: как это работает
  | 'status' // П9: состояние стенда
  | 'not-found' // неизвестный адрес веб-версии: «Такого раздела нет»
  | 'demo-page' // Р: демо-страница СМИ для расширения
  | 'gallery'; // витрина базовых компонентов (только мокап)

/** Параметры перехода на каждый экран. Все необязательные. */
export interface ScreenParamsMap {
  landing: Record<string, never>;
  search: {
    /** Подставить текст в поле запроса */
    text?: string;
    /** Полный запрос (например, «Повторить» из недавних, с `repeatOf`) */
    request?: SearchRequest;
    /** Сразу запустить поиск */
    autoRun?: boolean;
    /** Показать сохранённую подборку прошлого поиска без нового поиска («Недавние», Р-В9) */
    searchId?: string;
  };
  spread: {
    /** Поиск по тексту новости, из подборки которого строим распространение */
    searchId?: string;
    groupId?: string;
    /** Текст новости — например, выделенный на странице СМИ (расширение) */
    text?: string;
  };
  'ai-check': {
    /** Текст для проверки — например, выделенный на странице (пункт «Проверить текст на ИИ») */
    text?: string;
    /** Сразу проверить */
    autoRun?: boolean;
  };
  sources: {
    /** Что открыть сразу: добавление по ссылке, каталог или импорт */
    focus?: 'add' | 'catalog' | 'import';
  };
  recent: Record<string, never>;
  how: {
    section?: 'data' | 'region' | 'selection' | 'privacy' | 'limits';
  };
  status: Record<string, never>;
  'not-found': Record<string, never>;
  'demo-page': Record<string, never>;
  gallery: Record<string, never>;
}

export interface ScreenProps<S extends ScreenId> {
  params: ScreenParamsMap[S];
  /** Растёт при каждом переходе на экран — по нему можно реагировать на новые параметры */
  navKey: number;
  /** Экран сейчас виден (неактивные экраны остаются в памяти, но скрыты) */
  active: boolean;
}

interface Entry {
  screen: ScreenId;
  params: ScreenParamsMap[ScreenId];
  key: number;
}

export interface Navigation {
  screen: ScreenId;
  params: ScreenParamsMap[ScreenId];
  navKey: number;
  navigate: <S extends ScreenId>(screen: S, params?: ScreenParamsMap[S]) => void;
  /** Назад по истории; если некуда — на лендинг (по адресу — «Назад» браузера) */
  back: () => void;
  canGoBack: boolean;
}

const NavigationContext = createContext<Navigation | null>(null);

let navCounter = 0;

function currentUrl(): string {
  return `${window.location.pathname}${window.location.search}`;
}

export function NavigationProvider({
  initial = 'landing',
  initialParams = {},
  urlRouting = false,
  children,
}: {
  initial?: ScreenId;
  initialParams?: ScreenParamsMap[ScreenId];
  /** Синхронизировать экран с адресом страницы (веб-версия, src/app/routes.ts) */
  urlRouting?: boolean;
  children: ReactNode;
}) {
  const [history, setHistory] = useState<Entry[]>([
    { screen: initial, params: initialParams, key: 0 },
  ]);

  // Адрес — канонический путь экрана: `/app/?q=…` → `/app/` (текст уже в поле запроса).
  // Неизвестный адрес оставляем как есть, чтобы было видно, что набрано.
  useEffect(() => {
    if (!urlRouting || initial === 'not-found') return;
    const url = urlFor(initial, initialParams);
    if (url === currentUrl()) return;
    try {
      window.history.replaceState(window.history.state, '', `${url}${window.location.hash}`);
    } catch {
      // адрес не поменять — не страшно
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- только при загрузке страницы
  }, []);

  // «Назад» и «Вперёд» браузера: экран из адреса, без параметров действия.
  useEffect(() => {
    if (!urlRouting) return;
    const onPop = () => {
      const route = routeFromLocation();
      navCounter += 1;
      const entry: Entry = { screen: route.screen, params: route.params, key: navCounter };
      setHistory((h) => [...h.slice(-30), entry]);
    };
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, [urlRouting]);

  const navigate = useCallback(
    <S extends ScreenId>(screen: S, params?: ScreenParamsMap[S]) => {
      navCounter += 1;
      const entry: Entry = { screen, params: params ?? {}, key: navCounter };
      setHistory((h) => [...h.slice(-30), entry]);
      if (!urlRouting) return;
      const url = urlFor(screen, entry.params);
      try {
        // Тот же адрес (снова «Поиск» на «Поиске») — без новой записи в истории.
        if (url === currentUrl()) window.history.replaceState(window.history.state, '', url);
        else window.history.pushState(null, '', url);
      } catch {
        // песочница без истории — экран всё равно сменился
      }
    },
    [urlRouting],
  );

  const back = useCallback(() => {
    if (urlRouting) {
      window.history.back();
      return;
    }
    setHistory((h) =>
      h.length > 1 ? h.slice(0, -1) : [{ screen: 'landing', params: {}, key: ++navCounter }],
    );
  }, [urlRouting]);

  const value = useMemo<Navigation>(() => {
    const current = history[history.length - 1] ?? { screen: initial, params: {}, key: 0 };
    return {
      screen: current.screen,
      params: current.params,
      navKey: current.key,
      navigate,
      back,
      canGoBack: history.length > 1,
    };
  }, [history, initial, navigate, back]);

  return <NavigationContext.Provider value={value}>{children}</NavigationContext.Provider>;
}

export function useNavigation(): Navigation {
  const ctx = useContext(NavigationContext);
  if (!ctx) throw new Error('useNavigation: нет NavigationProvider выше по дереву');
  return ctx;
}
