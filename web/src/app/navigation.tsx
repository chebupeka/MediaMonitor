/**
 * Навигация без адресной строки (мокап публикуется одной страницей, где адрес
 * недоступен). Своё состояние: текущий экран, его параметры и история для «Назад».
 *
 * Экран получает параметры в props (`ScreenProps<'search'>`), переходит дальше
 * через `useNavigation().navigate('spread', { searchId, groupId })`.
 */
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';
import type { SearchRequest } from '@/api/types';

export type ScreenId =
  | 'landing' // Л. Лендинг
  | 'search' // П1–П3, П7: поиск, ход, подборка, состояния
  | 'spread' // П4: распространение новости
  | 'ai-check' // проверка текста на ИИ (04-decisions.md, «Проверка текста на ИИ»)
  | 'sources' // П5: источники
  | 'recent' // П6: недавние поиски
  | 'how' // П8: как это работает
  | 'status' // П9: состояние стенда
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
  /** Назад по истории; если некуда — на лендинг */
  back: () => void;
  canGoBack: boolean;
}

const NavigationContext = createContext<Navigation | null>(null);

let navCounter = 0;

export function NavigationProvider({
  initial = 'landing',
  initialParams = {},
  children,
}: {
  initial?: ScreenId;
  initialParams?: ScreenParamsMap[ScreenId];
  children: ReactNode;
}) {
  const [history, setHistory] = useState<Entry[]>([
    { screen: initial, params: initialParams, key: 0 },
  ]);

  const navigate = useCallback(<S extends ScreenId>(screen: S, params?: ScreenParamsMap[S]) => {
    navCounter += 1;
    const entry: Entry = { screen, params: params ?? {}, key: navCounter };
    setHistory((h) => [...h.slice(-30), entry]);
  }, []);

  const back = useCallback(() => {
    setHistory((h) =>
      h.length > 1 ? h.slice(0, -1) : [{ screen: 'landing', params: {}, key: ++navCounter }],
    );
  }, []);

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
