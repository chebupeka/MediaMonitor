/**
 * Имитация сервера: реализация MonitorApi на демо-данных — ТОЛЬКО ДЛЯ МОКАПА.
 * Задержки реалистичные, сбои — по выбранному демо-сценарию (scenario.ts).
 */
import { MonitorApiError, type MonitorApi } from '../client';
import type {
  AiCheck,
  ApiError,
  CatalogSource,
  ExportCell,
  ExportFile,
  ExportOptions,
  ExportPreview,
  ImportPreview,
  ImportReport,
  ImportRow,
  LinkRecheckReport,
  OriginNote,
  PlatformId,
  QueryAnalysis,
  RecentSearch,
  ResultItem,
  SearchConditions,
  SearchRequest,
  SearchRun,
  Selection,
  SelectionCounts,
  Source,
  SourceCheck,
  SourceInput,
  SourceType,
  SourcesRecheckReport,
  SpreadPlacement,
  SpreadReport,
  StandStatus,
  StartState,
  TopicCorrection,
  TopicUnderstanding,
  WavePoint,
  Workspace,
  WorkspaceLink,
} from '../types';
import {
  TIME_ZONE_LABEL_FULL,
  formatDateTime,
  formatPeriod,
  formatPublishedAt,
  truncateText,
} from '@/lib/format';
import {
  DEMO_POST_NOTE,
  METHOD_LABEL,
  MODE_LABEL,
  PLACEMENT_TYPE_LABEL,
  PLATFORMS,
  PLATFORM_ORDER,
  QUERY_KIND_LABEL,
  RELEVANCE_LABEL,
  RELEVANCE_ORDER,
  platformStatusView,
  regionReasonText,
} from '@/lib/labels';
import { getHost } from '@/lib/host';
import { buildXlsx } from '@/lib/xlsx';
import { demoAiCheck } from './ai';
import { validateItems } from './build';
import { at, demoNowMs, nowIso, toKrskIso } from './clock';
import {
  dropConnectionFor,
  getConnection,
  onConnectionChange,
  restoreConnection,
} from './connection';
import { buildBdd } from './datasets/bdd';
import { buildEvent } from './datasets/event';
import { buildLarge } from './datasets/large';
import { RELEASE_AI_SAMPLES, RELEASE_SOURCE_TEXT, buildRelease } from './datasets/release';
import {
  adoptRecord,
  attachFakeSearch,
  computeCounts,
  emptyByPlatform,
  getRecord,
  retryFakePlatform,
  snapshot,
  startFakeSearch,
  stopById,
  withAiCheck,
  type SearchContext,
  type SearchRecord,
} from './engine';
import { analyze, presetPeriod, topicFor } from './query';
import { getDemoState, subscribeDemo } from './scenario';
import {
  SITE_DOMAINS,
  SOURCE_SEEDS,
  catalogSources,
  platformInfo,
  platformVia,
  postOwner,
  seedById,
  sourceUrl,
  toSourceRef,
  type SourceSeed,
} from './sources';

// ---------------------------------------------------------------- служебное

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Реалистичная задержка; в сценарии «Медленно» — втрое дольше. */
async function delay(base: number): Promise<void> {
  const k = getDemoState().scenario === 'slow' ? 3 : 1;
  await sleep(Math.round((base + Math.random() * base * 0.4) * k));
}

function apiError(code: ApiError['code'], message: string): MonitorApiError {
  return new MonitorApiError(code, message);
}

/** Каждый обычный вызов при обрыве связи отвечает «нет связи» (НТ-23). */
async function call<T>(base: number, body: () => T): Promise<T> {
  if (getConnection() === 'offline') {
    await sleep(400);
    throw apiError(
      'offline',
      'Нет связи с интернетом. Проверьте подключение — данные на сервере не потеряются.',
    );
  }
  await delay(base);
  if (getConnection() === 'offline') {
    throw apiError('offline', 'Связь пропала во время запроса. Повторите, когда она вернётся.');
  }
  return body();
}

const clone = <T>(value: T): T => structuredClone(value);

// ---------------------------------------------------------------- источники

/** «Источник доступен» — своими словами для каждой площадки. */
const OK_MESSAGE: Record<PlatformId, string> = {
  vk: 'Источник доступен: открытая группа, посты читаются.',
  ok: 'Источник доступен: открытая группа, посты читаются.',
  max: 'Источник доступен: открытая группа, посты читаются.',
  site: 'Сайт доступен: статьи читаются из ленты RSS или раздела новостей.',
  dzen: 'Канал доступен: публикации читаются со страницы канала.',
};

function checkOk(platform: PlatformId): Omit<SourceCheck, 'checkedAt'> {
  return { state: 'ok', message: OK_MESSAGE[platform], preview: null };
}

function sourceFromSeed(seed: SourceSeed, origin: Source['origin'], addedAt: string): Source {
  return {
    ...toSourceRef(seed, true),
    origin,
    addedAt,
    check: seed.closed
      ? {
          state: 'closed',
          message: 'Группа закрыта: её посты не видны, поиск по ней невозможен.',
          preview: null,
          checkedAt: at('2026-10-19 08:00'),
        }
      : { ...checkOk(seed.platform), checkedAt: at('2026-10-19 08:00') },
  };
}

function defaultSources(): Map<string, Source> {
  const list = SOURCE_SEEDS.filter((s) => s.mine).map((seed, i) =>
    sourceFromSeed(
      seed,
      i % 3 === 0 ? 'manual' : 'catalog',
      at(`2026-0${(i % 3) + 7}-1${i % 9} 10:00`),
    ),
  );
  return new Map(list.map((s) => [s.id, s]));
}

let mySources: Map<string, Source> =
  getDemoState().scenario === 'first-run' ? new Map<string, Source>() : defaultSources();
const trash = new Map<string, Source>();
let manualCounter = 0;

function myIds(): Set<string> {
  return new Set(mySources.keys());
}

function myNamesByPlatform(): Record<PlatformId, string[]> {
  const result: Record<PlatformId, string[]> = { vk: [], ok: [], max: [], site: [], dzen: [] };
  for (const s of mySources.values()) result[s.platform].push(s.name);
  return result;
}

interface ParsedUrl {
  platform: PlatformId | null;
  normalized: string;
  slug: string;
}

/** Площадка по адресу. Сайт — только из каталога СМИ края; прочие сайты не поддерживаются. */
function platformOf(normalized: string): PlatformId | null {
  if (normalized.startsWith('vk.com/')) return 'vk';
  if (normalized.startsWith('ok.ru/')) return 'ok';
  if (normalized.startsWith('max.ru/')) return 'max';
  if (normalized.startsWith('dzen.ru/')) return 'dzen';
  const host = normalized.split('/')[0] ?? '';
  return SITE_DOMAINS.includes(host) ? 'site' : null;
}

function parseUrl(raw: string): ParsedUrl {
  const normalized = raw
    .trim()
    .toLowerCase()
    .replace(/^https?:\/\//u, '')
    .replace(/^(www\.|m\.)/u, '')
    .replace(/^vk\.ru\//u, 'vk.com/')
    .replace(/^zen\.yandex\.ru\//u, 'dzen.ru/')
    .replace(/[?#].*$/u, '')
    .replace(/\/+$/u, '');
  const platform = platformOf(normalized);
  const slug = normalized.split('/').slice(1).join('/');
  return { platform, normalized, slug };
}

function seedByUrl(parsed: ParsedUrl): SourceSeed | undefined {
  return SOURCE_SEEDS.find(
    (seed) =>
      parseUrl(sourceUrl(seed)).normalized === parsed.normalized ||
      // канал Дзена открывают и по нику, и по id издателя
      (seed.platform === 'dzen' && parsed.normalized === `dzen.ru/id/${seed.ownerId}`),
  );
}

/** Как назвать источник площадки в подсказке: «эту группу», «этот сайт». */
const SOURCE_ACCUSATIVE: Record<PlatformId, string> = {
  vk: 'эту группу',
  ok: 'эту группу',
  max: 'этот канал',
  site: 'этот сайт',
  dzen: 'этот канал',
};

function guessType(slug: string): SourceType {
  if (/adm|admin|gorod/u.test(slug)) return 'municipal';
  if (/news|novosti|tv|gazeta/u.test(slug)) return 'media';
  return 'community';
}

function previewOf(seed: SourceSeed): NonNullable<SourceCheck['preview']> {
  return {
    platform: seed.platform,
    name: seed.name,
    url: sourceUrl(seed),
    subscribers: seed.subscribers,
    lastPostAt: at('2026-10-19 09:40'),
    suggestedType: seed.type,
    suggestedDistrict: seed.district,
  };
}

function checkUrl(url: string): SourceCheck {
  const checkedAt = nowIso();
  const parsed = parseUrl(url);
  // У сайта СМИ адрес источника — сам домен, у остальных площадок нужен путь к группе.
  if (!parsed.platform || (parsed.platform !== 'site' && parsed.slug.length === 0)) {
    return {
      state: 'not-supported',
      message:
        'Это не ссылка на группу или канал ВКонтакте, Одноклассников, MAX, Дзена и не сайт из каталога СМИ края.',
      preview: null,
      checkedAt,
    };
  }
  // Ссылка на пост, а не на группу (SC-10): подсказываем группу, где он вышел.
  const post = postOwner(url);
  if (post.isPost) {
    const owner = post.seed;
    const isArticle = owner?.platform === 'site';
    return {
      state: 'post-link',
      message: owner
        ? isArticle
          ? `Это ссылка на статью. Она опубликована на сайте «${owner.name}» — можно проверить и добавить ${SOURCE_ACCUSATIVE[owner.platform]}.`
          : `Это ссылка на пост. Он опубликован в «${owner.name}» — можно проверить и добавить ${SOURCE_ACCUSATIVE[owner.platform]}.`
        : 'Это ссылка на пост, а не на группу. Откройте группу или канал, где он вышел, и скопируйте их адрес.',
      preview: owner && !owner.closed ? previewOf(owner) : null,
      checkedAt,
    };
  }
  const seed = seedByUrl(parsed);
  if (seed) {
    const preview = previewOf(seed);
    if (mySources.has(seed.id)) {
      return {
        state: 'duplicate',
        message: seed.closed
          ? `«${seed.name}» уже есть в вашем списке, но группа закрыта: по ней не ищем.`
          : `«${seed.name}» уже есть в вашем списке.`,
        preview,
        checkedAt,
      };
    }
    if (seed.closed) {
      return {
        state: 'closed',
        message: `«${seed.name}» — закрытая группа: её посты не видны, искать в ней нельзя.`,
        preview: null,
        checkedAt,
      };
    }
    if (!seed.regional) {
      return {
        state: 'not-regional',
        message: `«${seed.name}» пишет не только о крае. Добавить можно: в подборку попадут посты, где упоминается край.`,
        preview,
        checkedAt,
      };
    }
    return {
      state: 'ok',
      message:
        seed.platform === 'site'
          ? `Сайт «${seed.name}» доступен: статьи читаются из ленты RSS или раздела новостей.`
          : seed.platform === 'dzen'
            ? `Канал «${seed.name}» на Дзене доступен: публикации читаются со страницы канала.`
            : `«${seed.name}» доступен: открытая группа, посты читаются.`,
      preview,
      checkedAt,
    };
  }
  if (/404|notfound|not-found|deleted/u.test(parsed.slug)) {
    return {
      state: 'not-found',
      message: 'По этой ссылке ничего нет: группа удалена или ссылка с ошибкой.',
      preview: null,
      checkedAt,
    };
  }
  if (/closed|private/u.test(parsed.slug)) {
    return {
      state: 'closed',
      message: 'Это закрытая группа: её посты не видны.',
      preview: null,
      checkedAt,
    };
  }
  const label = parsed.slug.replace(/^(club|public|group\/|id\/)/u, '');
  return {
    state: 'ok',
    message: OK_MESSAGE[parsed.platform],
    preview: {
      platform: parsed.platform,
      name: parsed.platform === 'dzen' ? `Канал «${label}» на Дзене` : `Сообщество «${label}»`,
      url: `https://${parsed.normalized}`,
      subscribers: 1_000 + ((label.length * 1_337) % 40_000),
      lastPostAt: at('2026-10-18 17:05'),
      suggestedType: guessType(label),
      suggestedDistrict: null,
    },
    checkedAt,
  };
}

// ---------------------------------------------------------------- недавние поиски

function seededConditions(
  id: string,
  text: string,
  label: string,
  kind: SearchConditions['kind'],
  period: SearchConditions['period'],
  mode: SearchConditions['mode'],
  startedAt: string,
  meaningLabel: string | null = null,
): SearchConditions {
  return {
    searchId: id,
    text,
    label,
    kind,
    period,
    region: { id: 'krasnoyarsk-krai', name: 'Красноярский край', timeZone: 'Asia/Krasnoyarsk' },
    mode,
    sourceCount: mode === 'my-sources' ? 20 : null,
    platforms: [...PLATFORM_ORDER],
    meaningLabel,
    startedAt: at(startedAt),
    finishedAt: at(
      startedAt.replace(
        /:(\d\d)$/u,
        (_, m: string) => `:${String(Math.min(59, Number(m) + 1)).padStart(2, '0')}`,
      ),
    ),
    repeatOf: null,
  };
}

function seededRecent(): RecentSearch[] {
  const bdd = seededConditions(
    'recent-bdd',
    'Безопасность дорожного движения',
    'Безопасность дорожного движения',
    'topic',
    { preset: '30d', from: '2026-09-19', to: '2026-10-18' },
    'everywhere',
    '2026-10-18 16:20',
  );
  const school = seededConditions(
    'recent-school',
    RELEASE_SOURCE_TEXT,
    'Новая школа в Норильске',
    'news-text',
    { preset: '7d', from: '2026-10-10', to: '2026-10-16' },
    'everywhere',
    '2026-10-16 18:05',
  );
  const river = seededConditions(
    'recent-river',
    'Енисей',
    'Енисей (река)',
    'event',
    { preset: '7d', from: '2026-10-09', to: '2026-10-15' },
    'my-sources',
    '2026-10-15 11:40',
    'Река Енисей',
  );
  const tariffs = seededConditions(
    'recent-tariffs',
    'Тарифы ЖКХ в Минусинске',
    'Тарифы ЖКХ в Минусинске',
    'topic',
    { preset: '7d', from: '2026-10-08', to: '2026-10-14' },
    'my-sources',
    '2026-10-14 09:10',
  );
  const toRequest = (c: SearchConditions, meaningId?: string): SearchRequest => ({
    text: c.text,
    period: c.period,
    mode: c.mode,
    ...(meaningId ? { meaningId } : {}),
  });
  return [
    {
      searchId: bdd.searchId,
      conditions: bdd,
      total: 37,
      statusSummary: 'VK ✓ 21 · OK ✓ 7 · MAX ✓ 5 · Сайты ✓ 3 · Дзен ✓ 1',
      request: toRequest(bdd),
    },
    {
      searchId: school.searchId,
      conditions: school,
      total: 22,
      statusSummary: 'VK ✓ 9 · OK ✓ 4 · MAX ✓ 2 · Сайты ✓ 5 · Дзен ✓ 2',
      request: toRequest(school),
    },
    {
      searchId: river.searchId,
      conditions: river,
      total: 4,
      statusSummary: 'VK ✓ 2 · OK ✓ 1 · MAX ✓ 1 · Сайты ничего не найдено · Дзен ничего не найдено',
      request: toRequest(river, 'river'),
    },
    {
      searchId: tariffs.searchId,
      conditions: tariffs,
      total: 0,
      statusSummary: 'ничего не найдено на всех площадках',
      request: toRequest(tariffs),
    },
  ];
}

let recent: RecentSearch[] = seededRecent();

function statusSummary(selection: Selection): string {
  if (selection.counts.total === 0 && selection.statuses.every((s) => s.state === 'nothing')) {
    return 'ничего не найдено на всех площадках';
  }
  return selection.statuses
    .map((s) => {
      const view = platformStatusView(s);
      const mark = s.state === 'found' ? `✓ ${s.found}` : view.text;
      return `${PLATFORMS[s.platform].short} ${mark}`;
    })
    .join(' · ');
}

function rememberSearch(record: SearchRecord): void {
  const selection = snapshot(record);
  const entry: RecentSearch = {
    searchId: record.searchId,
    conditions: selection.conditions,
    total: selection.counts.total,
    statusSummary: statusSummary(selection),
    request: clone(record.request),
  };
  recent = [entry, ...recent.filter((r) => r.searchId !== record.searchId)].slice(0, 20);
  persistRecord(record);
}

// ---------------------------------------------------------------- снимки между страницами

/**
 * Законченные поиски лежат в хранилище сеанса (lib/host.ts). Так подборку видит и заново
 * открытая боковая панель, и вкладка «Открыть во вкладке»: у каждой страницы своя память,
 * а настоящий сервер хранит поиски сам. Держим несколько последних.
 */
const SAVED_KEY = 'mm:fake:searches';
const SAVED_LIMIT = 3;

interface SavedRecord {
  request: SearchRequest;
  selection: Selection;
  savedAt: number;
}

function isSavedRecord(value: unknown, searchId: string): value is SavedRecord {
  if (typeof value !== 'object' || value === null) return false;
  const v = value as { request?: { text?: unknown }; selection?: { searchId?: unknown } };
  return typeof v.request?.text === 'string' && v.selection?.searchId === searchId;
}

async function readSaved(): Promise<Record<string, unknown>> {
  const value = await getHost().session.get(SAVED_KEY);
  return typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : {};
}

/** Записи идут по очереди, чтобы два быстрых исключения не затёрли друг друга. */
let saving: Promise<void> = Promise.resolve();

function persistRecord(record: SearchRecord): void {
  if (record.phase === 'running') return;
  const entry: SavedRecord = {
    request: clone(record.request),
    selection: snapshot(record),
    savedAt: Date.now(),
  };
  saving = saving
    .then(async () => {
      const saved = { ...(await readSaved()), [record.searchId]: entry };
      const kept = Object.entries(saved)
        .map(([id, value]) => [id, value, isSavedRecord(value, id) ? value.savedAt : 0] as const)
        .sort((a, b) => b[2] - a[2])
        .slice(0, SAVED_LIMIT)
        .map(([id, value]) => [id, value]);
      await getHost().session.set(SAVED_KEY, Object.fromEntries(kept));
    })
    .catch(() => undefined);
}

/** Поиска нет в памяти страницы — поднять его из снимка, если он есть. */
async function ensureRecord(searchId: string): Promise<void> {
  if (getRecord(searchId)) return;
  const entry = (await readSaved())[searchId];
  if (!isSavedRecord(entry, searchId)) return;
  try {
    adoptRecord(entry.request, entry.selection, context(null));
  } catch {
    // снимок от другой версии мокапа — считаем, что поиска нет
  }
}

/** Вызов над записью поиска: сначала поднять её из снимка, если страницу открыли заново. */
function withRecord<T>(
  base: number,
  searchId: string,
  body: (record: SearchRecord) => T,
): Promise<T> {
  return ensureRecord(searchId).then(() => call(base, () => body(requireRecord(searchId))));
}

// ---------------------------------------------------------------- сценарии

subscribeDemo((next, prev) => {
  if (next.scenario === prev.scenario) return;
  if (next.scenario === 'first-run') {
    mySources = new Map<string, Source>();
    trash.clear();
  } else if (prev.scenario === 'first-run') {
    mySources = defaultSources();
  }
  if (next.scenario === 'offline') dropConnectionFor(6000);
  else if (prev.scenario === 'offline') restoreConnection();
});

// ---------------------------------------------------------------- проверка наборов

if (import.meta.env.DEV) {
  const sets = [buildBdd(), buildRelease(), buildEvent('all'), buildLarge()];
  for (const set of sets) {
    const problems = validateItems(
      [...set.items, ...set.optional.flatMap((o) => o.items), ...set.spare].map((d) => d.item),
    );
    if (problems.length > 0) console.warn(`Демо-набор «${set.id}»: нарушения контракта`, problems);
  }
}

// ---------------------------------------------------------------- распространение

function waveOf(items: ResultItem[], bucketMs: number): WavePoint[] {
  const dated = items.filter((i) => i.publication.publishedAt);
  if (dated.length === 0) return [];
  const OFFSET = 7 * 3600_000;
  const floor = (ms: number): number => Math.floor((ms + OFFSET) / bucketMs) * bucketMs - OFFSET;
  const times = dated.map((i) => Date.parse(i.publication.publishedAt ?? ''));
  const first = floor(Math.min(...times));
  const last = floor(Math.max(...times));
  const points: WavePoint[] = [];
  for (let t = first; t <= last; t += bucketMs) {
    points.push({ start: toKrskIso(t), count: 0, byPlatform: emptyByPlatform() });
  }
  dated.forEach((item, idx) => {
    const time = times[idx] ?? 0;
    const point = points[Math.round((floor(time) - first) / bucketMs)];
    if (!point) return;
    point.count += 1;
    point.byPlatform[item.publication.platform] += 1;
  });
  return points;
}

function buildSpread(record: SearchRecord, groupId?: string): SpreadReport {
  const release = record.dataset.release;
  const group = record.dataset.groups.find((g) =>
    groupId ? g.id === groupId : g.kind === 'release',
  );
  if (!release || !group) {
    throw apiError(
      'not-found',
      'Распространение считается для поиска по тексту новости. Вставьте текст релиза в поле поиска.',
    );
  }
  const members = record.items
    .filter((i) => i.groupId === group.id && !i.excluded)
    .sort((a, b) =>
      (a.publication.publishedAt ?? '9').localeCompare(b.publication.publishedAt ?? '9'),
    );
  const original = members.find((m) => m.isOriginal) ?? members[0];
  if (!original) throw apiError('not-found', 'В группе не осталось размещений: все исключены.');

  const notes: OriginNote[] = [
    {
      code: 'first-among-found',
      message: 'Первым среди найденного. Более ранние публикации могли не попасть в поиск.',
    },
  ];
  if (original.publication.timeReliability === 'approximate') {
    notes.push({
      code: 'approximate-time',
      message:
        original.publication.platform === 'site'
          ? 'Время приблизительное: у статьи сайта известна только дата из поиска по сайту.'
          : 'Время приблизительное: MAX не отдаёт время, оно вычислено по номеру поста.',
    });
  }
  if (original.publication.edited)
    notes.push({ code: 'edited', message: 'Пост редактировался после публикации.' });

  const sources = new Map<string, number | null>();
  for (const m of members) sources.set(m.publication.source.id, m.publication.source.subscribers);
  const subsKnown = [...sources.values()].filter((v): v is number => v !== null);
  const viewsKnown = members.map((m) => m.publication.views).filter((v): v is number => v !== null);

  const byPlatform = emptyByPlatform();
  const byType = { verbatim: 0, shortened: 0, retold: 0, repost: 0 };
  for (const m of members) {
    byPlatform[m.publication.platform] += 1;
    if (m.placementType) byType[m.placementType] += 1;
  }

  const placements: SpreadPlacement[] = members.map((m) => ({
    itemId: m.id,
    platform: m.publication.platform,
    sourceName: m.publication.source.name,
    publishedAt: m.publication.publishedAt,
    timeReliability: m.publication.timeReliability,
    subscribers: m.publication.source.subscribers,
    views: m.publication.views,
    placementType: m.placementType ?? 'retold',
    isOriginal: m.isOriginal,
    citationShare: m.citation?.share ?? 0,
    url: m.publication.url,
    ...(m.aiCheck ? { aiCheck: m.aiCheck } : {}),
    ...(m.publication.demo ? { demo: true } : {}),
  }));
  // Проверка на ИИ — только пересказы: копия релиза получает оценку самого релиза.
  const retold = placements.filter((p) => !p.isOriginal && p.placementType === 'retold');

  return {
    searchId: record.searchId,
    groupId: group.id,
    title: release.title,
    release: {
      text: release.text,
      fragments: release.fragments.map((f) => ({
        ...f,
        takenBy: members.filter((m) => !m.isOriginal && m.citation?.fragmentIds.includes(f.id))
          .length,
      })),
    },
    original: {
      itemId: original.id,
      sourceName: original.publication.source.name,
      platform: original.publication.platform,
      publishedAt: original.publication.publishedAt,
      timeReliability: original.publication.timeReliability,
      notes,
    },
    totals: { placements: members.length, byPlatform, byType },
    audience: {
      value: subsKnown.length > 0 ? subsKnown.reduce((a, b) => a + b, 0) : null,
      withData: subsKnown.length,
      of: sources.size,
      howCounted:
        'Сумма подписчиков источников по данным площадок. Одни и те же люди могут быть подписаны на несколько групп, поэтому это не число людей.',
    },
    views: {
      value: viewsKnown.length > 0 ? viewsKnown.reduce((a, b) => a + b, 0) : null,
      withData: viewsKnown.length,
      of: members.length,
      howCounted:
        'Сумма просмотров по данным площадок. Одноклассники и часть сайтов СМИ не отдают просмотры: по ним «нет данных», а не ноль.',
    },
    wave: { hourly: waveOf(members, 3600_000), daily: waveOf(members, 86400_000) },
    placements,
    aiRetold: {
      likelyAi: retold.filter((p) => p.aiCheck?.level === 'likely-ai').length,
      retold: retold.length,
    },
    computedAt: nowIso(),
  };
}

// ---------------------------------------------------------------- выгрузка

/** Ячейка, начинающаяся с = + - @, сохраняется как текст (НТ-10). */
function safeCell(value: string): string {
  return /^[=+\-@]/u.test(value) ? `'${value}` : value;
}

function exportItems(record: SearchRecord, options?: ExportOptions): ResultItem[] {
  const filter =
    options?.onlyRelevance && options.onlyRelevance.length > 0
      ? new Set(options.onlyRelevance)
      : null;
  return record.items
    .filter((i) => !i.excluded && (!filter || filter.has(i.relevance)))
    .sort((a, b) =>
      (b.publication.publishedAt ?? '').localeCompare(a.publication.publishedAt ?? ''),
    );
}

/** `full` — все строки (для файла); без него — первые 50 для предпросмотра. */
function buildExport(record: SearchRecord, options?: ExportOptions, full = false): ExportPreview {
  const selection = snapshot(record);
  const rows = exportItems(record, options);
  const c = selection.conditions;
  const groupTitle = new Map(selection.groups.map((g) => [g.id, g.title]));
  // Тема, дата и время поиска по Красноярску: две выгрузки за день не совпадут по имени
  const finishedAt = c.finishedAt ?? c.startedAt;
  const fileDate = finishedAt.slice(0, 10);
  const fileTime = finishedAt.slice(11, 16).replace(':', '-');
  const columns = [
    { id: 'n', title: '№' },
    { id: 'platform', title: 'Площадка' },
    { id: 'source', title: 'Источник' },
    { id: 'headline', title: 'Заголовок или начало поста' },
    { id: 'date', title: 'Дата публикации (время красноярское)' },
    { id: 'url', title: 'Ссылка' },
    { id: 'excerpt', title: 'Выдержка' },
    { id: 'relevance', title: 'Метка' },
    { id: 'method', title: 'Как отобрано' },
    { id: 'region', title: 'Почему краевой' },
    { id: 'placement', title: 'Тип размещения' },
    { id: 'group', title: 'Группа' },
    { id: 'fetched', title: 'Получено' },
  ];
  const table: ExportCell[][] = (full ? rows : rows.slice(0, 50)).map((item, index) => {
    const p = item.publication;
    return [
      index + 1,
      PLATFORMS[p.platform].itemName,
      safeCell(p.source.name),
      safeCell(p.headline),
      formatPublishedAt(p),
      p.demo ? DEMO_POST_NOTE : p.url,
      item.excerpt ? safeCell(item.excerpt.text) : 'текст отсутствует',
      RELEVANCE_LABEL[item.relevance],
      METHOD_LABEL[item.method],
      regionReasonText(item.regionReason),
      item.placementType ? PLACEMENT_TYPE_LABEL[item.placementType] : '',
      item.groupId ? (groupTitle.get(item.groupId) ?? '') : '',
      formatDateTime(p.fetchedAt),
    ];
  });
  const counts = computeCounts(rows);
  const appliedFilter =
    options?.onlyRelevance && options.onlyRelevance.length > 0 ? [...options.onlyRelevance] : null;
  const safeLabel =
    c.label
      .replace(/[^\p{L}\p{N}]+/gu, '_')
      .replace(/^_+|_+$/gu, '')
      .slice(0, 40) || 'подборка';

  return {
    searchId: record.searchId,
    fileName: `Медиарадар_${safeLabel}_${fileDate}_${fileTime}.xlsx`,
    rowCount: rows.length,
    excludedCount: selection.counts.excluded,
    rule: appliedFilter
      ? `В файл попадут только записи с метками: ${appliedFilter.map((r) => RELEVANCE_LABEL[r]).join(', ')}. Исключённые вами записи не попадут.`
      : 'В файл попадает вся подборка, кроме исключённых вами записей. Фильтр на экране на файл не влияет. Группы выгружаются построчно: у каждого размещения своя строка и колонка «Группа».',
    appliedFilter,
    summary: {
      name: 'Сводка',
      entries: [
        { label: 'Запрос', value: truncateText(c.text, 300) },
        {
          label: 'Что искали',
          value: QUERY_KIND_LABEL[c.kind] + (c.meaningLabel ? ` · ${c.meaningLabel}` : ''),
        },
        { label: 'Период', value: `${formatPeriod(c.period)} (${TIME_ZONE_LABEL_FULL})` },
        { label: 'Регион', value: c.region.name },
        {
          label: 'Источники',
          value:
            c.mode === 'my-sources'
              ? `${MODE_LABEL[c.mode]}: ${c.sourceCount ?? 0}`
              : MODE_LABEL[c.mode],
        },
        {
          label: 'Площадки',
          value: selection.statuses
            .map((s) => `${PLATFORMS[s.platform].name}: ${platformStatusView(s).text}`)
            .join('; '),
        },
        { label: 'Поиск выполнен', value: formatDateTime(c.finishedAt ?? c.startedAt) },
        { label: 'Записей в файле', value: String(rows.length) },
        { label: 'Исключено вами', value: String(selection.counts.excluded) },
        {
          label: 'По меткам',
          value: RELEVANCE_ORDER.map((r) => `${RELEVANCE_LABEL[r]}: ${counts.byRelevance[r]}`).join(
            ' · ',
          ),
        },
        { label: 'Время', value: TIME_ZONE_LABEL_FULL },
        {
          label: 'Данные',
          value:
            'Демонстрационные (мокап). Группы и каналы VK, OK, MAX вымышлены; сайты СМИ и каналы Дзена — настоящие редакции края, публикации придуманы.',
        },
      ],
    },
    publications: { name: 'Публикации', columns, rows: table, totalRows: rows.length },
    timeZoneNote: TIME_ZONE_LABEL_FULL,
  };
}

/** Ширина колонок «Публикаций» в знаках — чтобы файл читался без ручной подгонки */
const EXPORT_WIDTHS = [5, 14, 26, 44, 22, 38, 64, 12, 22, 30, 16, 26, 18];

function buildExportFile(record: SearchRecord, options?: ExportOptions): ExportFile {
  const book = buildExport(record, options, true);
  const { summary, publications } = book;
  const linkColumn = publications.columns.findIndex((col) => col.id === 'url');
  const file = buildXlsx([
    { name: summary.name, widths: [24, 90], rows: summary.entries.map((e) => [e.label, e.value]) },
    {
      name: publications.name,
      header: true,
      widths: EXPORT_WIDTHS,
      linkColumns: linkColumn >= 0 ? [linkColumn] : [],
      rows: [publications.columns.map((col) => col.title), ...publications.rows],
    },
  ]);
  return { fileName: book.fileName, rowCount: book.rowCount, file };
}

// ---------------------------------------------------------------- стенд

function standStatus(): StandStatus {
  const { scenario, maxFailure } = getDemoState();
  const maxDown = scenario === 'max-down';
  const aiDown = scenario === 'ai-down';
  const queue = scenario === 'queue';
  const offline = getConnection() === 'offline';
  const now = demoNowMs();
  const ago = (min: number): string => toKrskIso(now - min * 60_000);
  const maxMessage = maxDown
    ? {
        unavailable: 'Не отвечает с 14:05. Повторы каждые 2 минуты.',
        'bad-response': 'Отвечает в непонятном формате с 13:50 — нужен разбор.',
        'rate-limited': 'Ограничение частоты запросов: часть каналов не проверена.',
        'key-invalid': 'Ключ доступа недействителен — замените ключ в настройках сервера.',
        'quota-exhausted': 'Квота на сегодня исчерпана. Сброс в 00:00.',
      }[maxFailure]
    : 'Работает.';
  // MAX ищется через сторонний индекс с отставанием (НТ-4).
  const maxFreshness = {
    delayHours: 24,
    note: 'MAX ищется через сторонний индекс: публикации последних ~24 часов могут ещё не найтись.',
  };
  return {
    checkedAt: nowIso(),
    overall: maxDown || aiDown || offline ? 'degraded' : 'ok',
    platforms: [
      {
        platform: 'vk',
        state: maxDown ? 'degraded' : 'ok',
        message: maxDown ? 'Работает. 1 группа из демо-списка закрыта.' : 'Работает.',
        via: platformVia('vk'),
        freshness: null,
        quota: {
          used: 3_412,
          limit: 10_000,
          unit: 'вызовов в месяц',
          resetsAt: at('2026-11-01 00:00'),
        },
        lastSuccessAt: ago(1),
      },
      {
        platform: 'ok',
        state: 'ok',
        message: 'Работает.',
        via: platformVia('ok'),
        freshness: null,
        quota: null,
        lastSuccessAt: ago(2),
      },
      {
        platform: 'max',
        state: maxDown ? (maxFailure === 'rate-limited' ? 'degraded' : 'down') : 'ok',
        message: maxMessage,
        via: platformVia('max'),
        freshness: maxFreshness,
        quota: {
          used: maxDown && maxFailure === 'quota-exhausted' ? 1_000 : 388,
          limit: 1_000,
          unit: 'кредитов',
          resetsAt: maxDown && maxFailure === 'quota-exhausted' ? at('2026-10-20 00:00') : null,
        },
        lastSuccessAt: maxDown ? ago(27) : ago(3),
      },
      {
        platform: 'site',
        state: 'ok',
        message: 'Работает. Подключено 43 сайта из 48: 5 не опрашиваются.',
        via: platformVia('site'),
        freshness: null,
        quota: null,
        lastSuccessAt: ago(4),
      },
      {
        platform: 'dzen',
        state: 'ok',
        message: 'Работает. Каналы 25 редакций края.',
        via: platformVia('dzen'),
        freshness: null,
        quota: null,
        lastSuccessAt: ago(5),
      },
    ],
    ai: {
      state: aiDown ? 'down' : 'ok',
      model: 'GigaChat 3.1 Lightning, локально (Ollama)',
      warm: !aiDown,
      queueLength: queue ? 2 : 0,
      avgSecondsPerPost: aiDown ? null : 0.8,
    },
    queue: { running: queue ? 3 : 1, waiting: queue ? 2 : 0, perClientLimit: 2 },
    memory: { usedMb: 9_850, totalMb: 16_384 },
    events: [
      ...(aiDown
        ? [
            {
              at: ago(4),
              level: 'error' as const,
              message: 'Нейросеть не отвечает: перезапуск Ollama не помог.',
            },
          ]
        : []),
      ...(maxDown ? [{ at: ago(27), level: 'error' as const, message: `MAX: ${maxMessage}` }] : []),
      ...(queue
        ? [
            {
              at: ago(2),
              level: 'warning' as const,
              message: 'Очередь к нейросети: 2 поиска ждут.',
            },
          ]
        : []),
      { at: ago(35), level: 'info', message: 'Нейросеть прогрета после перезапуска сервера.' },
      { at: ago(36), level: 'info', message: 'Сервер перезапущен, версия 0.1.0-mockup.' },
    ],
    version: '0.1.0-mockup',
  };
}

// ---------------------------------------------------------------- импорт из Excel (ТЗ-Ф16)

const importPreviews = new Map<string, ImportPreview>();
let importCounter = 0;

/** Демо-файл: в мокапе файл не читается, строки собираются из каталога и списка. */
const DEMO_IMPORT_COLUMNS: ImportPreview['columns'] = [
  {
    letter: 'A',
    title: 'Название',
    role: 'name',
    note: 'название — подставим, если площадка не отдаст своё',
  },
  { letter: 'B', title: 'Ссылка на группу', role: 'url', note: 'ссылки — по ним добавляем' },
  { letter: 'C', title: 'Комментарий', role: 'ignored', note: 'не используем' },
];

function addRow(row: number, seed: SourceSeed, variant: number): ImportRow {
  const plain = sourceUrl(seed);
  const source = toSourceRef(seed, false);
  if (variant === 1) {
    return {
      row,
      value: `  ${plain.replace(/^https:\/\//u, '')}  `,
      title: seed.name,
      outcome: { kind: 'add', source, note: 'убрали лишние пробелы' },
    };
  }
  if (variant === 2 && plain.startsWith('https://vk.com/')) {
    return {
      row,
      value: plain.replace('https://vk.com/', 'https://m.vk.com/'),
      title: seed.name,
      outcome: { kind: 'add', source, note: 'мобильная ссылка — привели к обычной' },
    };
  }
  return { row, value: plain, title: seed.name, outcome: { kind: 'add', source, note: null } };
}

const emptyRow = (row: number): ImportRow => ({
  row,
  value: '',
  title: '',
  outcome: { kind: 'empty' },
});

function buildImportPreview(fileName: string): ImportPreview {
  // Источник демо-ссылки «доступна» в файл не кладём: иначе после импорта её проверка
  // ответит «уже в списке».
  const reserved = new Set(['vk-minusinsk']);
  const fresh = SOURCE_SEEDS.filter(
    (s) => s.regional && !s.closed && !mySources.has(s.id) && !reserved.has(s.id),
  ).slice(0, 6);
  const dups = SOURCE_SEEDS.filter((s) => mySources.has(s.id) && !s.closed).slice(0, 2);
  const closed = SOURCE_SEEDS.find((s) => s.closed && !mySources.has(s.id));
  const rows: ImportRow[] = [];
  // строки 2–6: новые источники
  for (let i = 0; i < 5; i += 1) {
    const seed = fresh[i];
    rows.push(seed ? addRow(i + 2, seed, i) : emptyRow(i + 2));
  }
  rows.push({
    row: 7,
    value: 'https://example.ru/news',
    title: 'Сайт новостей',
    outcome: { kind: 'skip', reason: 'Сайт не из каталога СМИ края: такие сайты не опрашиваем' },
  });
  const sixth = fresh[5];
  rows.push(sixth ? addRow(8, sixth, 0) : emptyRow(8));
  const [dup0, dup1] = dups;
  rows.push(
    dup0
      ? {
          row: 9,
          value: sourceUrl(dup0),
          title: dup0.name,
          outcome: { kind: 'duplicate', source: toSourceRef(dup0, true) },
        }
      : emptyRow(9),
  );
  rows.push(emptyRow(10));
  rows.push(
    dup1
      ? {
          row: 11,
          value: sourceUrl(dup1),
          title: dup1.name,
          outcome: { kind: 'duplicate', source: toSourceRef(dup1, true) },
        }
      : emptyRow(11),
  );
  rows.push(
    closed
      ? {
          row: 12,
          value: sourceUrl(closed),
          title: closed.name,
          outcome: { kind: 'skip', reason: 'Группа закрыта: посты не видны' },
        }
      : emptyRow(12),
  );
  rows.push({
    row: 13,
    value: 'https://vk.com/wall-100104_60210',
    title: 'Пост про школу',
    outcome: {
      kind: 'skip',
      reason: 'Ссылка на пост, а не на группу: добавьте группу, где он вышел',
    },
  });

  const count = (kind: ImportRow['outcome']['kind']): number =>
    rows.filter((r) => r.outcome.kind === kind).length;
  importCounter += 1;
  return {
    previewId: `import-${importCounter}`,
    fileName,
    sheetName: 'Лист1',
    totalRows: rows.length + 1,
    headerRow: 1,
    columns: DEMO_IMPORT_COLUMNS,
    rows,
    counts: {
      add: count('add'),
      duplicate: count('duplicate'),
      skip: count('skip'),
      empty: count('empty'),
    },
  };
}

function checkSpreadsheet(file: File): void {
  if (!/\.(xlsx|xls|csv)$/iu.test(file.name)) {
    throw apiError(
      'invalid',
      `«${file.name}» — не таблица. Нужен файл Excel (.xlsx, .xls) или CSV.`,
    );
  }
}

/** Добавить строки «добавим» разбора `previewId`: итог совпадает с предпросмотром. */
function runImport(previewId: string): ImportReport {
  const preview = importPreviews.get(previewId);
  if (!preview) throw apiError('not-found', 'Разбор файла устарел. Выберите файл ещё раз.');
  const report: ImportReport = { added: [], duplicates: [], skipped: [] };
  for (const row of preview.rows) {
    const { outcome } = row;
    if (outcome.kind === 'add') {
      if (mySources.has(outcome.source.id)) {
        report.duplicates.push({ row: row.row, value: row.value, name: outcome.source.name });
        continue;
      }
      const source = sourceFromSeed(seedById(outcome.source.id), 'import', nowIso());
      mySources.set(source.id, source);
      report.added.push(clone(source));
    } else if (outcome.kind === 'duplicate') {
      report.duplicates.push({ row: row.row, value: row.value, name: outcome.source.name });
    } else if (outcome.kind === 'skip') {
      report.skipped.push({ row: row.row, value: row.value, reason: outcome.reason });
    }
  }
  importPreviews.delete(previewId);
  return report;
}

// ---------------------------------------------------------------- рабочее место (Р8)

const WORKSPACE_KEY = 'mm-mockup-workspace';

function randomKey(length: number): string {
  const alphabet = 'abcdefghijkmnpqrstuvwxyz23456789';
  const bytes = new Uint8Array(length);
  crypto.getRandomValues(bytes);
  return [...bytes].map((b) => alphabet[b % alphabet.length] ?? 'a').join('');
}

interface StoredWorkspace {
  id: string;
  key: string;
  createdAt: string;
}

function loadWorkspace(): StoredWorkspace {
  try {
    const raw = window.localStorage.getItem(WORKSPACE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<StoredWorkspace>;
      if (parsed.id && parsed.key && parsed.createdAt) {
        return { id: parsed.id, key: parsed.key, createdAt: parsed.createdAt };
      }
    }
  } catch {
    // хранилище недоступно — рабочее место живёт до перезагрузки
  }
  const created: StoredWorkspace = {
    id: `ws-${randomKey(8)}`,
    key: randomKey(24),
    createdAt: nowIso(),
  };
  try {
    window.localStorage.setItem(WORKSPACE_KEY, JSON.stringify(created));
  } catch {
    // без запоминания
  }
  return created;
}

let workspace: StoredWorkspace | null = null;

function currentWorkspace(): Workspace {
  workspace ??= loadWorkspace();
  return {
    id: workspace.id,
    createdAt: workspace.createdAt,
    sourcesCount: mySources.size,
    recentCount: recent.length,
  };
}

function workspaceLink(): WorkspaceLink {
  const ws = currentWorkspace();
  const key = workspace?.key ?? '';
  const base =
    typeof window !== 'undefined'
      ? `${window.location.origin}${window.location.pathname}`
      : 'https://mediamonitor.demo/';
  // Ключ — во фрагменте адреса (#…): браузер не отправляет его на сервер в запросе страницы.
  return { workspaceId: ws.id, key, url: `${base}#workspace=${key}`, createdAt: nowIso() };
}

// ---------------------------------------------------------------- перепроверка списка (П9)

function recheckAll(): SourcesRecheckReport {
  const checkedAt = nowIso();
  const problems: SourcesRecheckReport['problems'] = [];
  for (const [id, source] of mySources) {
    const seed = SOURCE_SEEDS.find((s) => s.id === id);
    const check: SourceCheck = seed?.closed
      ? {
          state: 'closed',
          message: 'Группа закрыта: её посты не видны, поиск по ней невозможен.',
          preview: null,
          checkedAt,
        }
      : seed && !seed.regional
        ? {
            state: 'not-regional',
            message: 'Пишет не только о крае: в подборку попадут посты, где упоминается край.',
            preview: null,
            checkedAt,
          }
        : { ...checkOk(source.platform), checkedAt };
    mySources.set(id, { ...source, check });
    if (check.state !== 'ok') {
      problems.push({
        sourceId: id,
        name: source.name,
        state: check.state,
        message: check.message,
      });
    }
  }
  const sources = [...mySources.values()]
    .sort((a, b) => a.name.localeCompare(b.name, 'ru'))
    .map(clone);
  return {
    checkedAt,
    checked: sources.length,
    ok: sources.filter((s) => s.check.state === 'ok').length,
    problems,
    sources,
  };
}

// ---------------------------------------------------------------- реализация

function context(previous: SearchContext['previous']): SearchContext {
  return {
    demo: getDemoState(),
    mySourceIds: myIds(),
    mySourceNames: myNamesByPlatform(),
    previous,
    onFinished: rememberSearch,
  };
}

function requireRecord(searchId: string): SearchRecord {
  const record = getRecord(searchId);
  if (!record) throw apiError('not-found', 'Поиск не найден. Запустите его заново.');
  return record;
}

function previousFor(request: SearchRequest): SearchContext['previous'] {
  if (!request.repeatOf) return null;
  const record = getRecord(request.repeatOf);
  if (record) {
    return {
      itemIds: new Set(record.items.map((i) => i.id)),
      ranAtMs: Date.parse(record.conditions.finishedAt ?? record.conditions.startedAt),
    };
  }
  const seeded = recent.find((r) => r.searchId === request.repeatOf);
  if (!seeded) return null;
  return {
    itemIds: null,
    ranAtMs: Date.parse(seeded.conditions.finishedAt ?? seeded.conditions.startedAt),
  };
}

export function createFakeApi(): MonitorApi {
  return {
    getStartState: () =>
      call(200, (): StartState => {
        const firstRun = mySources.size === 0;
        return {
          firstRun,
          sourcesCount: mySources.size,
          defaultMode: 'everywhere',
          exampleQuery: 'Например: безопасность дорожного движения',
          defaultPeriod: presetPeriod('30d'),
          region: {
            id: 'krasnoyarsk-krai',
            name: 'Красноярский край',
            timeZone: 'Asia/Krasnoyarsk',
          },
          platforms: platformInfo(),
        };
      }),

    analyzeQuery: (text: string) => call(180, (): QueryAnalysis => analyze(text)),

    understandTopic: (
      text: string,
      options?: { meaningId?: string; correction?: TopicCorrection },
    ) =>
      call(getDemoState().scenario === 'ai-down' ? 300 : 750, (): TopicUnderstanding => {
        const base = topicFor(text, options?.meaningId);
        const correction = options?.correction;
        let topic: TopicUnderstanding = clone(base);
        if (correction) {
          const all = [...topic.includes, ...topic.excludes];
          topic = {
            ...topic,
            includes: all
              .filter((f) =>
                correction.include.includes(f.id)
                  ? true
                  : correction.exclude.includes(f.id)
                    ? false
                    : topic.includes.some((i) => i.id === f.id),
              )
              .map((f) =>
                correction.include.includes(f.id) ? { ...f, origin: 'user' as const } : f,
              ),
            excludes: all
              .filter((f) =>
                correction.exclude.includes(f.id)
                  ? true
                  : correction.include.includes(f.id)
                    ? false
                    : topic.excludes.some((e) => e.id === f.id),
              )
              .map((f) =>
                correction.exclude.includes(f.id) ? { ...f, origin: 'user' as const } : f,
              ),
          };
        }
        if (getDemoState().scenario === 'ai-down') {
          topic = {
            ...topic,
            madeBy: 'rules',
            note: 'Нейросеть недоступна: карточка составлена по словам запроса. Спорные публикации будут помечены «не проверено ИИ».',
          };
        }
        return topic;
      }),

    startSearch: (request: SearchRequest): SearchRun =>
      startFakeSearch(clone(request), context(previousFor(request))),

    attachSearch: (searchId: string): SearchRun => attachFakeSearch(searchId),

    stopSearch: (searchId: string) =>
      call(80, () => {
        stopById(searchId);
      }),

    retryPlatform: (searchId: string, platform: PlatformId): SearchRun =>
      retryFakePlatform(searchId, platform, context(null)),

    getSelection: (searchId: string) =>
      withRecord(150, searchId, (record): Selection => snapshot(record)),

    setExcluded: (searchId: string, itemIds: string[], excluded: boolean) =>
      withRecord(140, searchId, (record): SelectionCounts => {
        const ids = new Set(itemIds);
        for (const item of record.items) if (ids.has(item.id)) item.excluded = excluded;
        persistRecord(record);
        return computeCounts(record.items);
      }),

    excludeSource: (searchId: string, sourceId: string) =>
      withRecord(180, searchId, (record) => {
        const itemIds: string[] = [];
        for (const item of record.items) {
          if (item.publication.source.id === sourceId && !item.excluded) {
            item.excluded = true;
            itemIds.push(item.id);
          }
        }
        persistRecord(record);
        return { itemIds, counts: computeCounts(record.items) };
      }),

    addByUrl: (searchId: string, url: string) =>
      withRecord(900, searchId, (record): ResultItem => {
        const parsed = parseUrl(url);
        if (!parsed.platform)
          throw apiError(
            'invalid',
            'Это не ссылка на пост ВКонтакте, Одноклассников, MAX, Дзена или статью сайта СМИ края.',
          );
        const all = [
          ...record.dataset.items,
          ...record.dataset.spare,
          ...record.dataset.optional.flatMap((o) => o.items),
        ].map((d) => d.item);
        const found = all.find(
          (i) =>
            parseUrl(i.publication.url).normalized === parsed.normalized ||
            i.publication.mergedUrls.some((u) => parseUrl(u).normalized === parsed.normalized),
        );
        if (!found)
          throw apiError(
            'not-found',
            'Пост по ссылке не найден: он удалён, закрыт или ссылка с ошибкой.',
          );
        const existing = record.items.find((i) => i.id === found.id);
        if (existing) {
          if (!existing.excluded) throw apiError('invalid', 'Эта публикация уже есть в подборке.');
          existing.excluded = false;
          persistRecord(record);
          return { ...existing };
        }
        const item: ResultItem = withAiCheck(clone(found), !record.aiAvailable);
        item.method = 'manual';
        item.methodNote = 'Вы добавили публикацию по ссылке';
        item.publication.fetchedAt = nowIso();
        record.arrival += 1;
        item.arrival = record.arrival;
        record.items.push(item);
        persistRecord(record);
        return { ...item };
      }),

    recheckLinks: (searchId: string) =>
      withRecord(1400, searchId, (record): LinkRecheckReport => {
        const checkedAt = nowIso();
        const active = record.items.filter((i) => !i.excluded);
        // В демо один пост «удалён после поиска» (НТ-19, SC-69)
        const deleted = active.length > 3 ? [active[2]] : [];
        for (const item of active) {
          item.publication.linkCheck = {
            state: deleted.includes(item) ? 'deleted' : 'ok',
            checkedAt,
          };
        }
        persistRecord(record);
        return {
          checked: active.length,
          ok: active.length - deleted.length,
          deletedItemIds: deleted.flatMap((d) => (d ? [d.id] : [])),
          checkedAt,
        };
      }),

    checkAiText: (text: string) =>
      call(1100, (): AiCheck =>
        demoAiCheck(text, { modelDown: getDemoState().scenario === 'ai-down' }),
      ),

    getSpread: (searchId: string, groupId?: string) =>
      withRecord(600, searchId, (record): SpreadReport => buildSpread(record, groupId)),

    getExportPreview: (searchId: string, options?: ExportOptions) =>
      withRecord(500, searchId, (record): ExportPreview => buildExport(record, options)),

    getExportFile: (searchId: string, options?: ExportOptions) =>
      withRecord(700, searchId, (record): ExportFile => buildExportFile(record, options)),

    listSources: () =>
      call(320, (): Source[] =>
        [...mySources.values()].sort((a, b) => a.name.localeCompare(b.name, 'ru')).map(clone),
      ),

    checkSource: (url: string) => call(1100, (): SourceCheck => checkUrl(url)),

    addSource: (input: SourceInput) =>
      call(1100, (): Source => {
        const check = checkUrl(input.url);
        if ((check.state !== 'ok' && check.state !== 'not-regional') || !check.preview) {
          throw apiError('invalid', check.message);
        }
        const seed = seedByUrl(parseUrl(input.url));
        manualCounter += 1;
        const id = seed?.id ?? `manual-${manualCounter}`;
        const source: Source = {
          id,
          platform: check.preview.platform,
          name: input.name?.trim() || check.preview.name,
          url: check.preview.url,
          type: input.type ?? check.preview.suggestedType,
          district: input.district !== undefined ? input.district : check.preview.suggestedDistrict,
          subscribers: check.preview.subscribers,
          inMySources: true,
          regional: seed?.regional ?? true,
          origin: 'manual',
          addedAt: nowIso(),
          check,
        };
        mySources.set(id, source);
        return clone(source);
      }),

    updateSource: (id: string, patch: Partial<Omit<SourceInput, 'url'>>) =>
      call(300, (): Source => {
        const source = mySources.get(id);
        if (!source) throw apiError('not-found', 'Источник не найден в вашем списке.');
        const next: Source = {
          ...source,
          ...(patch.name !== undefined ? { name: patch.name } : {}),
          ...(patch.type !== undefined ? { type: patch.type } : {}),
          ...(patch.district !== undefined ? { district: patch.district } : {}),
        };
        mySources.set(id, next);
        return clone(next);
      }),

    removeSource: (id: string) =>
      call(250, (): void => {
        const source = mySources.get(id);
        if (!source) throw apiError('not-found', 'Источник не найден в вашем списке.');
        mySources.delete(id);
        trash.set(id, source);
      }),

    restoreSource: (id: string) =>
      call(200, (): Source => {
        const source = trash.get(id);
        if (!source) throw apiError('not-found', 'Источник уже нельзя вернуть.');
        trash.delete(id);
        mySources.set(id, source);
        return clone(source);
      }),

    recheckSources: () => call(1600, (): SourcesRecheckReport => recheckAll()),

    previewImport: (file: File) =>
      call(1200, (): ImportPreview => {
        checkSpreadsheet(file);
        const preview = buildImportPreview(file.name);
        importPreviews.set(preview.previewId, preview);
        return clone(preview);
      }),

    importSources: (source: File | string) =>
      call(1500, (): ImportReport => {
        if (typeof source === 'string') return runImport(source);
        // Файл без предпросмотра: разобрать и сразу добавить.
        checkSpreadsheet(source);
        const preview = buildImportPreview(source.name);
        importPreviews.set(preview.previewId, preview);
        return runImport(preview.previewId);
      }),

    getCatalog: () => call(400, (): CatalogSource[] => catalogSources(myIds())),

    addFromCatalog: (ids: string[]) =>
      call(500, (): Source[] => {
        const added: Source[] = [];
        for (const id of ids) {
          const seed = SOURCE_SEEDS.find((s) => s.id === id && s.regional && !s.closed);
          if (!seed || mySources.has(id)) continue;
          const source = sourceFromSeed(seed, 'catalog', nowIso());
          mySources.set(id, source);
          added.push(clone(source));
        }
        return added;
      }),

    getWorkspace: () => call(150, (): Workspace => currentWorkspace()),

    getWorkspaceLink: () => call(250, (): WorkspaceLink => workspaceLink()),

    openWorkspace: (key: string) =>
      call(400, (): Workspace => {
        const ws = currentWorkspace();
        const clean = key.trim().replace(/^.*#workspace=/u, '');
        if (clean !== workspace?.key) {
          throw apiError(
            'not-found',
            'Рабочее место по этой ссылке не найдено. Проверьте, что ссылка скопирована целиком.',
          );
        }
        return ws;
      }),

    // В имитации рабочее место одно: другого места по ссылке нет, возвращаться некуда.
    peekWorkspace: (key: string) =>
      call(200, (): Workspace => {
        const ws = currentWorkspace();
        if (key.trim().replace(/^.*#workspace=/u, '') !== workspace?.key)
          throw apiError('not-found', 'Рабочее место по этой ссылке не найдено.');
        return ws;
      }),

    previousWorkspaceKey: () => null,

    pendingWorkspaceLink: () => null,

    onPendingWorkspaceLink: () => () => undefined,

    dismissWorkspaceLink: () => undefined,

    listRecent: () => call(300, (): RecentSearch[] => recent.map(clone)),

    getStandStatus: () => call(350, (): StandStatus => standStatus()),

    getConnection: () => getConnection(),

    onConnectionChange: (listener) => onConnectionChange(listener),
  };
}

/** Примеры запросов и ссылок для демо — показываются только в панели мокапа. */
export const DEMO_QUERIES: readonly { id: string; label: string; text: string }[] = [
  {
    id: 'bdd',
    label: 'Тема: безопасность дорожного движения',
    text: 'Безопасность дорожного движения',
  },
  { id: 'release', label: 'Текст релиза «Новая школа в Норильске»', text: RELEASE_SOURCE_TEXT },
  { id: 'event', label: 'Многозначный запрос: «Енисей»', text: 'Енисей' },
  { id: 'region', label: 'Другой регион: ДТП в Новосибирске', text: 'ДТП в Новосибирске' },
  {
    id: 'hints',
    label: 'Запрос с подсказками',
    text: 'подбери, пожалуйста, новости о ДТП в Красноярском крае на прошлой неделе',
  },
  { id: 'link', label: 'Ссылка вместо текста', text: 'https://vk.com/wall-100104_60210' },
];

/** Примеры текстов для экрана «Проверка на ИИ» — пересказы релиза из демо-набора. */
export const DEMO_AI_TEXTS: readonly { id: string; label: string; text: string }[] =
  RELEASE_AI_SAMPLES;

export const DEMO_LINKS = {
  /** Пост вне периода — можно добавить в подборку БДД по ссылке (П8) */
  addByUrl: 'https://vk.com/wall-100106_57990',
  /** Источник, которого нет в списке: проверка «ок» */
  sourceOk: 'https://vk.com/demo_minusinsk',
  /** Закрытая группа, которой нет в списке */
  sourceClosed: 'https://vk.com/demo_kodinsk',
  /** Ссылка на пост вместо группы: проверка подскажет группу, где он вышел */
  sourcePostLink: 'https://vk.com/wall-100104_60210',
  /** Не краевой источник */
  sourceNotRegional: 'https://vk.com/demo_news_sibir',
  /** Не та площадка */
  sourceNotSupported: 'https://example.ru/news',
  /** Уже в списке */
  sourceDuplicate: 'https://vk.com/demo_tv_kraya',
} as const;
