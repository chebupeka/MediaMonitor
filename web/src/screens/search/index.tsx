/**
 * Экран «Поиск» — главный экран расширения, в стиле сайта «Медиарадар», только спокойнее.
 *
 * Сверху — точки по словарю форм (08-visual-concept.md): пока человек вводит запрос,
 * облако «слушает»; идёт поиск — три облака площадок текут на карту; найдено — на карте
 * загораются города, по точке на публикацию; пусто — точки гаснут; сбой — облако
 * площадки серое и мерцает. Ниже — поле запроса, период, режим, строка состояния
 * и подборка карточками. Факты на картинке продублированы текстом под ней.
 */
import { FileSpreadsheet, Maximize2 } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { api, demoQueries, useAsync, useSearchRun, type SearchRunState } from '@/api';
import type {
  IsoDate,
  Period,
  PeriodPreset,
  PlatformId,
  PlatformState,
  ResultItem,
  SearchMode,
  SearchRequest,
} from '@/api/types';
import { useNavigation, type ScreenProps } from '@/app/navigation';
import { useShell } from '@/app/shell-state';
import {
  Button,
  Chip,
  EmptyState,
  ErrorState,
  IconButton,
  Screen,
  StatusLine,
  TextArea,
  ToggleGroup,
  useAnnounce,
  useToast,
} from '@/components';
import {
  DotsScene,
  KRAI_CITIES,
  type DotsCityCount,
  type DotsForm,
  type DotsPlatformState,
} from '@/dots';
import { WORDS, formatCount, formatPeriod, plural } from '@/lib/format';
import { getHost } from '@/lib/host';
import { REGION_PRINCIPLE, RELEVANCE_ORDER, RELEVANCE_SHORT } from '@/lib/labels';
import { AiDots } from '@/screens/ai-check/AiMark';
import { ExportDialog } from './ExportDialog';
import { ResultCard } from './ResultCard';
import { loadSavedSearch, saveSearch, type ResultFilter, type SavedSearch } from './saved';
import styles from './search.module.css';

const PERIODS: { value: PeriodPreset; label: string }[] = [
  { value: 'today', label: 'Сегодня' },
  { value: '7d', label: '7 дней' },
  { value: '30d', label: '30 дней' },
];

const MODES: { value: SearchMode; label: string }[] = [
  { value: 'everywhere', label: 'Везде' },
  { value: 'my-sources', label: 'Мои источники' },
];

/** «Сейчас» имитации — 19 октября 2026 (web/README.md, «Имитация и демо-данные»). */
const MOCK_TODAY: IsoDate = '2026-10-19';

function shiftDate(date: IsoDate, days: number): IsoDate {
  const [y = 1970, m = 1, d = 1] = date.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d) + days * 86_400_000).toISOString().slice(0, 10);
}

/** Готовый период до сегодняшнего дня включительно. `today` — по данным сервера (или имитации). */
function periodFor(preset: PeriodPreset, today: IsoDate = MOCK_TODAY): Period {
  const days = preset === 'today' ? 0 : preset === '24h' ? 1 : preset === '7d' ? 6 : 29;
  return { preset, from: shiftDate(today, -days), to: today };
}

/**
 * Условия запроса из «Недавних», которых нет среди полей экрана: свой период из календаря,
 * выбранные источники, значение многозначного запроса, правки карточки темы. Подставляются
 * в следующий поиск, пока человек не поменял соответствующее поле.
 */
interface Carried {
  text: string;
  period: Period;
  sourceIds?: string[];
  meaningId?: string;
  topic?: SearchRequest['topic'];
}

/** Города, которые есть на карте точек. */
const MAP_CITIES = new Set(KRAI_CITIES.map((c) => c.name));

/** Состояние площадки → состояние её облака точек. */
function cloudState(state: PlatformState): DotsPlatformState {
  if (state === 'waiting') return 'idle';
  if (state === 'searching') return 'active';
  if (state === 'error' || state === 'no-access') return 'failed';
  return 'done';
}

interface DotsView {
  form: DotsForm;
  platforms: Partial<Record<PlatformId, DotsPlatformState>>;
  cities: DotsCityCount[];
  /** Те же факты текстом — для всех, кто не смотрит на картинку */
  caption: string;
}

/** Что показывают точки сейчас: момент продукта по словарю форм. */
function dotsView(state: SearchRunState, listening: boolean): DotsView {
  const platforms: Partial<Record<PlatformId, DotsPlatformState>> = {};
  for (const s of state.statuses) platforms[s.platform] = cloudState(s.state);
  const failed = state.statuses.filter((s) => cloudState(s.state) === 'failed').length;
  const items = state.items.filter((i) => !i.excluded);

  if (state.phase === 'queued' || state.phase === 'running')
    return {
      form: 'searching',
      platforms,
      cities: [],
      caption: 'Идёт поиск во ВКонтакте, Одноклассниках и MAX.',
    };

  if (state.phase === 'done' || state.phase === 'stopped') {
    if (items.length > 0) {
      // Точка загорается в городе, только если город известен и есть на карте
      // (правила честности 1 и 2): одна публикация — одна точка.
      const byCity = new Map<string, number>();
      for (const item of items) {
        const city = item.regionReason.places.find((p) => MAP_CITIES.has(p));
        if (city) byCity.set(city, (byCity.get(city) ?? 0) + 1);
      }
      const cities = [...byCity.entries()]
        .map(([city, count]) => ({ city, count }))
        .sort((a, b) => b.count - a.count);
      const onMap = cities.reduce((s, c) => s + c.count, 0);
      const offMap = items.length - onMap;
      const top = cities
        .slice(0, 4)
        .map((c) => `${c.city} ${c.count}`)
        .join(', ');
      const more = cities.length > 4 ? ` и ещё ${cities.length - 4}` : '';
      const rest = offMap > 0 ? ` Ещё ${offMap} — без точного города, на карте не отмечены.` : '';
      return {
        form: 'found',
        platforms,
        cities,
        caption:
          onMap > 0
            ? `На карте — ${formatCount(onMap, WORDS.publication)}: ${top}${more}.${rest}`
            : 'У найденных публикаций нет точного города — на карте они не отмечены.',
      };
    }
    if (failed > 0)
      return {
        form: 'failure',
        platforms,
        cities: [],
        caption: 'Часть площадок не ответила — их облака серые.',
      };
    return { form: 'empty', platforms, cities: [], caption: 'Ничего не нашли.' };
  }

  if (state.phase === 'failed')
    return { form: 'failure', platforms, cities: [], caption: 'Поиск не удался.' };

  return listening
    ? {
        form: 'listening',
        platforms,
        cities: [],
        caption: 'Система слушает: введите запрос и нажмите «Найти».',
      }
    : {
        form: 'krai',
        platforms,
        cities: [],
        caption: 'Красноярский край: ищем во ВКонтакте, Одноклассниках и MAX.',
      };
}

export default function SearchScreen({ params, navKey }: ScreenProps<'search'>) {
  const { navigate } = useNavigation();
  const { layout } = useShell();
  const { state, start, stop, retryPlatform, setExcluded, restore } = useSearchRun();
  const toast = useToast();
  const announce = useAnnounce();
  /** Поиск, итог которого уже озвучен скринридеру */
  const announced = useRef<string | null>(null);
  const [text, setText] = useState(params.text ?? '');
  const [preset, setPreset] = useState<PeriodPreset>('30d');
  const [mode, setMode] = useState<SearchMode>('everywhere');
  const [focused, setFocused] = useState(false);
  const [filter, setFilter] = useState<ResultFilter>('all');
  const [exportOpen, setExportOpen] = useState(false);
  /** Прошлое состояние уже подставлено (или его не было) — можно запоминать новое. */
  const [ready, setReady] = useState(false);
  const [carried, setCarried] = useState<Carried | null>(null);
  const firstVisit = useRef(true);
  // «Сегодня» — у сервера: период по умолчанию заканчивается сегодняшним днём.
  const startState = useAsync(useCallback(() => api.getStartState(), []));
  const today = startState.data?.defaultPeriod.to ?? MOCK_TODAY;

  const running = state.phase === 'running' || state.phase === 'queued';
  const finished = state.phase === 'done' || state.phase === 'stopped';

  /** Запрос из полей экрана и перенесённых условий «Недавних». */
  const requestFor = (value: string): SearchRequest => {
    const sameText = carried !== null && carried.text.trim() === value.trim();
    const period =
      carried && carried.period.preset === preset ? carried.period : periodFor(preset, today);
    return {
      text: value,
      period,
      mode,
      ...(mode === 'my-sources' && carried?.sourceIds ? { sourceIds: carried.sourceIds } : {}),
      ...(sameText && carried.meaningId ? { meaningId: carried.meaningId } : {}),
      ...(sameText && carried.topic ? { topic: carried.topic } : {}),
    };
  };

  const run = (value: string) => {
    if (!value.trim()) return;
    setFilter('all');
    start(requestFor(value), { replace: true });
  };

  /** Подставить все условия запроса: текст, период, режим и то, чего нет среди полей. */
  const applyRequest = (request: SearchRequest) => {
    setText(request.text);
    setPreset(request.period.preset);
    setMode(request.mode);
    setCarried({
      text: request.text,
      period: request.period,
      ...(request.sourceIds ? { sourceIds: request.sourceIds } : {}),
      ...(request.meaningId ? { meaningId: request.meaningId } : {}),
      ...(request.topic ? { topic: request.topic } : {}),
    });
  };

  // Новый переход на экран с параметрами: подставить текст или сразу искать
  // (так приходит выделенный текст из контекстного меню расширения).
  // Без параметров при первом показе возвращаем прошлый поиск: панель закрыли и открыли,
  // поиск перенесли во вкладку, страницу перезагрузили.
  useEffect(() => {
    const first = firstVisit.current;
    firstVisit.current = false;
    if (params.request) {
      applyRequest(params.request);
      if (params.autoRun) start(params.request, { replace: true });
      setReady(true);
    } else if (params.text !== undefined) {
      setText(params.text);
      setCarried(null);
      if (params.autoRun)
        start(
          { text: params.text, period: periodFor('30d', today), mode: 'everywhere' },
          { replace: true },
        );
      setReady(true);
    } else if (first) {
      void loadSavedSearch()
        .then(async (saved) => {
          if (!saved) return;
          setText(saved.text);
          setPreset(saved.preset);
          setMode(saved.mode);
          setFilter(saved.filter);
          if (saved.searchId && (await restore(saved.searchId))) {
            announced.current = saved.searchId;
            announce('Показан прошлый поиск: подборка сохранилась.');
          }
        })
        .catch(() => undefined)
        .finally(() => setReady(true));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- реагируем только на новый переход
  }, [navKey]);

  // Запоминаем запрос, условия и законченный поиск — для следующего открытия.
  const savedSearchId = finished ? state.searchId : null;
  const current = useMemo<SavedSearch>(
    () => ({ text, preset, mode, filter, searchId: savedSearchId }),
    [text, preset, mode, filter, savedSearchId],
  );
  useEffect(() => {
    if (!ready) return;
    const timer = window.setTimeout(() => void saveSearch(current), 250);
    return () => window.clearTimeout(timer);
  }, [ready, current]);

  // «Открыть во вкладке» есть только в боковой панели расширения
  const openInTab = layout === 'panel' ? getHost().openInTab : null;
  const moveToTab = async () => {
    if (!openInTab) return;
    await saveSearch(current);
    await openInTab();
  };

  // Итог поиска — вслух для скринридера
  useEffect(() => {
    if (!finished || !state.searchId || announced.current === state.searchId) return;
    announced.current = state.searchId;
    announce(`Поиск завершён: ${formatCount(state.counts?.total ?? 0, WORDS.publication)}.`);
  }, [finished, state.searchId, state.counts, announce]);

  const dots = useMemo(
    () => dotsView(state, focused || text.trim().length > 0),
    [state, focused, text],
  );
  const visible = state.items.filter((i) =>
    filter === 'all'
      ? true
      : filter === 'ai'
        ? i.aiCheck?.level === 'likely-ai'
        : i.relevance === filter,
  );
  const aiLikely = state.counts?.aiLikely ?? 0;
  const total = state.counts?.total ?? 0;
  const releaseGroup = state.groups.find((g) => g.kind === 'release');

  const toggleExcluded = (item: ResultItem) => {
    const next = !item.excluded;
    void setExcluded([item.id], next);
    if (next)
      toast.undo(
        'Публикация исключена',
        () => void setExcluded([item.id], false),
        'Счётчик и выгрузка пересчитаны.',
      );
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    run(text);
  };

  return (
    <Screen
      title="Поиск"
      eyebrow="Красноярский край · ВКонтакте, Одноклассники, MAX"
      width="narrow"
      className={styles.screen}
    >
      <figure className={styles.stage}>
        <DotsScene
          form={dots.form}
          intensity="calm"
          platforms={dots.platforms}
          cities={dots.cities}
          height={200}
        />
        <figcaption className={styles.caption}>{dots.caption}</figcaption>
      </figure>

      <form className={styles.query} onSubmit={onSubmit} aria-label="Запрос">
        <TextArea
          label="Запрос"
          hideLabel
          placeholder="Тема, событие, человек или текст новости"
          value={text}
          rows={3}
          onChange={(e) => setText(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
        />
        <div className={styles.examples}>
          <span className={styles.examplesLabel}>Например:</span>
          {demoQueries.slice(0, 3).map((q) => (
            <Chip
              key={q.id}
              size="sm"
              onClick={() => {
                setText(q.text);
                run(q.text);
              }}
            >
              {q.label}
            </Chip>
          ))}
        </div>
        <div className={styles.controls}>
          <ToggleGroup
            label="Период"
            items={PERIODS}
            value={preset}
            onValueChange={setPreset}
            size="sm"
          />
          <ToggleGroup
            label="Где искать"
            items={MODES}
            value={mode}
            onValueChange={setMode}
            size="sm"
          />
        </div>
        {carried &&
          carried.period.preset === preset &&
          !PERIODS.some((p) => p.value === preset) && (
            <p className={styles.region}>
              <span className={styles.regionDot} aria-hidden="true" />
              <span>
                <b>Период из недавнего поиска:</b> {formatPeriod(carried.period)}. Другой — выберите
                выше.
              </span>
            </p>
          )}
        {mode === 'my-sources' && carried?.sourceIds && carried.sourceIds.length > 0 && (
          <p className={styles.region}>
            <span className={styles.regionDot} aria-hidden="true" />
            <span>
              <b>Источники из недавнего поиска:</b>{' '}
              {formatCount(carried.sourceIds.length, WORDS.source)} из вашего списка.
            </span>
          </p>
        )}
        <p className={styles.region}>
          <span className={styles.regionDot} aria-hidden="true" />
          <span>
            <b>Красноярский край.</b> {REGION_PRINCIPLE}
          </span>
        </p>
        <div className={styles.submit}>
          {running ? (
            <Button type="button" size="lg" onClick={stop}>
              Остановить
            </Button>
          ) : (
            <Button type="submit" variant="primary" size="lg" disabled={!text.trim()}>
              Найти
            </Button>
          )}
        </div>
      </form>

      {state.phase === 'queued' && state.queue && (
        <p className={styles.notice} role="status">
          Вы в очереди: перед вами {state.queue.ahead}. Поиск начнётся примерно через{' '}
          {state.queue.etaSec} с.
        </p>
      )}
      {state.connectionLost && (
        <p className={styles.notice} role="status">
          {state.connectionLost}
        </p>
      )}
      {state.aiUnavailable && (
        <p className={styles.notice} role="status">
          {state.aiUnavailable}
        </p>
      )}

      {state.phase === 'failed' && (
        <ErrorState
          title="Поиск не удался"
          description={state.error?.message}
          onRetry={() => run(text)}
        />
      )}

      {state.conditions && (
        <StatusLine
          conditions={state.conditions}
          statuses={state.statuses}
          total={total}
          running={running}
          currentSource={state.currentSource}
          onRetry={retryPlatform}
          actions={
            releaseGroup && state.searchId ? (
              <Button
                size="sm"
                variant="secondary"
                onClick={() =>
                  navigate('spread', {
                    searchId: state.searchId ?? undefined,
                    groupId: releaseGroup.id,
                  })
                }
              >
                Распространение
              </Button>
            ) : undefined
          }
        />
      )}

      {state.items.length > 0 && (
        <section className={styles.results} aria-labelledby="results-title">
          <div className={styles.resultsHead}>
            <h2 id="results-title" className={styles.found}>
              <span className={styles.foundNum}>{total}</span>
              <span className={styles.foundLabel}>
                {plural(total, WORDS.publication)}
                {state.counts && state.counts.new > 0 ? ` · новых ${state.counts.new}` : ''}
                {running ? ' · поиск идёт' : ''}
              </span>
            </h2>
            <div className={styles.resultsActions}>
              {finished && state.searchId && (
                <Button
                  variant="secondary"
                  iconStart={<FileSpreadsheet />}
                  onClick={() => setExportOpen(true)}
                >
                  Скачать XLSX · {total}
                </Button>
              )}
              {openInTab && (
                <IconButton
                  label="Открыть во вкладке — шире для большой подборки"
                  icon={<Maximize2 />}
                  variant="secondary"
                  onClick={() => void moveToTab()}
                />
              )}
            </div>
          </div>
          <div className={styles.filters} role="group" aria-label="Показать">
            <Chip size="sm" selected={filter === 'all'} onClick={() => setFilter('all')}>
              Все
            </Chip>
            {RELEVANCE_ORDER.map((r) => (
              <Chip
                key={r}
                size="sm"
                selected={filter === r}
                count={state.counts?.byRelevance[r] ?? 0}
                tone={r === 'disputed' ? 'warning' : 'neutral'}
                onClick={() => setFilter(r)}
              >
                {RELEVANCE_SHORT[r]}
              </Chip>
            ))}
            {/* Проверка на ИИ: только «похоже на ИИ»; метка ни на что не влияет */}
            {(aiLikely > 0 || filter === 'ai') && (
              <Chip
                size="sm"
                selected={filter === 'ai'}
                count={aiLikely}
                icon={<AiDots level="likely-ai" />}
                onClick={() => setFilter('ai')}
              >
                Похоже на ИИ
              </Chip>
            )}
          </div>
          <ul className={styles.list}>
            {visible.map((item) => (
              <li key={item.id}>
                <ResultCard item={item} onToggleExcluded={toggleExcluded} />
              </li>
            ))}
          </ul>
        </section>
      )}

      {finished && state.items.length === 0 && (
        <EmptyState
          title="Ничего не нашли"
          description="Это не ошибка: площадки ответили, подходящих публикаций нет. Попробуйте другой период или опишите тему иначе."
        />
      )}

      {state.searchId && (
        <ExportDialog searchId={state.searchId} open={exportOpen} onOpenChange={setExportOpen} />
      )}
    </Screen>
  );
}
