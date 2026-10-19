/**
 * Состояние оболочки: тема, раскладка (сайт или боковая панель расширения),
 * включены ли анимированные точки. Экраны читают его через `useShell()`.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from 'react';
import { urlLayout, urlTheme } from './url-hints';

export type ThemeChoice = 'system' | 'light' | 'dark';
/** `site` — обычный сайт; `panel` — предпросмотр боковой панели расширения (380 px) */
export type Layout = 'site' | 'panel';

export interface Shell {
  theme: ThemeChoice;
  /** Тема, которая видна сейчас (с учётом системной настройки) */
  resolvedTheme: 'light' | 'dark';
  setTheme: (theme: ThemeChoice) => void;
  layout: Layout;
  setLayout: (layout: Layout) => void;
  /** Анимация точек включена (08: «выключается одним переключателем») */
  dotsEnabled: boolean;
  setDotsEnabled: (enabled: boolean) => void;
  /** Пользователь просит меньше движения (prefers-reduced-motion) */
  reducedMotion: boolean;
}

const ShellContext = createContext<Shell | null>(null);

const KEY = 'mm-mockup-shell';

interface Stored {
  theme: ThemeChoice;
  layout: Layout;
  dotsEnabled: boolean;
}

function loadStored(): Stored {
  // По умолчанию — тёмная тема, как на сайте «Стрежень»; светлую можно выбрать в меню «Вид».
  const fallback: Stored = { theme: 'dark', layout: 'site', dotsEnabled: true };
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as Partial<Stored>;
    return {
      theme:
        parsed.theme === 'light' || parsed.theme === 'dark' || parsed.theme === 'system'
          ? parsed.theme
          : fallback.theme,
      layout: parsed.layout === 'panel' ? 'panel' : 'site',
      dotsEnabled: parsed.dotsEnabled !== false,
    };
  } catch {
    return fallback;
  }
}

function load(): Stored {
  const stored = loadStored();
  return { ...stored, theme: urlTheme() ?? stored.theme, layout: urlLayout() ?? stored.layout };
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
  const prefersDark = useMediaQuery('(prefers-color-scheme: dark)');
  const reducedMotion = useMediaQuery('(prefers-reduced-motion: reduce)');

  useEffect(() => {
    try {
      window.localStorage.setItem(KEY, JSON.stringify(stored));
    } catch {
      // хранилище недоступно — настройки живут до перезагрузки
    }
  }, [stored]);

  useEffect(() => {
    const root = document.documentElement;
    if (stored.theme === 'system') delete root.dataset.theme;
    else root.dataset.theme = stored.theme;
  }, [stored.theme]);

  const setTheme = useCallback((theme: ThemeChoice) => setStored((s) => ({ ...s, theme })), []);
  const setLayout = useCallback((layout: Layout) => setStored((s) => ({ ...s, layout })), []);
  const setDotsEnabled = useCallback(
    (dotsEnabled: boolean) => setStored((s) => ({ ...s, dotsEnabled })),
    [],
  );

  const value = useMemo<Shell>(
    () => ({
      theme: stored.theme,
      resolvedTheme: stored.theme === 'system' ? (prefersDark ? 'dark' : 'light') : stored.theme,
      setTheme,
      layout: stored.layout,
      setLayout,
      dotsEnabled: stored.dotsEnabled,
      setDotsEnabled,
      reducedMotion,
    }),
    [stored, prefersDark, reducedMotion, setTheme, setLayout, setDotsEnabled],
  );

  return <ShellContext.Provider value={value}>{children}</ShellContext.Provider>;
}

export function useShell(): Shell {
  const ctx = useContext(ShellContext);
  if (!ctx) throw new Error('useShell: нет ShellProvider выше по дереву');
  return ctx;
}
