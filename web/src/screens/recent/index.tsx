/**
 * П6. Недавние поиски (П12, SC-20) — в стиле «Поиска»: карточки, крупная цифра узким
 * гротеском, условия чипами. Хранятся условия поисков, а не подборки: «Повторить» запускает
 * новый живой поиск, а то, чего не было в прошлый раз, приходит с пометкой «новое»
 * (`SearchRequest.repeatOf` → `ResultItem.isNew`).
 */
import { ArrowRight, Pencil, RotateCw, Search } from 'lucide-react';
import { useCallback, useEffect, useRef, type CSSProperties } from 'react';
import { api, useAsync } from '@/api';
import type { IsoDate, IsoDateTime, Period, RecentSearch } from '@/api/types';
import { useNavigation, type ScreenProps } from '@/app/navigation';
import {
  Button,
  Card,
  CardFooter,
  CardHeader,
  Chip,
  cx,
  EmptyState,
  ErrorState,
  Screen,
  Section,
  Skeleton,
  StatusBadge,
} from '@/components';
import {
  formatDateLong,
  formatNumber,
  formatPeriod,
  formatTime,
  krskParts,
  plural,
  TIME_ZONE_LABEL,
  truncateText,
  WORDS,
} from '@/lib/format';
import { MODE_LABEL, PERIOD_PRESET_LABEL, QUERY_KIND_LABEL } from '@/lib/labels';
import { daysBetween, repeatPeriod } from './period';
import styles from './recent.module.css';

function krskDate(iso: IsoDateTime): IsoDate {
  const p = krskParts(iso);
  const pad = (n: number): string => String(n).padStart(2, '0');
  return `${p.year}-${pad(p.month + 1)}-${pad(p.day)}`;
}

function dayTitle(date: IsoDate, today: IsoDate | null, sample: IsoDateTime): string {
  if (today) {
    const diff = daysBetween(date, today);
    if (diff === 0) return 'Сегодня';
    if (diff === 1) return 'Вчера';
  }
  return formatDateLong(sample);
}

/** «за последние 30 дней: 20 сен – 19 окт» — что будет с периодом при повторе. */
function repeatPeriodText(old: Period, next: Period): string {
  if (old.preset === 'custom') return `за тот же период: ${formatPeriod(next)}`;
  if (next.preset === 'today') return `за сегодня, ${formatPeriod(next)}`;
  return `за последние ${PERIOD_PRESET_LABEL[next.preset].toLowerCase()}: ${formatPeriod(next)}`;
}

export default function RecentScreen({ navKey }: ScreenProps<'recent'>) {
  const { navigate } = useNavigation();
  const recent = useAsync(useCallback(() => api.listRecent(), []));
  // «Сегодня» берём у сервера: период по умолчанию заканчивается сегодняшним днём.
  const start = useAsync(useCallback(() => api.getStartState(), []));
  const today = start.data?.defaultPeriod.to ?? null;
  const { reload } = recent;

  // Повторный заход — свежий список: только что выполненный поиск появится сверху.
  const seenNav = useRef(navKey);
  useEffect(() => {
    if (seenNav.current === navKey) return;
    seenNav.current = navKey;
    reload();
  }, [navKey, reload]);

  const periodFor = (r: RecentSearch): Period =>
    today ? repeatPeriod(r.request.period, today) : r.request.period;

  const repeat = (r: RecentSearch): void => {
    navigate('search', {
      request: { ...r.request, period: periodFor(r), repeatOf: r.searchId },
      autoRun: true,
    });
  };

  const edit = (r: RecentSearch): void => {
    navigate('search', { request: { ...r.request, period: periodFor(r) } });
  };

  let content;
  if (recent.status === 'error' && !recent.data) {
    content = (
      <ErrorState
        title="Не удалось загрузить недавние поиски"
        description={recent.error?.message}
        kind={recent.error?.code === 'offline' ? 'offline' : 'error'}
        onRetry={reload}
      />
    );
  } else if (!recent.data) {
    content = (
      <div className={styles.list} role="status">
        <span className="sr-only">Загружаем недавние поиски</span>
        {Array.from({ length: 3 }, (_, i) => (
          <Card key={i} className={styles.card}>
            <Skeleton width="30%" height={12} />
            <Skeleton width="70%" height={20} />
            <Skeleton width="85%" height={12} />
            <Skeleton width={140} height={32} radius="pill" />
          </Card>
        ))}
      </div>
    );
  } else if (recent.data.length === 0) {
    content = (
      <EmptyState
        variant="start"
        title="Здесь появятся ваши поиски"
        description="После первого поиска его условия сохранятся здесь. Повторить поиск можно будет одной кнопкой — новое с прошлого раза будет помечено."
        actions={
          <Button variant="primary" iconStart={<Search />} onClick={() => navigate('search')}>
            Перейти к поиску
          </Button>
        }
      />
    );
  } else {
    // Группы по дням: «Сегодня», «Вчера», «16 октября 2026».
    const groups: { date: IsoDate; title: string; items: RecentSearch[] }[] = [];
    for (const r of recent.data) {
      const date = krskDate(r.conditions.startedAt);
      const last = groups[groups.length - 1];
      if (last && last.date === date) last.items.push(r);
      else groups.push({ date, title: dayTitle(date, today, r.conditions.startedAt), items: [r] });
    }
    let index = 0;
    content = (
      <div className={styles.days}>
        {groups.map((g) => (
          <Section key={g.date} id={`recent-day-${g.date}`} title={g.title}>
            <ul className={styles.list}>
              {g.items.map((r) => {
                index += 1;
                return (
                  <li
                    key={r.searchId}
                    className={styles.reveal}
                    style={{ '--i': Math.min(index - 1, 8) } as CSSProperties}
                  >
                    <RecentCard
                      item={r}
                      next={today ? periodFor(r) : null}
                      onRepeat={() => repeat(r)}
                      onEdit={() => edit(r)}
                    />
                  </li>
                );
              })}
            </ul>
          </Section>
        ))}
      </div>
    );
  }

  return (
    <Screen
      title="Недавние поиски"
      eyebrow="Условия поисков, а не подборки"
      lead="«Повторить» ищет заново прямо сейчас: появятся свежие публикации, удалённые пропадут. То, чего не было в прошлый раз, будет помечено «новое»."
      width="narrow"
      className={styles.screen}
    >
      {content}
      {recent.data && recent.data.length > 0 && (
        <p className={styles.legend}>
          Ваши поиски не видны другим пользователям. Указано {TIME_ZONE_LABEL}.
        </p>
      )}
    </Screen>
  );
}

function RecentCard({
  item,
  next,
  onRepeat,
  onEdit,
}: {
  item: RecentSearch;
  next: Period | null;
  onRepeat: () => void;
  onEdit: () => void;
}) {
  const c = item.conditions;
  const titleId = `recent-${item.searchId}`;
  const hintId = `recent-hint-${item.searchId}`;
  // «Ничего не нашли» — только если площадки ответили; остановленный поиск так не называем.
  const nothing = item.total === 0 && /ничего не найдено/u.test(item.statusSummary);
  const short = truncateText(c.label, 60);
  return (
    <Card as="article" className={styles.card} aria-labelledby={titleId}>
      <CardHeader aside={<span className={styles.when}>в {formatTime(c.startedAt)}</span>}>
        <span className={styles.kindLine}>
          <span className={styles.kind}>{QUERY_KIND_LABEL[c.kind]}</span>
          {c.meaningLabel && <span>значение: {c.meaningLabel}</span>}
          {c.repeatOf && <span className={styles.mark}>повтор</span>}
        </span>
      </CardHeader>

      <h3 id={titleId} className={styles.headline}>
        «{truncateText(c.label, 90)}»
      </h3>

      {c.kind === 'news-text' && c.text !== c.label && (
        <details className={styles.fullText}>
          <summary>Текст новости целиком</summary>
          <p>{truncateText(c.text, 700)}</p>
        </details>
      )}

      <ul className={styles.conditions} aria-label="Условия поиска">
        <li>
          <Chip size="sm">
            Период: <strong>{formatPeriod(c.period)}</strong>
          </Chip>
        </li>
        <li>
          <Chip size="sm">
            <strong>
              {c.mode === 'my-sources' && c.sourceCount !== null
                ? `${MODE_LABEL[c.mode]} · ${formatNumber(c.sourceCount)}`
                : MODE_LABEL[c.mode]}
            </strong>
          </Chip>
        </li>
        <li>
          <Chip size="sm">
            <strong>{c.region.name}</strong>
          </Chip>
        </li>
      </ul>

      <div className={styles.outcome}>
        {nothing ? (
          <StatusBadge tone="neutral" icon="nothing" size="sm">
            тогда ничего не нашли
          </StatusBadge>
        ) : (
          <p className={styles.found}>
            <span className={styles.foundNum}>{formatNumber(item.total)}</span>
            <span className={styles.foundLabel}>
              {plural(item.total, WORDS.publication)} тогда
              <span className={styles.platforms}>{item.statusSummary}</span>
            </span>
          </p>
        )}
        {c.repeatOf && <NewSince searchId={item.searchId} />}
      </div>

      <CardFooter className={cx(styles.footer)}>
        <Button
          variant="primary"
          size="sm"
          iconStart={<RotateCw />}
          onClick={onRepeat}
          aria-describedby={hintId}
        >
          Повторить<span className="sr-only"> поиск «{short}»</span>
        </Button>
        <Button variant="ghost" size="sm" iconStart={<Pencil />} onClick={onEdit}>
          Изменить условия<span className="sr-only"> поиска «{short}»</span>
        </Button>
        <span id={hintId} className={styles.repeatHint}>
          <ArrowRight aria-hidden="true" />
          Новый поиск{next ? ` ${repeatPeriodText(item.request.period, next)}` : ''}
        </span>
      </CardFooter>
    </Card>
  );
}

/** «Новых с прошлого раза: 5» — для повторённого поиска (П12). */
function NewSince({ searchId }: { searchId: string }) {
  const selection = useAsync(useCallback(() => api.getSelection(searchId), [searchId]));
  if (!selection.data) return null;
  const n = selection.data.counts.new;
  return n > 0 ? (
    <StatusBadge tone="info" icon="info" size="sm">
      новых с прошлого раза: {formatNumber(n)}
    </StatusBadge>
  ) : (
    <StatusBadge tone="neutral" icon="nothing" size="sm">
      нового с прошлого раза нет
    </StatusBadge>
  );
}
