import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

/**
 * Невидимая область, которую зачитывает скринридер (aria-live). Для хода и итога
 * поиска (НТ-16): «VK: проверено 18 из 40 групп», «Найдено 37 публикаций».
 * Скринридер получает факты, а не описание анимации (08-visual-concept.md).
 */
export function LiveRegion({
  children,
  politeness = 'polite',
  atomic = true,
}: {
  children: ReactNode;
  politeness?: 'polite' | 'assertive';
  atomic?: boolean;
}) {
  return (
    <div
      className="sr-only"
      aria-live={politeness}
      aria-atomic={atomic}
      role={politeness === 'assertive' ? 'alert' : 'status'}
    >
      {children}
    </div>
  );
}

type Announce = (message: string, options?: { assertive?: boolean }) => void;

const AnnouncerContext = createContext<Announce | null>(null);

/**
 * Провайдер объявлений — один на приложение (в оболочке). Держит две живые
 * области: вежливую и срочную. Повтор того же текста тоже будет зачитан.
 */
export function AnnouncerProvider({ children }: { children: ReactNode }) {
  const [polite, setPolite] = useState('');
  const [assertive, setAssertive] = useState('');
  const flip = useRef(false);

  const announce = useCallback<Announce>((message, options) => {
    // Невидимый символ-переключатель заставляет скринридер зачитать повтор.
    flip.current = !flip.current;
    const text = flip.current ? message : message + String.fromCharCode(160);
    if (options?.assertive) setAssertive(text);
    else setPolite(text);
  }, []);

  const value = useMemo(() => announce, [announce]);

  return (
    <AnnouncerContext.Provider value={value}>
      {children}
      <LiveRegion politeness="polite">{polite}</LiveRegion>
      <LiveRegion politeness="assertive">{assertive}</LiveRegion>
    </AnnouncerContext.Provider>
  );
}

/** `const announce = useAnnounce(); announce('Найдено 37 публикаций');` */
export function useAnnounce(): Announce {
  const ctx = useContext(AnnouncerContext);
  if (!ctx) throw new Error('useAnnounce: нет AnnouncerProvider выше по дереву');
  return ctx;
}
