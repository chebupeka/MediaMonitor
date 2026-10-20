/**
 * Экран «Распространение» (П4, Р10): куда и как широко разошлась новость.
 *
 * Отвечает на вопрос заказчика «как широко расходится релиз». Как раздел «Распространение»
 * сайта: слева заголовок, новость, первоисточник и цифры, справа — крупная вспышка точек из
 * источника, по опоре на каждое размещение (в боковой панели — во всю ширину под заголовком).
 * Сцена одна на все состояния: идёт поиск — облака площадок, готово — вспышка, формы
 * перетекают друг в друга. Дальше, во всю ширину, — кто опубликовал первым и
 * насколько точно время (П4); размещения по площадкам и типам; аудитория источников и
 * просмотры отдельными цифрами с «как посчитано» (П5, НТ-24); как расходилась новость
 * по времени (П6); какие абзацы релиза взяли (П1); таблица размещений с сортировкой.
 * Набросок: docs/visuals/rasprostranenie.png. Данные: `api.getSpread(searchId, groupId)`.
 */
import { ExternalLink, FileSpreadsheet, Info } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { IS_MOCKUP, api, demoQueries, errorMessage, useSearchRun } from '@/api';
import type { SpreadPlacement, SpreadReport } from '@/api/types';
import { useNavigation, type ScreenProps } from '@/app/navigation';
import { useShell } from '@/app/shell-state';
import {
  Button,
  ErrorState,
  PlatformDot,
  Screen,
  Section,
  SkeletonText,
  ToggleGroup,
} from '@/components';
import { DotsStage, type DotsForm } from '@/dots';
import { SELECTION_FEATURES } from '@/lib/build';
import {
  WORDS,
  formatCompact,
  formatCount,
  formatDateTime,
  formatPublishedAt,
  formatShare,
  plural,
} from '@/lib/format';
import {
  DEMO_POST_NOTE,
  PLACEMENT_TYPE_LABEL,
  PLATFORMS,
  PLATFORM_ORDER,
  TIME_RELIABILITY_LABEL,
} from '@/lib/labels';
import { AI_DISCLAIMER } from '@/lib/ai-check';
import { AiDots, AiMark } from '@/screens/ai-check/AiMark';
import { ExportDialog } from '@/screens/search/ExportDialog';
import { loadSavedSearch } from '@/screens/search/saved';
import { Timeline } from './Timeline';
import styles from './spread.module.css';

type Sort = 'time' | 'popular';

const SORTS: { value: Sort; label: string }[] = [
  { value: 'time', label: 'По времени' },
  { value: 'popular', label: 'По популярности' },
];

/** Формы после «из N»: «из 1 размещения», «из 15 размещений» */
const OF_PLACEMENTS = ['размещения', 'размещений', 'размещений'] as const;
const OF_RETOLD = ['пересказа', 'пересказов', 'пересказов'] as const;
const OF_SOURCES = ['источника', 'источников', 'источников'] as const;

/** Популярность — просмотры поста; без данных — в конце, между собой по подписчикам. */
function byPopularity(a: SpreadPlacement, b: SpreadPlacement): number {
  if (a.views !== b.views) return (b.views ?? -1) - (a.views ?? -1);
  return (b.subscribers ?? -1) - (a.subscribers ?? -1);
}

function byTime(a: SpreadPlacement, b: SpreadPlacement): number {
  return (a.publishedAt ?? '9').localeCompare(b.publishedAt ?? '9');
}

function typeLabel(p: SpreadPlacement): string {
  if (p.isOriginal) return 'Исходный';
  const label = PLACEMENT_TYPE_LABEL[p.placementType];
  return label.charAt(0).toUpperCase() + label.slice(1);
}

export default function SpreadScreen({ params, navKey }: ScreenProps<'spread'>) {
  const { navigate } = useNavigation();
  const { layout } = useShell();
  const { state, start } = useSearchRun();
  const [report, setReport] = useState<SpreadReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSort] = useState<Sort>('time');
  const [exportOpen, setExportOpen] = useState(false);

  const load = useCallback((searchId: string, groupId?: string, quiet = false) => {
    setError(null);
    setLoading(true);
    api
      .getSpread(searchId, groupId)
      .then(setReport, (e: unknown) => {
        if (!quiet) setError(errorMessage(e));
      })
      .finally(() => setLoading(false));
  }, []);

  const runText = useCallback(
    (text: string) => {
      setReport(null);
      setError(null);
      start(
        {
          text,
          period: { preset: '7d', from: '2026-10-13', to: '2026-10-19' },
          mode: 'everywhere',
        },
        { replace: true },
      );
    },
    [start],
  );

  // Переход из подборки — по id поиска; из расширения — по тексту новости. Без параметров
  // пробуем последний поиск (панель открыли заново): если он был по тексту новости — покажем.
  useEffect(() => {
    if (params.searchId) load(params.searchId, params.groupId);
    else if (params.text) runText(params.text);
    else if (!report)
      void loadSavedSearch().then((saved) => {
        if (saved?.searchId) load(saved.searchId, undefined, true);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- реагируем только на новый переход
  }, [navKey]);

  useEffect(() => {
    if (state.phase === 'done' && state.searchId) load(state.searchId);
  }, [state.phase, state.searchId, load]);

  const placements = useMemo(
    () => (report ? [...report.placements].sort(sort === 'time' ? byTime : byPopularity) : []),
    [report, sort],
  );
  const chronological = useMemo(
    () => (report ? [...report.placements].sort(byTime).map((p) => p.platform) : []),
    [report],
  );

  // Пример релиза — только на демо-данных: на сервере такой новости нет
  const releaseText = IS_MOCKUP ? (demoQueries.find((q) => q.id === 'release')?.text ?? '') : '';
  const searching = state.phase === 'running' || state.phase === 'queued';
  // Не удался поиск по тексту новости (лимит, слишком длинный текст) — причина видна тоже
  const problem = error ?? (state.phase === 'failed' ? (state.error?.message ?? null) : null);
  const failed = !report && !searching && !loading && problem !== null;

  // Сцена — одна на все состояния: формы перетекают друг в друга
  const form: DotsForm = report ? 'spread' : searching ? 'searching' : failed ? 'failure' : 'krai';
  const caption = report
    ? `${formatCount(report.totals.placements, WORDS.placement)}: ${platformSummary(report)}. Ближе к центру — опубликованные раньше.`
    : searching
      ? `Ищем размещения новости… найдено ${state.counts?.total ?? 0}`
      : failed
        ? 'Распространение не посчитать.'
        : 'Красноярский край: ВКонтакте, Одноклассники и MAX.';

  return (
    <Screen
      index="02"
      eyebrow="Распространение · по тексту новости"
      title="Как *разошлась* новость"
      className={styles.screen}
      sceneMode="hero"
      scene={
        <DotsStage
          form={form}
          intensity="calm"
          placements={report ? chronological : undefined}
          // В панели вспышка вписывается по ширине — крупнее, до краёв, как на сайте в телефоне
          zoom={layout === 'panel' && report ? 1.3 : 1}
          caption={caption}
          live={searching}
        />
      }
      intro={
        <>
          {!report && searching && (
            <p className={styles.lead}>
              Ищем, где вышла новость: во ВКонтакте, Одноклассниках и MAX. Когда поиск закончится,
              здесь появятся первоисточник, все размещения и как широко разошлась новость.
            </p>
          )}

          {!report && !searching && loading && <SkeletonText lines={6} />}

          {failed && (
            <ErrorState
              compact
              title="Распространение не посчитать"
              description={problem}
              actions={
                <Button variant="secondary" onClick={() => navigate('search')}>
                  К поиску
                </Button>
              }
            />
          )}

          {!report && !searching && !loading && !problem && (
            <div className={styles.start}>
              <p className={styles.lead}>
                <b>Распространение считается по тексту новости.</b>{' '}
                {SELECTION_FEATURES
                  ? 'Вставьте текст релиза в поиск или выделите его на сайте СМИ и нажмите «Найти, где это опубликовано».'
                  : 'Вставьте текст релиза в поиск.'}{' '}
                Когда поиск закончится, нажмите «Распространение» в строке состояния.
              </p>
              <div className={styles.startActions}>
                {releaseText && (
                  <Button variant="primary" size="lg" onClick={() => runText(releaseText)}>
                    Показать на примере релиза
                  </Button>
                )}
                <Button
                  variant={releaseText ? 'link' : 'secondary'}
                  size={releaseText ? 'md' : 'lg'}
                  onClick={() => navigate('search')}
                >
                  К поиску
                </Button>
              </div>
            </div>
          )}

          {report && (
            <>
              <header className={styles.news}>
                <h2 className={styles.newsTitle}>{report.title}</h2>
                <Origin report={report} />
              </header>
              <Totals report={report} />
            </>
          )}
        </>
      }
      actions={
        report ? (
          <>
            <Button variant="secondary" size="sm" onClick={() => navigate('search')}>
              К подборке
            </Button>
            <Button
              variant="secondary"
              size="sm"
              iconStart={<FileSpreadsheet />}
              onClick={() => setExportOpen(true)}
            >
              XLSX
            </Button>
          </>
        ) : undefined
      }
    >
      {report && (
        <>
          <Section title="Как *расходилась* новость">
            <Timeline placements={report.placements} hourly={report.wave.hourly} />
          </Section>

          <Section
            title="Что *взяли* из релиза"
            aside={<span className={styles.aside}>Ярче — абзац перепечатали чаще</span>}
          >
            <Fragments report={report} />
          </Section>

          <Section
            title="Все *размещения*"
            aside={
              <ToggleGroup
                label="Сортировка"
                items={SORTS}
                value={sort}
                onValueChange={setSort}
                size="sm"
              />
            }
          >
            <PlacementsTable placements={placements} />
          </Section>

          <p className={styles.legend}>
            «Дословно» — текст совпадает с релизом. «Сокращено» — часть текста релиза. «Пересказ» —
            та же новость своими словами: совпадают место, дата и участники. Если площадка не отдаёт
            цифру, пишем «нет данных» и не подставляем оценку.
            {report.aiRetold && report.aiRetold.retold > 0
              ? ` «Похоже на ИИ» — ${AI_DISCLAIMER.toLowerCase()}; проверяем только пересказы.`
              : ''}{' '}
            Данные на {formatDateTime(report.computedAt)}.
          </p>

          <ExportDialog searchId={report.searchId} open={exportOpen} onOpenChange={setExportOpen} />
        </>
      )}
    </Screen>
  );
}

function platformSummary(report: SpreadReport): string {
  return PLATFORM_ORDER.map((id) => `${PLATFORMS[id].short} ${report.totals.byPlatform[id]}`).join(
    ', ',
  );
}

/** «Первым опубликовал» с надёжностью времени (П4) */
function Origin({ report }: { report: SpreadReport }) {
  const { original } = report;
  const reliability = TIME_RELIABILITY_LABEL[original.timeReliability];
  return (
    <div className={styles.origin}>
      <p className={styles.originLine}>
        Первым опубликовал: <b>{original.sourceName}</b>
        <span className={styles.originPlatform}>
          <PlatformDot platform={original.platform} size="sm" />
          {PLATFORMS[original.platform].name}
        </span>
        <span className={styles.originTime}>
          {formatPublishedAt(original)}
          {reliability && original.timeReliability !== 'unknown' ? ` · ${reliability}` : ''}
        </span>
      </p>
      {original.notes.length > 0 && (
        <ul className={styles.notes}>
          {original.notes.map((n) => (
            <li key={n.code}>
              <Info aria-hidden="true" />
              {n.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Размещения, площадки, аудитория и просмотры — отдельными цифрами (П5) */
function Totals({ report }: { report: SpreadReport }) {
  const { totals, audience, views } = report;
  const types = (['verbatim', 'shortened', 'retold', 'repost'] as const)
    .filter((t) => totals.byType[t] > 0)
    .map((t) => `${PLACEMENT_TYPE_LABEL[t]} ${totals.byType[t]}`)
    .join(' · ');
  return (
    <div className={styles.tiles}>
      <div className={styles.tile}>
        <span className={styles.tileLabel}>Размещений</span>
        <span className={styles.tileNum}>{totals.placements}</span>
        <span className={styles.tileNote}>включая исходный{types ? ` · ${types}` : ''}</span>
        {report.aiRetold && report.aiRetold.retold > 0 && (
          <span className={styles.tileAi}>
            <AiDots level="likely-ai" />
            <span>
              похожи на ИИ: {report.aiRetold.likelyAi} из {report.aiRetold.retold}{' '}
              {plural(report.aiRetold.retold, OF_RETOLD)}
            </span>
          </span>
        )}
      </div>
      <div className={styles.tile}>
        <span className={styles.tileLabel}>По площадкам</span>
        <span className={styles.bar} aria-hidden="true">
          {PLATFORM_ORDER.map((id) => (
            <span
              key={id}
              style={{ flexGrow: totals.byPlatform[id], background: PLATFORMS[id].colorVar }}
            />
          ))}
        </span>
        <span className={styles.tileNote}>
          {PLATFORM_ORDER.map((id) => `${PLATFORMS[id].name} ${totals.byPlatform[id]}`).join(' · ')}
        </span>
      </div>
      <Reach label="Аудитория источников" metric={audience} of={OF_SOURCES} />
      <Reach label="Просмотры" metric={views} of={OF_PLACEMENTS} />
    </div>
  );
}

function Reach({
  label,
  metric,
  of,
}: {
  label: string;
  metric: SpreadReport['views'];
  of: readonly [string, string, string];
}) {
  return (
    <div className={styles.tile}>
      <span className={styles.tileLabel}>{label}</span>
      <span className={styles.tileNum}>{formatCompact(metric.value)}</span>
      <span className={styles.tileNote}>
        {metric.withData < metric.of
          ? `По ${metric.withData} из ${metric.of} ${plural(metric.of, of)}. `
          : ''}
        {metric.howCounted}
      </span>
    </div>
  );
}

/** Карта фрагментов релиза (П1): какие абзацы взяли и сколько раз */
function Fragments({ report }: { report: SpreadReport }) {
  const copies = Math.max(report.totals.placements - 1, 1);
  return (
    <ol className={styles.fragments}>
      {report.release.fragments.map((f) => (
        <li
          key={f.id}
          className={styles.fragment}
          style={{ ['--share' as string]: String(f.takenBy / copies) }}
        >
          <p>{f.text}</p>
          <span className={styles.fragmentCount}>
            {f.takenBy === 0
              ? 'дословно не взял никто'
              : `взяли ${f.takenBy} из ${copies} ${plural(copies, OF_PLACEMENTS)}`}
          </span>
        </li>
      ))}
    </ol>
  );
}

/** Таблица размещений; в узкой панели строки становятся карточками */
function PlacementsTable({ placements }: { placements: readonly SpreadPlacement[] }) {
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th scope="col">Когда</th>
            <th scope="col">Источник</th>
            <th scope="col" className={styles.num}>
              Подписчики
            </th>
            <th scope="col" className={styles.num}>
              Просмотры
            </th>
            <th scope="col">Как опубликовали</th>
            <th scope="col">
              <span className="sr-only">Пост</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {placements.map((p) => (
            <tr key={p.itemId} className={p.isOriginal ? styles.rowOriginal : undefined}>
              <td data-label="Когда">{formatPublishedAt(p)}</td>
              <td data-label="Источник">
                <span className={styles.source}>
                  <PlatformDot platform={p.platform} size="sm" />
                  <span>
                    {p.sourceName}
                    <span className={styles.sourcePlatform}> · {PLATFORMS[p.platform].short}</span>
                  </span>
                </span>
              </td>
              <td data-label="Подписчики" className={styles.num}>
                <Metric value={p.subscribers} />
              </td>
              <td data-label="Просмотры" className={styles.num}>
                <Metric value={p.views} />
              </td>
              <td data-label="Как опубликовали">
                <span className={p.isOriginal ? styles.typeOriginal : styles.type}>
                  {typeLabel(p)}
                </span>
                {!p.isOriginal && p.citationShare > 0 && (
                  <span className={styles.share}>{formatShare(p.citationShare)} текста релиза</span>
                )}
                {/* Проверка на ИИ — только у пересказов: копия получает оценку релиза */}
                {!p.isOriginal && p.placementType === 'retold' && (
                  <AiMark check={p.aiCheck} className={styles.aiMark} />
                )}
              </td>
              <td className={styles.openCell}>
                {p.demo ? (
                  // Записанный пример: поста на площадке нет — ссылку не показываем (Р11 п. 3)
                  <span className={styles.demoPost}>{DEMO_POST_NOTE}</span>
                ) : (
                  <a className={styles.open} href={p.url} target="_blank" rel="noopener noreferrer">
                    Открыть пост
                    <ExternalLink aria-hidden="true" />
                  </a>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Metric({ value }: { value: number | null }) {
  return value === null ? (
    <span className={styles.noData}>нет данных</span>
  ) : (
    <>{formatCompact(value)}</>
  );
}
