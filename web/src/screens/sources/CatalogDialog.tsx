/**
 * Готовый каталог краевых источников (НТ-14, SC-30): отметить нужные и добавить одним
 * действием. При первом запуске отмечено всё. Данные — `api.getCatalog`, `api.addFromCatalog`.
 */
import { Library } from 'lucide-react';
import { useCallback, useMemo, useState } from 'react';
import { api, errorMessage, useAsync } from '@/api';
import type { CatalogSource, PlatformId, Source } from '@/api/types';
import {
  Button,
  Dialog,
  DialogClose,
  ErrorState,
  PlatformDot,
  SkeletonText,
  TextField,
  ToggleGroup,
} from '@/components';
import { formatCount, formatNumber, WORDS } from '@/lib/format';
import { PLATFORM_ORDER, PLATFORMS, SOURCE_TYPE_LABEL } from '@/lib/labels';
import { matchesQuery, subscribersText, type PlatformFilter } from './model';
import styles from './sources.module.css';

export interface CatalogDialogProps {
  onOpenChange: (open: boolean) => void;
  /** Первый запуск: отметить всё сразу */
  selectAll: boolean;
  onAdded: (sources: Source[]) => void;
}

export function CatalogDialog({ onOpenChange, selectAll, onAdded }: CatalogDialogProps) {
  const catalog = useAsync(useCallback(() => api.getCatalog(), []));
  const [picked, setPicked] = useState<Set<string> | null>(null);
  const [query, setQuery] = useState('');
  const [platform, setPlatform] = useState<PlatformFilter>('all');
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const all = useMemo(() => catalog.data ?? [], [catalog.data]);
  const available = useMemo(() => all.filter((c) => !c.inMySources), [all]);
  // Выбор по умолчанию: при первом запуске — все доступные, иначе — ничего.
  const selected = useMemo(
    () => picked ?? new Set(selectAll ? available.map((c) => c.id) : []),
    [picked, selectAll, available],
  );

  const shown = useMemo(
    () =>
      all.filter(
        (c) =>
          (platform === 'all' || c.platform === platform) &&
          matchesQuery(c, query, SOURCE_TYPE_LABEL[c.type]),
      ),
    [all, platform, query],
  );
  const shownAvailable = shown.filter((c) => !c.inMySources);
  const allShownPicked =
    shownAvailable.length > 0 && shownAvailable.every((c) => selected.has(c.id));

  const toggle = (id: string): void => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setPicked(next);
  };

  const toggleShown = (): void => {
    const next = new Set(selected);
    for (const c of shownAvailable) {
      if (allShownPicked) next.delete(c.id);
      else next.add(c.id);
    }
    setPicked(next);
  };

  const add = async (): Promise<void> => {
    setAdding(true);
    setError(null);
    try {
      const added = await api.addFromCatalog([...selected]);
      onAdded(added);
      onOpenChange(false);
    } catch (e) {
      setError(errorMessage(e));
      setAdding(false);
    }
  };

  const byPlatform = (p: PlatformId): number => all.filter((c) => c.platform === p).length;

  return (
    <Dialog
      open
      onOpenChange={onOpenChange}
      size="lg"
      title="Каталог краевых источников"
      description="Группы и каналы, которые мы собрали заранее: краевые и районные СМИ, органы власти, администрации, сообщества городов и районов. Отмеченные добавятся к вашему списку."
      footer={
        <>
          <span className={styles.footerNote} aria-live="polite">
            Выбрано {formatNumber(selected.size)} из {formatNumber(available.length)}
          </span>
          <DialogClose>
            <Button>Отмена</Button>
          </DialogClose>
          <Button
            variant="primary"
            iconStart={<Library />}
            disabled={selected.size === 0}
            loading={adding}
            onClick={() => void add()}
          >
            {selected.size > 0
              ? `Добавить ${formatCount(selected.size, WORDS.source)}`
              : 'Добавить'}
          </Button>
        </>
      }
    >
      <div className={styles.dialogStack}>
        {catalog.status === 'loading' && !catalog.data && (
          <div role="status">
            <span className="sr-only">Загружаем каталог</span>
            <SkeletonText lines={6} />
          </div>
        )}
        {catalog.status === 'error' && !catalog.data && (
          <ErrorState
            compact
            title="Не удалось загрузить каталог"
            description={catalog.error?.message}
            kind={catalog.error?.code === 'offline' ? 'offline' : 'error'}
            onRetry={catalog.reload}
          />
        )}
        {catalog.data && (
          <>
            <div className={styles.toolbar}>
              <TextField
                label="Найти в каталоге"
                hideLabel
                type="search"
                placeholder="Название, город или район"
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
                      count: byPlatform(p),
                    })),
                  ]}
                />
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={toggleShown}
                  disabled={shownAvailable.length === 0}
                >
                  {allShownPicked ? 'Снять отметки с показанных' : 'Отметить все показанные'}
                </Button>
              </div>
            </div>
            {shown.length === 0 ? (
              <p className={styles.muted}>В каталоге ничего не нашлось по «{query.trim()}».</p>
            ) : (
              <ul className={styles.catalogList} aria-label="Источники каталога">
                {shown.map((c) => (
                  <CatalogRow
                    key={c.id}
                    source={c}
                    checked={c.inMySources || selected.has(c.id)}
                    onToggle={() => toggle(c.id)}
                  />
                ))}
              </ul>
            )}
            {error && (
              <p className={styles.errorText} role="alert">
                {error}
              </p>
            )}
          </>
        )}
      </div>
    </Dialog>
  );
}

function CatalogRow({
  source,
  checked,
  onToggle,
}: {
  source: CatalogSource;
  checked: boolean;
  onToggle: () => void;
}) {
  const id = `catalog-${source.id}`;
  return (
    <li className={styles.catalogItem}>
      <input
        id={id}
        type="checkbox"
        className={styles.checkbox}
        checked={checked}
        disabled={source.inMySources}
        onChange={onToggle}
      />
      <label htmlFor={id} className={styles.catalogLabel}>
        <span className={styles.source}>
          <PlatformDot platform={source.platform} size="sm" />
          <span>
            {source.name}
            <span className={styles.sourcePlatform}> · {PLATFORMS[source.platform].short}</span>
            {source.inMySources && (
              <>
                {' '}
                <span className={styles.mark}>уже в списке</span>
              </>
            )}
          </span>
        </span>
        <span className={styles.catalogFacts}>
          {SOURCE_TYPE_LABEL[source.type]} · {source.district ?? 'район не указан'} ·{' '}
          {subscribersText(source.subscribers)}
        </span>
        <span className={styles.catalogDesc}>{source.description}</span>
      </label>
    </li>
  );
}
