/**
 * Имитация поиска: ход по площадкам и источникам, порции записей, сбои по сценарию.
 * Таймеры настоящие, поэтому ход, «+N новых», «Остановить» и обрыв связи
 * выглядят так же, как с настоящим сервером.
 */
import type {
  PlatformId,
  PlatformProblem,
  PlatformState,
  PlatformStatus,
  ResultGroup,
  ResultItem,
  SearchConditions,
  SearchRequest,
  Selection,
  SelectionCounts,
  SelectionNotice,
  TopicUnderstanding,
} from '../types';
import { PLATFORM_ORDER } from '@/lib/labels';
import { demoAiCheck, immediateAiCheck } from './ai';
import { dayEndMs, dayStartMs, demoNowMs, nowIso } from './clock';
import type { DemoItem } from './build';
import { setConnection } from './connection';
import type { Dataset } from './datasets/types';
import { OK_CAP } from './datasets/large';
import { detectKind, pickDataset } from './query';
import type { DemoState, MaxFailure } from './scenario';
import { EVERYWHERE_POOL } from './sources';
import { FakeSearchRun } from './stream';

// ---------------------------------------------------------------- состояние

interface PlatformPlan {
  platform: PlatformId;
  /** Записи площадки в порядке прихода */
  queue: ResultItem[];
  released: number;
  total: number;
  unit: 'sources' | 'pages';
  done: number;
  /** Сколько единиц хода за тик */
  speed: number;
  /** На какой единице хода случится сбой (по сценарию) */
  failAt: number | null;
  failure: { state: PlatformState; problem: PlatformProblem } | null;
  /** Итоговое состояние после окончания хода */
  finalState: PlatformState | null;
  finalProblem: PlatformProblem | null;
  currentSource: string | null;
  updatedAt: string | null;
}

export interface SearchRecord {
  searchId: string;
  request: SearchRequest;
  conditions: SearchConditions;
  dataset: Dataset;
  plans: Record<PlatformId, PlatformPlan>;
  /** Все записи, которые уже пришли, в порядке прихода */
  items: ResultItem[];
  /** Все записи набора после фильтров (для «добавить по ссылке» и спарки) */
  pool: Map<string, ResultItem>;
  topic: TopicUnderstanding | null;
  aiAvailable: boolean;
  phase: Selection['phase'];
  notices: SelectionNotice[];
  arrival: number;
  /** Обрыв связи уже был в этом поиске */
  connectionDropped: boolean;
}

const records = new Map<string, SearchRecord>();
const activeRunners = new Map<string, Runner>();
let searchCounter = 0;

export function getRecord(searchId: string): SearchRecord | undefined {
  return records.get(searchId);
}

export interface SearchContext {
  demo: DemoState;
  mySourceIds: ReadonlySet<string>;
  /** Названия источников пользователя по площадкам — для «сейчас проверяем …» */
  mySourceNames: Record<PlatformId, string[]>;
  /** Прежний поиск для пометки «новое» (П12) */
  previous: { itemIds: ReadonlySet<string> | null; ranAtMs: number } | null;
  onFinished: (record: SearchRecord) => void;
}

// ---------------------------------------------------------------- подсчёты

const emptyByPlatform = (): Record<PlatformId, number> => ({ vk: 0, ok: 0, max: 0 });

export function computeCounts(items: readonly ResultItem[]): SelectionCounts {
  const counts: SelectionCounts = {
    total: 0,
    excluded: 0,
    byRelevance: { direct: 0, indirect: 0, disputed: 0 },
    byPlatform: emptyByPlatform(),
    byPlacementType: { verbatim: 0, shortened: 0, retold: 0, repost: 0 },
    new: 0,
    aiLikely: 0,
    aiSigns: 0,
  };
  for (const item of items) {
    if (item.excluded) {
      counts.excluded += 1;
      continue;
    }
    counts.total += 1;
    counts.byRelevance[item.relevance] += 1;
    counts.byPlatform[item.publication.platform] += 1;
    if (item.placementType) counts.byPlacementType[item.placementType] += 1;
    if (item.isNew) counts.new += 1;
    if (item.aiCheck?.level === 'likely-ai') counts.aiLikely += 1;
    if (item.aiCheck?.level === 'signs') counts.aiSigns += 1;
  }
  return counts;
}

function computeGroups(record: SearchRecord): ResultGroup[] {
  return record.dataset.groups
    .map((group) => {
      const members = record.items
        .filter((item) => item.groupId === group.id)
        .sort((a, b) =>
          (a.publication.publishedAt ?? '').localeCompare(b.publication.publishedAt ?? ''),
        );
      const active = members.filter((m) => !m.excluded);
      const countsByPlatform = emptyByPlatform();
      const countsByType = { verbatim: 0, shortened: 0, retold: 0, repost: 0 };
      for (const m of active) {
        countsByPlatform[m.publication.platform] += 1;
        if (m.placementType) countsByType[m.placementType] += 1;
      }
      return {
        ...group,
        itemIds: members.map((m) => m.id),
        originalItemId: members.find((m) => m.isOriginal)?.id ?? null,
        countsByPlatform,
        countsByType,
      };
    })
    .filter((group) => group.itemIds.length > 0);
}

function platformStatus(record: SearchRecord, platform: PlatformId): PlatformStatus {
  const plan = record.plans[platform];
  const found = record.items.filter(
    (i) => i.publication.platform === platform && !i.excluded,
  ).length;
  const running = record.phase === 'running' && plan.finalState === null;
  let state: PlatformState;
  if (plan.finalState) state = plan.finalState;
  else if (record.phase === 'stopped') state = 'stopped';
  else if (running && plan.done === 0 && plan.total > 0) state = 'waiting';
  else state = 'searching';
  const showProgress =
    state === 'searching' || state === 'partial' || state === 'stopped' || plan.total === 0;
  const freshness =
    platform === 'max'
      ? {
          delayHours: 24,
          note: 'MAX ищется через сторонний индекс: публикации последних ~24 часов могут ещё не найтись.',
        }
      : null;
  const cap =
    record.dataset.id === 'large' && platform === 'ok' && found >= OK_CAP
      ? { limit: OK_CAP, note: `Одноклассники отдают не больше ${OK_CAP} результатов на запрос` }
      : null;
  return {
    platform,
    state,
    found,
    progress: showProgress
      ? { done: Math.floor(plan.done + 1e-6), total: plan.total, unit: plan.unit }
      : null,
    problem: plan.finalProblem,
    freshness,
    cap,
    updatedAt: plan.updatedAt,
  };
}

export function snapshot(record: SearchRecord): Selection {
  return {
    searchId: record.searchId,
    conditions: { ...record.conditions },
    statuses: PLATFORM_ORDER.map((p) => platformStatus(record, p)),
    items: record.items.map((item) => ({ ...item })),
    groups: computeGroups(record),
    counts: computeCounts(record.items),
    topic: record.topic,
    notices: [...record.notices],
    aiAvailable: record.aiAvailable,
    phase: record.phase,
  };
}

// ---------------------------------------------------------------- подготовка

function inPeriod(item: DemoItem, request: SearchRequest, startedMs: number): boolean {
  if (item.publishedMs === null) return true; // без даты — показываем с пометкой (ТЗ-Ф36)
  if (request.period.preset === '24h') {
    return item.publishedMs >= startedMs - 24 * 3600_000 && item.publishedMs <= startedMs;
  }
  return (
    item.publishedMs >= dayStartMs(request.period.from) &&
    item.publishedMs <= dayEndMs(request.period.to)
  );
}

function prepareItems(
  dataset: Dataset,
  request: SearchRequest,
  ctx: SearchContext,
  startedMs: number,
): DemoItem[] {
  const include = new Set(request.topic?.include ?? []);
  const exclude = new Set(request.topic?.exclude ?? []);
  let pool: DemoItem[] = [...dataset.items];
  for (const extra of dataset.optional) {
    if (include.has(extra.facetId)) pool.push(...extra.items);
  }
  if (exclude.size > 0) {
    pool = pool.filter((d) => d.facets.length === 0 || d.facets.some((f) => !exclude.has(f)));
  }
  const allowedSources =
    request.mode === 'my-sources'
      ? new Set(
          request.sourceIds && request.sourceIds.length > 0 ? request.sourceIds : ctx.mySourceIds,
        )
      : null;
  return pool.filter((d) => {
    if (!inPeriod(d, request, startedMs)) return false;
    if (allowedSources && !allowedSources.has(d.item.publication.source.id)) return false;
    return true;
  });
}

function decorate(
  d: DemoItem,
  request: SearchRequest,
  ctx: SearchContext,
  aiDown: boolean,
): ResultItem {
  const item: ResultItem = structuredClone(d.item);
  item.publication.source.inMySources = ctx.mySourceIds.has(item.publication.source.id);
  // Причина «в вашем списке» (Р4): в «Моих источниках» все записи — из выбранных
  // источников списка (prepareItems), в режиме «Везде» её нет.
  item.regionReason.inMySources = request.mode === 'my-sources';
  if (ctx.previous) {
    item.isNew = ctx.previous.itemIds
      ? !ctx.previous.itemIds.has(item.id)
      : d.publishedMs !== null && d.publishedMs > ctx.previous.ranAtMs;
  }
  if (aiDown && (item.method === 'ai-confirmed' || item.relevance === 'disputed')) {
    item.method = 'ai-unchecked';
    item.methodNote =
      'Смысловая проверка недоступна: нейросеть не ответила. Решите сами, подходит ли публикация.';
    item.relevance = 'disputed';
    if (item.evidence && item.evidence.basis === 'ai')
      item.evidence = { ...item.evidence, basis: 'semantic' };
  }
  // Проверка на ИИ — при выдаче записи (releaseUpTo) и фоном, как на сервере.
  delete item.aiCheck;
  return item;
}

/**
 * Проверка текста поста на ИИ сразу — тот же метод и кэш, что у отдельной проверки
 * (fake/ai.ts). Для «добавить по ссылке» и для снимка, где оценка не успела. Пост без текста
 * не проверяем. «Нейросеть недоступна» — детектор на той же машине с видеокартой, что и
 * GigaChat, поэтому тоже недоступен.
 */
export function withAiCheck(item: ResultItem, modelDown: boolean): ResultItem {
  const text = item.publication.text;
  if (text === null) delete item.aiCheck;
  else item.aiCheck = demoAiCheck(text, { modelDown });
  return item;
}

function failureFor(kind: MaxFailure): { state: PlatformState; problem: PlatformProblem } {
  switch (kind) {
    case 'unavailable':
      return {
        state: 'error',
        problem: {
          code: 'unavailable',
          message:
            'MAX не отвечает. Найденное на других площадках сохранено — можно повторить поиск по MAX.',
          retryable: true,
        },
      };
    case 'bad-response':
      return {
        state: 'error',
        problem: {
          code: 'bad-response',
          message:
            'MAX ответил в непонятном формате. Это ошибка, а не «ничего не найдено» — повторите позже.',
          retryable: true,
        },
      };
    case 'rate-limited':
      return {
        state: 'partial',
        problem: {
          code: 'rate-limited',
          message:
            'MAX ограничил частоту запросов: проверена только часть каналов. Повторите через минуту.',
          retryable: true,
        },
      };
    case 'key-invalid':
      return {
        state: 'no-access',
        problem: {
          code: 'key-invalid',
          message: 'Нет доступа к MAX: ключ доступа недействителен. Сообщите дежурному стенда.',
          retryable: false,
        },
      };
    case 'quota-exhausted':
      return {
        state: 'no-access',
        problem: {
          code: 'quota-exhausted',
          message:
            'Кончилась квота запросов к MAX на сегодня. Поиск по MAX снова заработает после 00:00.',
          retryable: false,
        },
      };
  }
}

const CLOSED_GROUP_PROBLEM: PlatformProblem = {
  code: 'sources-closed',
  message:
    'Одна группа из списка закрыта: «Новости Богучан». Её посты не видны, остальные проверены.',
  retryable: false,
};

function makePlans(
  items: ResultItem[],
  request: SearchRequest,
  ctx: SearchContext,
): Record<PlatformId, PlatformPlan> {
  const scenario = ctx.demo.scenario;
  const plans = {} as Record<PlatformId, PlatformPlan>;
  for (const platform of PLATFORM_ORDER) {
    const queue = items
      .filter((i) => i.publication.platform === platform)
      .sort((a, b) =>
        (b.publication.publishedAt ?? '').localeCompare(a.publication.publishedAt ?? ''),
      );
    const total =
      request.mode === 'my-sources'
        ? ctx.mySourceNames[platform].length
        : EVERYWHERE_POOL[platform];
    const ticks = platform === 'vk' ? 18 : platform === 'ok' ? 15 : 20;
    const failMax = scenario === 'max-down' && platform === 'max' && total > 0;
    plans[platform] = {
      platform,
      queue,
      released: 0,
      total,
      unit: 'sources',
      done: 0,
      speed: Math.max(total / ticks, 0.34),
      failAt: failMax ? Math.max(1, Math.round(total * 0.45)) : null,
      failure: failMax ? failureFor(ctx.demo.maxFailure) : null,
      finalState: null,
      finalProblem: null,
      currentSource: null,
      updatedAt: null,
    };
  }
  return plans;
}

// ---------------------------------------------------------------- ход

const TICK_MS = { normal: 260, slow: 1150 } as const;

interface Runner {
  record: SearchRecord;
  run: FakeSearchRun;
  ctx: SearchContext;
  platforms: PlatformId[];
  timer: ReturnType<typeof setTimeout> | null;
  /** Связь пропала: события копятся и уходят после восстановления */
  buffering: boolean;
  pending: ResultItem[];
  closedGroup: boolean;
  /** Записи, тексты которых ждут фоновой проверки на ИИ (у них пока нет `aiCheck`). */
  aiWaiting: Set<ResultItem>;
}

function sourceNameFor(runner: Runner, platform: PlatformId, done: number): string | null {
  const names = runner.ctx.mySourceNames[platform];
  if (runner.record.request.mode === 'my-sources' && names.length > 0) {
    return names[Math.min(names.length - 1, Math.floor(done))] ?? null;
  }
  return null;
}

function emitPlatform(runner: Runner, platform: PlatformId): void {
  if (runner.buffering) return;
  const plan = runner.record.plans[platform];
  runner.run.emit({
    type: 'platform',
    status: platformStatus(runner.record, platform),
    currentSource: plan.finalState ? null : plan.currentSource,
  });
}

function emitItems(runner: Runner, fresh: ResultItem[]): void {
  if (fresh.length === 0) return;
  if (runner.buffering) {
    // Та же запись могла ждать и с оценкой на ИИ — в очереди она одна.
    for (const item of fresh) if (!runner.pending.includes(item)) runner.pending.push(item);
    return;
  }
  const { record } = runner;
  runner.run.emit({
    type: 'items',
    items: fresh.map((i) => ({ ...i })),
    groups: computeGroups(record),
    counts: computeCounts(record.items),
  });
}

function releaseUpTo(runner: Runner, plan: PlatformPlan, done: number): ResultItem[] {
  const n = plan.queue.length;
  const fresh: ResultItem[] = [];
  while (plan.released < n) {
    const threshold = ((plan.released + 1) / (n + 1)) * Math.max(plan.total, 1);
    if (done < threshold && plan.total > 0) break;
    const item = plan.queue[plan.released];
    plan.released += 1;
    if (!item) continue;
    runner.record.arrival += 1;
    item.arrival = runner.record.arrival;
    item.publication.fetchedAt = nowIso();
    attachImmediateAi(runner, item);
    runner.record.items.push(item);
    fresh.push(item);
  }
  return fresh;
}

// ---------------------------------------------------------------- проверка на ИИ фоном

/** Задержка фоновой проверки на ИИ — как у детектора на машине с видеокартой. */
const AI_DELAY_MS = { normal: 1100, slow: 3200 } as const;

/**
 * Как на сервере: короткие, уже проверенные и «недоступна» — сразу; остальные уходят в
 * поток без `aiCheck` и ждут фоновой проверки.
 */
function attachImmediateAi(runner: Runner, item: ResultItem): void {
  const text = item.publication.text;
  delete item.aiCheck;
  if (text === null) return;
  const result = immediateAiCheck(text, { modelDown: !runner.record.aiAvailable });
  if (result) item.aiCheck = result;
  else runner.aiWaiting.add(item);
}

/** Оценить тексты фоном и прислать эти же записи ещё раз — уже с оценкой. */
function scheduleAi(runner: Runner, fresh: readonly ResultItem[]): void {
  const batch = fresh.filter((item) => runner.aiWaiting.has(item));
  if (batch.length === 0) return;
  const ms = runner.ctx.demo.scenario === 'slow' ? AI_DELAY_MS.slow : AI_DELAY_MS.normal;
  setTimeout(
    () => {
      const done = batch.filter((item) => runner.aiWaiting.delete(item));
      for (const item of done) checkNow(runner, item);
      // Поиск уже закончен — оценки остались в записи и будут в подборке.
      if (done.length > 0 && !runner.run.closed) emitItems(runner, done);
    },
    ms + Math.round(Math.random() * ms * 0.5),
  );
}

function checkNow(runner: Runner, item: ResultItem): void {
  const text = item.publication.text;
  if (text !== null) item.aiCheck = demoAiCheck(text, { modelDown: !runner.record.aiAvailable });
}

/** Перед итогом сервер ждёт фоновую проверку (AI_DETECT_FINISH_WAIT_SEC): досчитываем. */
function drainAi(runner: Runner): void {
  for (const item of runner.aiWaiting) checkNow(runner, item);
  runner.aiWaiting.clear();
}

function finishPlatform(runner: Runner, plan: PlatformPlan): void {
  const found = runner.record.items.filter((i) => i.publication.platform === plan.platform).length;
  if (plan.platform === 'vk' && runner.closedGroup) {
    plan.finalState = 'partial';
    plan.finalProblem = CLOSED_GROUP_PROBLEM;
    plan.done = Math.max(0, plan.total - 1);
  } else {
    plan.finalState = found > 0 ? 'found' : 'nothing';
    plan.finalProblem = null;
  }
  plan.updatedAt = nowIso();
}

function tick(runner: Runner): void {
  const { record } = runner;
  if (record.phase !== 'running') return;
  const fresh: ResultItem[] = [];
  let active = 0;

  for (const platform of runner.platforms) {
    const plan = record.plans[platform];
    if (plan.finalState) continue;
    active += 1;
    if (plan.total === 0) {
      fresh.push(...releaseUpTo(runner, plan, 0));
      plan.finalState = 'nothing';
      plan.updatedAt = nowIso();
      emitPlatform(runner, platform);
      continue;
    }
    plan.done = Math.min(plan.total, plan.done + plan.speed);
    if (plan.total - plan.done < 1e-6) plan.done = plan.total;
    const done = Math.floor(plan.done);
    plan.currentSource = sourceNameFor(runner, platform, done);
    if (plan.failAt !== null && plan.failure && done >= plan.failAt) {
      fresh.push(...releaseUpTo(runner, plan, plan.failAt));
      plan.done = plan.failAt;
      plan.finalState = plan.failure.state;
      plan.finalProblem = plan.failure.problem;
      plan.updatedAt = nowIso();
      emitPlatform(runner, platform);
      continue;
    }
    fresh.push(...releaseUpTo(runner, plan, plan.done));
    if (plan.done >= plan.total) {
      finishPlatform(runner, plan);
    }
    emitPlatform(runner, platform);
  }

  emitItems(runner, fresh);
  scheduleAi(runner, fresh);

  // Обрыв связи (сценарий «Нет связи»): поиск продолжается на сервере (НТ-23).
  if (runner.ctx.demo.scenario === 'offline' && !record.connectionDropped) {
    const progress =
      runner.platforms.reduce(
        (sum, p) => sum + record.plans[p].done / Math.max(record.plans[p].total, 1),
        0,
      ) / runner.platforms.length;
    if (progress >= 0.35) {
      record.connectionDropped = true;
      runner.run.emit({
        type: 'connection-lost',
        message:
          'Нет связи с интернетом. Поиск продолжается на сервере — результаты появятся, когда связь вернётся.',
      });
      runner.buffering = true;
      setConnection('offline');
      setTimeout(() => {
        setConnection('online');
        runner.buffering = false;
        if (runner.run.closed) return;
        runner.run.emit({
          type: 'connection-restored',
          message: 'Связь восстановлена. Догружаем найденное.',
        });
        for (const p of runner.platforms) emitPlatform(runner, p);
        const pending = runner.pending;
        runner.pending = [];
        emitItems(runner, pending);
        if (record.phase === 'done')
          runner.run.emit({ type: 'finished', selection: snapshot(record) });
      }, 6000);
    }
  }

  if (active === 0 || runner.platforms.every((p) => record.plans[p].finalState !== null)) {
    complete(runner);
    return;
  }
  schedule(runner);
}

function schedule(runner: Runner): void {
  const ms = runner.ctx.demo.scenario === 'slow' ? TICK_MS.slow : TICK_MS.normal;
  runner.timer = setTimeout(() => tick(runner), ms + Math.round(Math.random() * 80));
}

function complete(runner: Runner): void {
  const { record } = runner;
  drainAi(runner);
  record.phase = 'done';
  record.conditions.finishedAt = nowIso();
  runner.timer = null;
  runner.ctx.onFinished(record);
  if (!runner.buffering) runner.run.emit({ type: 'finished', selection: snapshot(record) });
}

function stopRunner(runner: Runner): void {
  if (runner.timer) clearTimeout(runner.timer);
  runner.timer = null;
  const { record } = runner;
  if (record.phase !== 'running') return;
  record.phase = 'stopped';
  record.conditions.finishedAt = nowIso();
  for (const p of runner.platforms) {
    const plan = record.plans[p];
    if (!plan.finalState) plan.done = Math.floor(plan.done);
  }
  runner.ctx.onFinished(record);
  runner.buffering = false;
  const pending = runner.pending;
  runner.pending = [];
  emitItems(runner, pending);
  runner.run.emit({ type: 'stopped', selection: snapshot(record) });
}

// ---------------------------------------------------------------- запуск

function notesFor(dataset: Dataset, items: ResultItem[], aiDown: boolean): SelectionNotice[] {
  const notices: SelectionNotice[] = [...(dataset.notices ?? [])];
  if (aiDown) {
    notices.push({
      code: 'ai-unavailable',
      tone: 'warning',
      message:
        'Смысловая проверка недоступна: нейросеть не отвечает. Публикации найдены по совпадению слов и близости по смыслу; спорные помечены «не проверено ИИ».',
    });
  }
  if (items.some((i) => i.publication.publishedAt === null)) {
    notices.push({
      code: 'undated-included',
      tone: 'info',
      message:
        'Публикации без даты показаны с пометкой «дата неизвестна»: проверить, что они попадают в период, нельзя.',
    });
  }
  if (items.some((i) => i.publication.hasMedia)) {
    notices.push({
      code: 'images-not-analyzed',
      tone: 'info',
      message: 'Текст на картинках и в видео не анализируется.',
    });
  }
  return notices;
}

function aiDownTopic(topic: TopicUnderstanding | null): TopicUnderstanding | null {
  if (!topic) return null;
  return {
    ...topic,
    madeBy: 'rules',
    note: 'Нейросеть недоступна: карточка составлена по словам запроса. Спорные публикации помечены «не проверено ИИ».',
  };
}

function conditionsLabel(dataset: Dataset, text: string): string {
  if (dataset.id !== 'empty' && dataset.id !== 'large') return dataset.label;
  const trimmed = text.trim();
  return trimmed.length > 48 ? `${trimmed.slice(0, 48)}…` : trimmed;
}

export function startFakeSearch(request: SearchRequest, ctx: SearchContext): FakeSearchRun {
  searchCounter += 1;
  const searchId = `s-${Date.now().toString(36)}-${searchCounter}`;
  const run = new FakeSearchRun(searchId);
  const scenario = ctx.demo.scenario;
  const aiDown = scenario === 'ai-down';
  const startedMs = demoNowMs();

  if (request.text.trim().length > 20_000) {
    setTimeout(() => {
      run.emit({
        type: 'failed',
        error: {
          code: 'too-long',
          message: 'Текст запроса длиннее 20 000 знаков. Оставьте заголовок и первые абзацы.',
        },
      });
    }, 300);
    return run;
  }

  const dataset = pickDataset(request.text, request.meaningId, scenario);
  const prepared = prepareItems(dataset, request, ctx, startedMs);
  const items = prepared.map((d) => decorate(d, request, ctx, aiDown));
  const platforms =
    request.platforms && request.platforms.length > 0 ? request.platforms : [...PLATFORM_ORDER];
  const meaning = request.meaningId
    ? ((
        {
          river: 'Река Енисей',
          club: 'Спортивный клуб «Енисей»',
          all: 'Всё со словом «Енисей»',
        } as Record<string, string>
      )[request.meaningId] ?? null)
    : null;

  const conditions: SearchConditions = {
    searchId,
    text: request.text,
    label: conditionsLabel(dataset, request.text),
    kind:
      dataset.id === 'release' && request.text.length > 120
        ? 'news-text'
        : detectKind(request.text),
    period: { ...request.period },
    region: { id: 'krasnoyarsk-krai', name: 'Красноярский край', timeZone: 'Asia/Krasnoyarsk' },
    mode: request.mode,
    sourceCount:
      request.mode === 'my-sources' ? request.sourceIds?.length || ctx.mySourceIds.size : null,
    platforms,
    meaningLabel: meaning,
    startedAt: nowIso(),
    finishedAt: null,
    repeatOf: request.repeatOf ?? null,
  };

  const record: SearchRecord = {
    searchId,
    request: structuredClone(request),
    conditions,
    dataset,
    plans: makePlans(items, request, ctx),
    items: [],
    pool: new Map(items.map((i) => [i.id, i])),
    topic: aiDown ? aiDownTopic(dataset.topic) : dataset.topic,
    aiAvailable: !aiDown,
    phase: 'running',
    notices: notesFor(dataset, items, aiDown),
    arrival: 0,
    connectionDropped: false,
  };
  records.set(searchId, record);

  const runner: Runner = {
    record,
    run,
    ctx,
    platforms,
    timer: null,
    buffering: false,
    pending: [],
    aiWaiting: new Set(),
    closedGroup:
      scenario === 'max-down' &&
      (request.mode === 'everywhere' || ctx.mySourceIds.has('vk-boguchany')),
  };
  run.onStop(() => stopRunner(runner));
  activeRunners.set(searchId, runner);

  const begin = (): void => {
    if (record.phase !== 'running') return;
    run.emit({
      type: 'started',
      conditions: { ...conditions },
      statuses: PLATFORM_ORDER.map((p) => platformStatus(record, p)),
    });
    if (aiDown) {
      run.emit({
        type: 'ai-unavailable',
        message: 'Смысловая проверка недоступна: нейросеть не отвечает. Поиск идёт без неё.',
      });
    }
    runner.timer = setTimeout(
      () => {
        if (record.topic && record.phase === 'running')
          run.emit({ type: 'topic', topic: record.topic });
        schedule(runner);
      },
      scenario === 'slow' ? 1500 : 450,
    );
  };

  if (scenario === 'queue') {
    run.emit({ type: 'queued', ahead: 2, etaSec: 20 });
    runner.timer = setTimeout(() => {
      if (record.phase !== 'running') return;
      run.emit({ type: 'queued', ahead: 1, etaSec: 10 });
      runner.timer = setTimeout(begin, 3000);
    }, 3000);
  } else {
    setTimeout(begin, 120);
  }

  return run;
}

/** Повтор одной площадки после сбоя (ТЗ-Ф44). */
export function retryFakePlatform(
  searchId: string,
  platform: PlatformId,
  ctx: SearchContext,
): FakeSearchRun {
  const run = new FakeSearchRun(searchId);
  const record = records.get(searchId);
  if (!record) {
    setTimeout(
      () => run.emit({ type: 'failed', error: { code: 'not-found', message: 'Поиск не найден.' } }),
      100,
    );
    return run;
  }
  const plan = record.plans[platform];
  const failure = plan.failure;
  const stillFails =
    failure !== null && ctx.demo.scenario === 'max-down' && failure.state === 'no-access';

  plan.finalState = null;
  plan.finalProblem = null;
  plan.failAt = stillFails ? plan.failAt : null;
  plan.failure = stillFails ? failure : null;
  plan.done = stillFails ? 0 : Math.floor(plan.done);
  record.phase = 'running';
  record.conditions.finishedAt = null;

  const runner: Runner = {
    record,
    run,
    ctx,
    platforms: [platform],
    timer: null,
    buffering: false,
    pending: [],
    aiWaiting: new Set(),
    closedGroup: false,
  };
  run.onStop(() => stopRunner(runner));
  activeRunners.set(searchId, runner);
  setTimeout(() => {
    emitPlatform(runner, platform);
    schedule(runner);
  }, 200);
  return run;
}

/**
 * Поднять законченный поиск из снимка. Настоящий сервер хранит поиски сам, а имитация
 * живёт в памяти страницы: боковую панель закрыли и открыли, поиск перенесли во вкладку —
 * памяти уже нет. Поэтому имитация кладёт снимок в хранилище сеанса (index.ts) и здесь
 * собирает из него запись заново. Очереди площадок строим тем же порядком, что при
 * поиске, — «Повторить» по площадке после сбоя досыплет то, что не успело прийти.
 */
export function adoptRecord(
  request: SearchRequest,
  selection: Selection,
  ctx: SearchContext,
): SearchRecord {
  const dataset = pickDataset(request.text, request.meaningId, ctx.demo.scenario);
  const startedMs = Date.parse(selection.conditions.startedAt);
  const prepared = prepareItems(dataset, request, ctx, startedMs).map((d) =>
    decorate(d, request, ctx, !selection.aiAvailable),
  );
  const plans = makePlans(prepared, request, ctx);
  for (const status of selection.statuses) {
    const plan = plans[status.platform];
    const arrived = new Set(
      selection.items.filter((i) => i.publication.platform === status.platform).map((i) => i.id),
    );
    plan.queue = [
      ...plan.queue.filter((i) => arrived.has(i.id)),
      ...plan.queue.filter((i) => !arrived.has(i.id)),
    ];
    plan.released = plan.queue.filter((i) => arrived.has(i.id)).length;
    plan.done = status.progress ? status.progress.done : plan.total;
    plan.finalState =
      status.state === 'searching' || status.state === 'waiting' ? 'stopped' : status.state;
    plan.finalProblem = status.problem;
    plan.updatedAt = status.updatedAt;
  }
  const record: SearchRecord = {
    searchId: selection.searchId,
    request: structuredClone(request),
    conditions: { ...selection.conditions },
    dataset,
    plans,
    // Оценка на ИИ не успела к снимку (поиск остановили) — «досчиталась», как на сервере.
    items: selection.items.map((i) => {
      const item = structuredClone(i);
      return item.aiCheck ? item : withAiCheck(item, !selection.aiAvailable);
    }),
    pool: new Map(prepared.map((i) => [i.id, i])),
    topic: selection.topic,
    aiAvailable: selection.aiAvailable,
    phase: selection.phase === 'running' ? 'stopped' : selection.phase,
    notices: [...selection.notices],
    arrival: selection.items.reduce((max, i) => Math.max(max, i.arrival), 0),
    // обрыв связи по сценарию уже показали в исходном поиске
    connectionDropped: true,
  };
  records.set(record.searchId, record);
  return record;
}

/** Остановить поиск по id (если он ещё идёт). */
export function stopById(searchId: string): void {
  const runner = activeRunners.get(searchId);
  if (runner) runner.run.stop();
}
