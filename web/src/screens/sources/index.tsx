/**
 * П5. Источники (ТЗ-Ф15, Ф16; П9, П13; НТ-7, НТ-14; SC-10, SC-11, SC-30) — в стиле
 * «Поиска» и «Распространения»: крупные цифры узким гротеском, плитки, таблица, которая в
 * узкой панели становится карточками.
 *
 * Список групп и каналов для режима «Мои источники»: поиск и фильтры, добавить по ссылке
 * с проверкой, правка, удаление с отменой, импорт из Excel, готовый каталог края.
 * Первый запуск — пустой список, каталог и объяснение режима «Везде».
 */
import { FileSpreadsheet, Library, Plus, RotateCw } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { api, errorMessage, useAsync } from '@/api';
import type { PlatformId, Source } from '@/api/types';
import { useNavigation, type ScreenProps } from '@/app/navigation';
import {
  Button,
  Chip,
  cx,
  EmptyState,
  ErrorState,
  Screen,
  Skeleton,
  StatusBadge,
  TextField,
  ToggleGroup,
  useAnnounce,
  useToast,
} from '@/components';
import {
  formatCount,
  formatDateTime,
  formatNumber,
  plural,
  TIME_ZONE_LABEL,
  WORDS,
} from '@/lib/format';
import { PLATFORM_ORDER, PLATFORMS, SOURCE_TYPE_LABEL } from '@/lib/labels';
import { AddSourceDialog } from './AddSourceDialog';
import { CatalogDialog } from './CatalogDialog';
import { EditSourceDialog } from './EditSourceDialog';
import { FirstRun } from './FirstRun';
import { ImportDialog } from './ImportDialog';
import {
  districtOptions,
  hasProblem,
  matchesQuery,
  sortSources,
  SORTS,
  SOURCE_TYPE_ORDER,
  type PlatformFilter,
  type SortKey,
  type TypeFilter,
} from './model';
import { SourceTable } from './SourceTable';
import styles from './sources.module.css';

type DialogState =
  | null
  | { kind: 'add' }
  | { kind: 'catalog' }
  | { kind: 'import' }
  | { kind: 'edit'; source: Source };

export default function SourcesScreen({ params, navKey }: ScreenProps<'sources'>) {
  const { navigate } = useNavigation();
  const toast = useToast();
  const announce = useAnnounce();
  const loaded = useAsync(useCallback(() => api.listSources(), []));
  const { reload } = loaded;
  const [list, setList] = useState<Source[] | null>(null);
  const [dialog, setDialog] = useState<DialogState>(null);
  const [fresh, setFresh] = useState<ReadonlySet<string>>(new Set());
  const [query, setQuery] = useState('');
  const [platform, setPlatform] = useState<PlatformFilter>('all');
  const [type, setType] = useState<TypeFilter>('all');
  const [problemsOnly, setProblemsOnly] = useState(false);
  const [sort, setSort] = useState<SortKey>('name');
  const [rechecking, setRechecking] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  // Данные сервера — основа; локальные правки поверх них до следующей загрузки.
  useEffect(() => {
    if (loaded.data) setList(loaded.data);
  }, [loaded.data]);

  // Повторный заход на экран — свежий список (его могли поменять в другой вкладке).
  const seenNav = useRef(navKey);
  useEffect(() => {
    if (seenNav.current === navKey) return;
    seenNav.current = navKey;
    reload();
  }, [navKey, reload]);

  // Переход с параметром: сразу открыть добавление, каталог или импорт.
  useEffect(() => {
    if (params.focus) setDialog({ kind: params.focus });
  }, [navKey, params.focus]);

  const districts = useMemo(() => districtOptions(list ?? []), [list]);

  const resetFilters = (): void => {
    setQuery('');
    setPlatform('all');
    setType('all');
    setProblemsOnly(false);
  };

  const focusList = (): void => listRef.current?.focus({ preventScroll: true });

  const merge = (added: readonly Source[]): void => {
    if (added.length === 0) return;
    const ids = new Set(added.map((s) => s.id));
    setList((current) => [...(current ?? []).filter((s) => !ids.has(s.id)), ...added]);
    setFresh(ids);
    resetFilters();
  };

  const handleAdded = (source: Source): void => {
    merge([source]);
    toast.show({
      title: `Добавлен источник «${source.name}»`,
      description: 'Он будет участвовать в следующих поисках в режиме «Мои источники».',
      tone: 'good',
    });
    window.setTimeout(focusList, 0);
  };

  const handleSaved = (source: Source): void => {
    setList((current) => (current ?? []).map((s) => (s.id === source.id ? source : s)));
    toast.show({ title: `Сохранено: «${source.name}»`, tone: 'good' });
  };

  const handleCatalogAdded = (added: Source[]): void => {
    merge(added);
    toast.show({
      title:
        added.length > 0
          ? `Добавлено из каталога: ${formatCount(added.length, WORDS.source)}`
          : 'Ничего не добавлено: выбранные источники уже в списке',
      tone: added.length > 0 ? 'good' : 'neutral',
    });
    window.setTimeout(focusList, 0);
  };

  const handleUndone = (ids: string[]): void => {
    const gone = new Set(ids);
    setList((current) => (current ?? []).filter((s) => !gone.has(s.id)));
  };

  const restore = (source: Source): void => {
    api.restoreSource(source.id).then(
      (restored) => {
        setList((current) => [...(current ?? []).filter((s) => s.id !== restored.id), restored]);
        announce(`Источник «${restored.name}» возвращён в список`);
      },
      (error: unknown) =>
        toast.show({
          title: 'Не удалось вернуть источник',
          description: errorMessage(error),
          tone: 'critical',
        }),
    );
  };

  const remove = (source: Source): void => {
    // Сразу убираем из списка; если сервер откажет — вернём.
    setList((current) => (current ?? []).filter((s) => s.id !== source.id));
    focusList();
    api.removeSource(source.id).then(
      () =>
        toast.undo(
          `Удалён источник «${source.name}»`,
          () => restore(source),
          'Уже найденные подборки не изменятся.',
        ),
      (error: unknown) => {
        setList((current) => [...(current ?? []), source]);
        toast.show({
          title: `Не удалось удалить «${source.name}»`,
          description: errorMessage(error),
          tone: 'critical',
        });
      },
    );
  };

  /** «Проверить все» (П9, НТ-17): доступность каждого источника списка заново. */
  const recheckAll = (): void => {
    setRechecking(true);
    api
      .recheckSources()
      .then(
        (report) => {
          setList(report.sources);
          const names = report.problems.map((p) => `«${p.name}»`);
          toast.show({
            title:
              report.problems.length === 0
                ? `Проверено ${formatCount(report.checked, WORDS.source)}: все доступны`
                : `Проверено ${formatCount(report.checked, WORDS.source)}: с замечаниями — ${formatNumber(report.problems.length)}`,
            description:
              names.length > 0
                ? `${names.slice(0, 3).join(', ')}${names.length > 3 ? ` и ещё ${formatNumber(names.length - 3)}` : ''}. Подробности — в строке источника.`
                : undefined,
            tone: report.problems.length === 0 ? 'good' : 'warning',
          });
        },
        (error: unknown) =>
          toast.show({
            title: 'Не удалось проверить список',
            description: errorMessage(error),
            tone: 'critical',
          }),
      )
      .finally(() => setRechecking(false));
  };

  const showExisting = (name: string): void => {
    resetFilters();
    setQuery(name);
  };

  // ------------------------------------------------------------ производные
  const all = list ?? [];
  const filtered = sortSources(
    all.filter(
      (s) =>
        (platform === 'all' || s.platform === platform) &&
        (type === 'all' || s.type === type) &&
        (!problemsOnly || hasProblem(s)) &&
        matchesQuery(s, query, SOURCE_TYPE_LABEL[s.type]),
    ),
    sort,
  );
  const problems = all.filter(hasProblem).length;
  const lastCheck = all.reduce<string | null>(
    (latest, s) =>
      latest === null || Date.parse(s.check.checkedAt) > Date.parse(latest)
        ? s.check.checkedAt
        : latest,
    null,
  );
  const countBy = (p: PlatformId): number => all.filter((s) => s.platform === p).length;
  const typesPresent = SOURCE_TYPE_ORDER.filter((t) => all.some((s) => s.type === t));
  const filtersOn = query.trim() !== '' || platform !== 'all' || type !== 'all' || problemsOnly;

  const actions = (
    <>
      <Button
        variant="primary"
        size="sm"
        iconStart={<Plus />}
        onClick={() => setDialog({ kind: 'add' })}
      >
        Добавить по ссылке
      </Button>
      <Button
        size="sm"
        iconStart={<FileSpreadsheet />}
        onClick={() => setDialog({ kind: 'import' })}
      >
        Из Excel
      </Button>
      <Button size="sm" iconStart={<Library />} onClick={() => setDialog({ kind: 'catalog' })}>
        Каталог края
      </Button>
    </>
  );

  // ------------------------------------------------------------ содержимое
  let content;
  if (list === null && loaded.status === 'error') {
    content = (
      <ErrorState
        title="Не удалось загрузить список источников"
        description={loaded.error?.message}
        kind={loaded.error?.code === 'offline' ? 'offline' : 'error'}
        onRetry={reload}
      />
    );
  } else if (list === null) {
    content = <LoadingList />;
  } else if (all.length === 0) {
    content = (
      <FirstRun
        onCatalog={() => setDialog({ kind: 'catalog' })}
        onAdd={() => setDialog({ kind: 'add' })}
        onImport={() => setDialog({ kind: 'import' })}
        onSearch={() => navigate('search')}
      />
    );
  } else {
    content = (
      <>
        <div className={styles.tiles}>
          <div className={cx(styles.tile, styles.reveal)}>
            <span className={styles.tileLabel}>В списке</span>
            <span className={styles.tileNum}>{formatNumber(all.length)}</span>
            <span className={styles.tileNote}>
              {plural(all.length, WORDS.source)} для режима «Мои источники»
            </span>
          </div>
          <div
            className={cx(styles.tile, styles.tileWide, styles.reveal)}
            style={{ '--i': 1 } as CSSProperties}
          >
            <span className={styles.tileLabel}>По площадкам</span>
            <span className={styles.bar} aria-hidden="true">
              {PLATFORM_ORDER.map((p) => (
                <span key={p} style={{ flexGrow: countBy(p), background: PLATFORMS[p].colorVar }} />
              ))}
            </span>
            <span className={styles.tileNote}>
              {PLATFORM_ORDER.map((p) => `${PLATFORMS[p].name} ${countBy(p)}`).join(' · ')}
            </span>
          </div>
          <div className={cx(styles.tile, styles.reveal)} style={{ '--i': 2 } as CSSProperties}>
            <span className={styles.tileLabel}>Доступны</span>
            <span className={styles.tileNum}>{formatNumber(all.length - problems)}</span>
            {problems > 0 ? (
              <>
                <StatusBadge tone="critical" icon="lock" size="sm">
                  {problems === 1 ? '1 недоступен' : `${formatNumber(problems)} недоступны`}
                </StatusBadge>
                <span className={styles.tileNote}>
                  {problems === 1 ? 'по нему не ищем' : 'по ним не ищем'}
                </span>
              </>
            ) : (
              <span className={styles.tileNote}>все открыты — ищем по каждому</span>
            )}
            {lastCheck && (
              <span className={styles.tileNote}>
                проверено {formatDateTime(lastCheck)}, {TIME_ZONE_LABEL}
              </span>
            )}
            <span>
              <Button
                size="sm"
                variant="link"
                iconStart={<RotateCw />}
                loading={rechecking}
                onClick={recheckAll}
              >
                Проверить все
              </Button>
            </span>
          </div>
        </div>

        <div className={styles.toolbar} role="search" aria-label="Поиск и фильтры по списку">
          <TextField
            label="Найти в списке"
            hideLabel
            type="search"
            placeholder="Название, город, район или ссылка"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className={styles.toolbarRow}>
            <ToggleGroup<PlatformFilter>
              label="Площадка"
              size="sm"
              value={platform}
              onValueChange={setPlatform}
              items={[
                { value: 'all', label: 'Все', count: all.length },
                ...PLATFORM_ORDER.map((p) => ({
                  value: p,
                  label: PLATFORMS[p].short,
                  count: countBy(p),
                })),
              ]}
            />
            <ToggleGroup<SortKey>
              label="Порядок"
              size="sm"
              value={sort}
              onValueChange={setSort}
              items={SORTS}
            />
          </div>
          <div className={styles.filters} role="group" aria-label="Тип источника">
            <Chip size="sm" selected={type === 'all'} onClick={() => setType('all')}>
              Все типы
            </Chip>
            {typesPresent.map((t) => (
              <Chip
                key={t}
                size="sm"
                selected={type === t}
                count={all.filter((s) => s.type === t).length}
                onClick={() => setType(type === t ? 'all' : t)}
              >
                {SOURCE_TYPE_LABEL[t]}
              </Chip>
            ))}
            {problems > 0 && (
              <Chip
                size="sm"
                tone="warning"
                selected={problemsOnly}
                count={problems}
                onClick={() => setProblemsOnly((v) => !v)}
              >
                Недоступные
              </Chip>
            )}
          </div>
        </div>

        <div ref={listRef} tabIndex={-1} className={styles.listRegion}>
          <p className={styles.shown} aria-live="polite">
            <span>
              {filtersOn
                ? `Показано ${formatNumber(filtered.length)} из ${formatCount(all.length, WORDS.source)}`
                : `Показаны все ${formatCount(all.length, WORDS.source)}`}
            </span>
            {filtersOn && (
              <Button size="sm" variant="link" onClick={resetFilters}>
                Сбросить фильтры
              </Button>
            )}
          </p>
          {filtered.length === 0 ? (
            <EmptyState
              compact
              title="Ничего не нашлось"
              description={
                query.trim()
                  ? `В списке нет источников по запросу «${query.trim()}» с выбранными фильтрами.`
                  : 'С выбранными фильтрами в списке ничего нет.'
              }
              actions={
                <>
                  <Button onClick={resetFilters}>Сбросить фильтры</Button>
                  <Button iconStart={<Plus />} onClick={() => setDialog({ kind: 'add' })}>
                    Добавить по ссылке
                  </Button>
                </>
              }
            />
          ) : (
            <SourceTable
              sources={filtered}
              fresh={fresh}
              onEdit={(source) => setDialog({ kind: 'edit', source })}
              onRemove={remove}
            />
          )}
        </div>

        {loaded.status === 'error' && (
          <p className={styles.notice} role="alert">
            Не удалось обновить список: {loaded.error?.message}{' '}
            <Button size="sm" iconStart={<RotateCw />} onClick={reload}>
              Повторить
            </Button>
          </p>
        )}

        <p className={styles.legend}>
          Изменения списка влияют только на следующие поиски — уже найденные подборки не меняются.
          Доступность источников проверяем и перед каждым поиском. Подписчики — по данным площадки:
          это не число читателей, один человек бывает подписан на несколько групп.
        </p>
      </>
    );
  }

  return (
    <Screen
      index="04"
      title="Мои *источники*"
      eyebrow="Источники · режим «Мои источники» · Красноярский край"
      lead="Группы и каналы, по которым ищем в режиме «Мои источники». В режиме «Везде» список не нужен."
      actions={list !== null && all.length === 0 ? undefined : actions}
      className={styles.screen}
    >
      {content}

      <AddSourceDialog
        open={dialog?.kind === 'add'}
        onOpenChange={(open) => setDialog(open ? { kind: 'add' } : null)}
        districts={districts}
        onAdded={handleAdded}
        onShowExisting={showExisting}
      />
      {dialog?.kind === 'edit' && (
        <EditSourceDialog
          key={dialog.source.id}
          source={dialog.source}
          districts={districts}
          onOpenChange={(open) => !open && setDialog(null)}
          onSaved={handleSaved}
        />
      )}
      {dialog?.kind === 'catalog' && (
        <CatalogDialog
          selectAll={all.length === 0}
          onOpenChange={(open) => !open && setDialog(null)}
          onAdded={handleCatalogAdded}
        />
      )}
      {dialog?.kind === 'import' && (
        <ImportDialog
          onOpenChange={(open) => !open && setDialog(null)}
          onImported={merge}
          onUndone={handleUndone}
        />
      )}
    </Screen>
  );
}

function LoadingList() {
  return (
    <div className={styles.loading} role="status">
      <span className="sr-only">Загружаем список источников</span>
      <div className={styles.tiles}>
        {Array.from({ length: 3 }, (_, i) => (
          <Skeleton key={i} height={112} radius="lg" />
        ))}
      </div>
      <Skeleton height={36} radius="pill" />
      {Array.from({ length: 6 }, (_, i) => (
        <Skeleton key={i} height={48} radius="md" />
      ))}
    </div>
  );
}
