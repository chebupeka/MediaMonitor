/**
 * Состояние оболочки: вид (тема, «Тёплый свет», версия для слабовидящих — src/app/prefs.ts),
 * раскладка (вкладка или боковая панель расширения), включены ли анимированные точки.
 * Экраны читают его через `useShell()`.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from 'react';
import { flushSync } from 'react-dom';
import { IS_WEB_BUILD } from '@/lib/build';
import {
  applyPrefs,
  prefsKey,
  readPrefs,
  savePrefs,
  systemTheme,
  withTransition,
  type Prefs,
  type Theme,
} from './prefs';
import { urlLayout } from './url-hints';

export type { Theme } from './prefs';
/** `site` — вкладка (широко); `panel` — боковая панель расширения (380 px) */
export type Layout = 'site' | 'panel';

export interface Shell {
  /** Тема: тёмная или светлая «чернила на бумаге» */
  theme: Theme;
  /** То же, что `theme` (для холстов и старого кода) */
  resolvedTheme: Theme;
  setTheme: (theme: Theme) => void;
  /** «Тёплый свет» — меньше синего; действует только в светлой теме */
  warm: boolean;
  setWarm: (warm: boolean) => void;
  /** Версия для слабовидящих: крупный шрифт, максимальный контраст, без точек и анимаций */
  lowVision: boolean;
  setLowVision: (on: boolean) => void;
  /** Имя текущего вида: при смене холсты перечитывают цвета из токенов */
  themeKey: string;
  layout: Layout;
  setLayout: (layout: Layout) => void;
  /** Точки показываются: переключатель «Анимация точек» включён и это не версия для слабовидящих */
  dotsEnabled: boolean;
  /** Положение переключателя «Анимация точек» */
  dotsChoice: boolean;
  setDotsEnabled: (enabled: boolean) => void;
  /** Пользователь просит меньше движения (prefers-reduced-motion) */
  reducedMotion: boolean;
}

const ShellContext = createContext<Shell | null>(null);

const KEY = 'mm-mockup-shell';

interface Stored {
  layout: Layout;
  dotsEnabled: boolean;
}

function loadStored(): Stored {
  const fallback: Stored = { layout: 'site', dotsEnabled: true };
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as Partial<Stored>;
    return {
      layout: parsed.layout === 'panel' ? 'panel' : 'site',
      dotsEnabled: parsed.dotsEnabled !== false,
    };
  } catch {
    return fallback;
  }
}

function load(): Stored {
  const stored = loadStored();
  // Веб-версия — всегда вкладка: предпросмотра боковой панели в ней нет
  const layout = IS_WEB_BUILD ? 'site' : (urlLayout() ?? stored.layout);
  return { ...stored, layout };
}

function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const mql = window.matchMedia(query);
      mql.addEventListener('change', onChange);
      return () => mql.removeEventListener('change', onChange);
    },
    () => window.matchMedia(query).matches,
  );
}

export function ShellProvider({ children }: { children: ReactNode }) {
  const [stored, setStored] = useState<Stored>(load);
  const [prefs, setPrefs] = useState<Prefs>(() => {
    const p = readPrefs();
    applyPrefs(p); // до первой отрисовки
    return p;
  });
  const prefsRef = useRef(prefs);
  prefsRef.current = prefs;
  const reducedMotion = useMediaQuery('(prefers-reduced-motion: reduce)');

  useEffect(() => {
    try {
      window.localStorage.setItem(KEY, JSON.stringify(stored));
    } catch {
      // хранилище недоступно — настройки живут до перезагрузки
    }
  }, [stored]);

  /** Новый вид — плавно: атрибуты и состояние меняются внутри перехода, синхронно. */
  const change = useCallback((patch: Partial<Prefs>) => {
    const prev = prefsRef.current;
    const next = { ...prev, ...patch };
    savePrefs(next, prev);
    withTransition(() => {
      applyPrefs(next);
      flushSync(() => setPrefs(next));
    });
  }, []);

  // Пока человек сам не выбрал тему — она следует за системой
  useEffect(() => {
    const mql = window.matchMedia?.('(prefers-color-scheme: light)');
    if (!mql) return;
    const follow = () => {
      if (!prefsRef.current.chosen) change({ theme: systemTheme() });
    };
    mql.addEventListener('change', follow);
    return () => mql.removeEventListener('change', follow);
  }, [change]);

  const setTheme = useCallback((theme: Theme) => change({ theme, chosen: true }), [change]);
  const setWarm = useCallback((warm: boolean) => change({ warm }), [change]);
  const setLowVision = useCallback((lowVision: boolean) => change({ lowVision }), [change]);
  const setLayout = useCallback((layout: Layout) => setStored((s) => ({ ...s, layout })), []);
  const setDotsEnabled = useCallback(
    (dotsEnabled: boolean) => setStored((s) => ({ ...s, dotsEnabled })),
    [],
  );

  const value = useMemo<Shell>(
    () => ({
      theme: prefs.theme,
      resolvedTheme: prefs.theme,
      setTheme,
      warm: prefs.warm,
      setWarm,
      lowVision: prefs.lowVision,
      setLowVision,
      themeKey: prefsKey(prefs),
      layout: stored.layout,
      setLayout,
      dotsEnabled: stored.dotsEnabled && !prefs.lowVision,
      dotsChoice: stored.dotsEnabled,
      setDotsEnabled,
      reducedMotion,
    }),
    [stored, prefs, reducedMotion, setTheme, setWarm, setLowVision, setLayout, setDotsEnabled],
  );

  return <ShellContext.Provider value={value}>{children}</ShellContext.Provider>;
}

export function useShell(): Shell {
  const ctx = useContext(ShellContext);
  if (!ctx) throw new Error('useShell: нет ShellProvider выше по дереву');
  return ctx;
}
