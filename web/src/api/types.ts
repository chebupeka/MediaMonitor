/**
 * Контракт предметной области Медиарадара.
 *
 * Эти типы — договор между интерфейсом и сервером. Сейчас их реализует имитация
 * (src/api/fake), потом — настоящий сервер. Экраны работают только с этими типами.
 * Меняет файл только «Основа» или лид (docs/09-mockup-brief.md, «Как делим работу»).
 *
 * Обозначения в комментариях: ТЗ-Ф — 01-tz.md; Р — 04-decisions.md;
 * НТ — 05-scenarios.md §5.1; П — дополнения из анализа конкурентов (04-decisions.md).
 *
 * Время. Все моменты — строки ISO 8601 со смещением красноярского времени
 * (`2026-10-14T10:02:00+07:00`). Показываем их только через src/lib/format.ts,
 * там же подпись «время красноярское» (НТ-12).
 */

// ============================================================================
// Базовые обозначения
// ============================================================================

/** Момент времени, ISO 8601 со смещением, например `2026-10-14T10:02:00+07:00`. */
export type IsoDateTime = string;

/** Календарная дата по красноярскому времени, `YYYY-MM-DD`. */
export type IsoDate = string;

/** Площадка. Полный набор — VK, OK, MAX (ТЗ-Ф18). */
export type PlatformId = 'vk' | 'ok' | 'max';

/** Регион поиска. В прототипе он один и фиксирован (Р4), но хранится как параметр. */
export interface Region {
  id: 'krasnoyarsk-krai';
  /** «Красноярский край» */
  name: string;
  /** IANA-зона для показа времени: `Asia/Krasnoyarsk` (UTC+7, НТ-12). */
  timeZone: 'Asia/Krasnoyarsk';
}

// ============================================================================
// Запрос и условия поиска
// ============================================================================

/**
 * Что ищем. Определяет сервер по тексту поля (одно поле на всё, П1 брифа).
 * - `topic` — тема своими словами («безопасность дорожного движения»);
 * - `event` — событие или человек, возможно с уточнением (SC-02);
 * - `news-text` — текст новости или релиза: ищем перепечатки (Сц. ТЗ 2, Р10).
 */
export type QueryKind = 'topic' | 'event' | 'news-text';

/**
 * Режим охвата источников (ТЗ-Ф13, Ф14).
 * - `my-sources` — только по списку пользователя;
 * - `everywhere` — без ограничения списком; главный фильтр — регион (Р4).
 */
export type SearchMode = 'my-sources' | 'everywhere';

/** Готовые периоды рядом с календарём (П10, НТ-22). `custom` — выбран в календаре. */
export type PeriodPreset = 'today' | '24h' | '7d' | '30d' | 'custom';

/** Период поиска. Границы включительно, по красноярскому времени (НТ-12). */
export interface Period {
  preset: PeriodPreset;
  /** Первый день периода. */
  from: IsoDate;
  /** Последний день периода (включительно). */
  to: IsoDate;
}

/** Правка карточки «Как система поняла тему» перед поиском (Р5, П14, SC-14). */
export interface TopicCorrection {
  /** id граней, которые пользователь перенёс в «входит». */
  include: string[];
  /** id граней, которые пользователь перенёс в «не то». */
  exclude: string[];
  /** Свои уточнения текстом: «только про детей», «без ремонта дорог». */
  notes?: string;
}

/** Запрос на поиск — то, что пользователь отправляет кнопкой «Найти». */
export interface SearchRequest {
  /** Текст поля как есть: тема, событие, человек или текст новости. До 20 000 знаков (НТ-6). */
  text: string;
  period: Period;
  mode: SearchMode;
  /**
   * Для режима `my-sources`: какие источники из списка использовать.
   * Не задано — все источники пользователя.
   */
  sourceIds?: string[];
  /** Площадки. По умолчанию все три; в интерфейсе выбор не предлагаем. */
  platforms?: PlatformId[];
  /** Выбранное значение многозначного запроса (id варианта из `QueryAnalysis.ambiguity`). */
  meaningId?: string;
  /** Правки карточки темы. */
  topic?: TopicCorrection;
  /**
   * Повтор недавнего поиска (П12): id прежнего поиска. Записи, которых не было
   * в прежней подборке, придут с `isNew: true` («новое»).
   */
  repeatOf?: string;
}

/**
 * Условия ВЫПОЛНЕННОГО поиска (НТ-1). Снимок на момент запуска: над подборкой
 * показываем именно его, а не текущие значения полей. XLSX берёт условия отсюда.
 */
export interface SearchConditions {
  searchId: string;
  text: string;
  /** Короткая подпись запроса для строки состояния: «БДД» или начало текста новости. */
  label: string;
  kind: QueryKind;
  period: Period;
  region: Region;
  mode: SearchMode;
  /** Сколько источников из списка участвовало (для `my-sources`); `null` — режим «везде». */
  sourceCount: number | null;
  platforms: PlatformId[];
  /** Выбранное значение многозначного запроса, человеческой подписью. */
  meaningLabel: string | null;
  /** Когда поиск запущен. */
  startedAt: IsoDateTime;
  /** Когда поиск закончился (или остановлен); `null` — ещё идёт. */
  finishedAt: IsoDateTime | null;
  /** Это повтор недавнего поиска (П12). */
  repeatOf: string | null;
}

// ============================================================================
// Разбор поля запроса и «как система поняла тему»
// ============================================================================

/** Подсказка к полю запроса (НТ-21, П14, НТ-26). Показываем под полем, не мешая вводу. */
export interface QueryHint {
  code:
    | 'looks-like-link' // «Похоже, это ссылка. Вставьте текст новости»
    | 'too-short' // слишком короткий запрос
    | 'too-long' // больше лимита знаков (НТ-6)
    | 'region-in-text' // «в Красноярском крае» — это регион, а не слова для поиска
    | 'conversational' // «подбери, пожалуйста…» — разговорные обороты
    | 'time-words' // «на прошлой неделе» → предложить период
    | 'other-region'; // запрос про другой регион (НТ-26)
  /** Готовый текст подсказки простым языком. */
  message: string;
  /** Что можно сделать одной кнопкой (необязательно). */
  fix?: QueryHintFix;
}

export type QueryHintFix =
  | { type: 'replace-text'; label: string; text: string }
  | { type: 'set-period'; label: string; period: Period };

/** Вариант значения многозначного запроса («Енисей» — река или хоккейный клуб). */
export interface QueryMeaning {
  id: string;
  label: string;
  description: string;
}

/** Результат разбора поля запроса. Сервер не меняет текст сам — только предлагает. */
export interface QueryAnalysis {
  text: string;
  kind: QueryKind;
  hints: QueryHint[];
  /** Уточнение многозначного запроса (П14). `null` — запрос однозначный. */
  ambiguity: { question: string; options: QueryMeaning[] } | null;
}

/** Грань темы: что входит или что не то. */
export interface TopicFacet {
  id: string;
  label: string;
  /** Пример формулировки из постов, по которой понятно, о чём грань. */
  example?: string;
  /** Сколько публикаций отсекла грань «не то» (если уже известно). */
  cutCount?: number;
  /** Кто добавил грань: система или пользователь (после правки). */
  origin: 'system' | 'user';
}

/** Признаки события (Р5, шаг 3 воронки): кто, где, когда, какие числа. */
export interface EventSigns {
  who: string[];
  where: string[];
  when: string[];
  numbers: string[];
}

/**
 * «Как система поняла тему» (ТЗ-Ф7, Р5, П14, SC-14). Карточку составляет нейросеть
 * один раз на запрос; пользователь может перенести грани между «входит» и «не то».
 */
export interface TopicUnderstanding {
  /** Одна фраза: о чём ищем. */
  summary: string;
  includes: TopicFacet[];
  excludes: TopicFacet[];
  /** Для события и текста новости — признаки события. */
  signs: EventSigns | null;
  /**
   * Кто составил карточку. `rules` — нейросеть недоступна, карточка собрана по словам
   * запроса; тогда в `note` объяснение («смысловая проверка недоступна»).
   */
  madeBy: 'ai' | 'rules';
  note: string | null;
  /** Примеры отсечённых публикаций — чтобы было видно ловушку (пожарная безопасность). */
  cutExamples: { headline: string; reason: string }[];
}

// ============================================================================
// Площадки: статусы и свежесть (НТ-3, НТ-4, НТ-5)
// ============================================================================

/** Счётчик хода по площадке: «VK: 18 из 40 групп» (НТ-2). */
export interface ProgressCounter {
  done: number;
  total: number;
  /** Что считаем: группы и каналы из списка или страницы общего поиска. */
  unit: 'sources' | 'pages';
}

/**
 * Свежесть данных площадки (НТ-4). Например, MAX ищется через сторонний индекс:
 * «публикации последних ~24 часов могут не найтись».
 */
export interface DataFreshness {
  /** Задержка индекса, часы. */
  delayHours: number;
  /** Текст для пользователя. */
  note: string;
}

/** Потолок выдачи площадки (SC-16): площадка отдала не больше `limit` результатов. */
export interface PlatformCap {
  limit: number;
  note: string;
}

/** Проблема площадки: что случилось и можно ли повторить. */
export interface PlatformProblem {
  code:
    | 'unavailable' // площадка не отвечает
    | 'timeout' // не уложилась во время
    | 'bad-response' // ответ не удалось разобрать: это ошибка, а не «0 найдено» (НТ-5)
    | 'rate-limited' // площадка ограничила частоту запросов (SC-49)
    | 'key-invalid' // ключ доступа недействителен (SC-46)
    | 'quota-exhausted' // кончилась квота (SC-46)
    | 'sources-closed'; // часть групп закрыта или удалена (НТ-17)
  /** Текст для пользователя простым языком. */
  message: string;
  /** Можно ли нажать «Повторить» по площадке (ТЗ-Ф44). */
  retryable: boolean;
}

/**
 * Статус площадки — полный набор (НТ-3). У каждого состояния свой текст и значок
 * (см. src/lib/labels.ts), не только цвет.
 * - `waiting` — ещё не начали;
 * - `searching` — идёт поиск, есть счётчик хода;
 * - `found` — найдено N;
 * - `nothing` — ничего не найдено (это не ошибка, ТЗ-Ф43);
 * - `partial` — частично: k из n источников и причина;
 * - `error` — ошибка, найденное до сбоя сохранено, есть «Повторить»;
 * - `no-access` — нет доступа (ключ, квота);
 * - `stopped` — пользователь остановил поиск.
 * «Данные с задержкой» — не отдельное состояние, а `freshness` поверх любого из них.
 */
export type PlatformState =
  'waiting' | 'searching' | 'found' | 'nothing' | 'partial' | 'error' | 'no-access' | 'stopped';

export interface PlatformStatus {
  platform: PlatformId;
  state: PlatformState;
  /** Сколько публикаций этой площадки в подборке (без исключённых). */
  found: number;
  /** Ход поиска; есть у `searching`, `partial`, `stopped`. */
  progress: ProgressCounter | null;
  /** Есть у `partial`, `error`, `no-access`. */
  problem: PlatformProblem | null;
  /** Задержка данных (НТ-4); `null` — данные свежие. */
  freshness: DataFreshness | null;
  /** Потолок выдачи (SC-16); `null` — не упёрлись. */
  cap: PlatformCap | null;
  /** Когда площадка последний раз ответила. */
  updatedAt: IsoDateTime | null;
  /**
   * Площадка отвечает записанными примерами (демо): её публикации вымышлены, ссылок нет.
   * У живой площадки поля нет.
   */
  demo?: boolean;
}

// ============================================================================
// Источники (ТЗ-Ф15, Ф16; П9, П13; НТ-14)
// ============================================================================

/** Тип источника (П13). Подписи — src/lib/labels.ts. */
export type SourceType =
  | 'media' // СМИ
  | 'authority' // органы власти края
  | 'municipal' // администрации городов и районов
  | 'institution' // учреждения: школы, больницы, театры
  | 'community' // паблики и сообщества
  | 'blogger'; // личные блоги и каналы

/** Краткая ссылка на источник внутри публикации. */
export interface SourceRef {
  id: string;
  platform: PlatformId;
  name: string;
  url: string;
  type: SourceType;
  /** Город или район края; `null` — не определён. */
  district: string | null;
  /** Подписчики по данным площадки (НТ-24); `null` — площадка не отдаёт. */
  subscribers: number | null;
  /** Входит ли источник в список пользователя (НТ-25: «в вашем списке / вне списка»). */
  inMySources: boolean;
  /** Источник из каталога краевых источников (основание «краевой источник», Р4). */
  regional: boolean;
}

/** Результат проверки источника по ссылке (П9). */
export interface SourceCheck {
  state:
    | 'ok' // открытая группа или канал, посты читаются
    | 'not-found' // по ссылке ничего нет
    | 'closed' // закрытая группа: посты не видны
    | 'not-supported' // ссылка не на VK, OK или MAX
    | 'duplicate' // уже есть в списке
    | 'not-regional' // источник не про край — можно добавить, но предупреждаем
    | 'post-link'; // ссылка на пост, а не на группу: `preview` — группа, где он вышел
  message: string;
  /**
   * Что удалось узнать об источнике (для `ok`, `not-regional`, `duplicate`).
   * Для `post-link` — группа или канал, где опубликован пост (если удалось узнать):
   * её адрес `preview.url` можно проверить и добавить.
   */
  preview: {
    platform: PlatformId;
    name: string;
    url: string;
    subscribers: number | null;
    lastPostAt: IsoDateTime | null;
    suggestedType: SourceType;
    suggestedDistrict: string | null;
  } | null;
  checkedAt: IsoDateTime;
}

/** Источник в списке пользователя. */
export interface Source extends SourceRef {
  /** Откуда взялся: добавлен вручную, из каталога или импортом из Excel. */
  origin: 'manual' | 'catalog' | 'import';
  addedAt: IsoDateTime;
  /** Последняя проверка доступности. */
  check: SourceCheck;
}

/** Данные для добавления или правки источника. */
export interface SourceInput {
  url: string;
  name?: string;
  type?: SourceType;
  district?: string | null;
}

/** Как сервер понял колонку файла импорта (SC-11). */
export interface ImportColumn {
  /** Буква колонки: `A`, `B`… */
  letter: string;
  /** Заголовок колонки из первой строки. */
  title: string;
  /** `url` — ссылки (по ним добавляем), `name` — названия, `ignored` — не используем. */
  role: 'url' | 'name' | 'ignored';
  /** Пояснение простым языком: «ссылки — по ним добавляем». */
  note: string;
}

/** Что будет со строкой файла. Тот же итог потом вернёт `importSources`. */
export type ImportRowOutcome =
  /** Добавим. `note` — что поправили в ссылке: «мобильная ссылка — привели к обычной». */
  | { kind: 'add'; source: SourceRef; note: string | null }
  /** Уже в списке — не трогаем. */
  | { kind: 'duplicate'; source: SourceRef }
  /** Пропустим с причиной. */
  | { kind: 'skip'; reason: string }
  | { kind: 'empty' };

export interface ImportRow {
  /** Номер строки в файле (первая — заголовок). */
  row: number;
  /** Значение колонки со ссылками как есть (с пробелами). */
  value: string;
  /** Значение колонки с названием. */
  title: string;
  outcome: ImportRowOutcome;
}

/**
 * Предпросмотр импорта (ТЗ-Ф16, SC-11): сервер разобрал файл, но ещё ничего не
 * добавил. Добавление — `importSources(previewId)`: ровно строки `add` этого разбора.
 */
export interface ImportPreview {
  previewId: string;
  fileName: string;
  sheetName: string;
  /** Строк в файле вместе с заголовком. */
  totalRows: number;
  /** Первая строка — заголовок (её не добавляем). */
  headerRow: number | null;
  columns: ImportColumn[];
  rows: ImportRow[];
  counts: { add: number; duplicate: number; skip: number; empty: number };
}

/** Итог импорта списка из Excel (ТЗ-Ф16). После предпросмотра совпадает с ним. */
export interface ImportReport {
  added: Source[];
  /** Строки, которые уже были в списке: их не трогали. */
  duplicates: { row: number; value: string; name: string }[];
  /** Строки, которые не вошли, с причиной. */
  skipped: { row: number; value: string; reason: string }[];
}

/** Итог перепроверки всего списка источников (П9, НТ-17). */
export interface SourcesRecheckReport {
  checkedAt: IsoDateTime;
  checked: number;
  /** Доступны и читаются. */
  ok: number;
  /** Источники, по которым поиск сейчас невозможен или есть предупреждение. */
  problems: { sourceId: string; name: string; state: SourceCheck['state']; message: string }[];
  /** Список после проверки (у каждого обновлён `check`). */
  sources: Source[];
}

/** Источник готового каталога краевых источников (НТ-14). */
export interface CatalogSource extends SourceRef {
  /** Короткое описание: «новости Норильска и Таймыра». */
  description: string;
}

/** Состояние рабочего места при открытии: первый запуск и пример запроса (НТ-14, SC-30). */
export interface StartState {
  /** Список источников пуст: предлагаем каталог и режим «везде». */
  firstRun: boolean;
  sourcesCount: number;
  /** Режим по умолчанию: при пустом списке — `everywhere`. */
  defaultMode: SearchMode;
  /** Пример запроса для пустого поля (placeholder). */
  exampleQuery: string;
  /** Период по умолчанию. */
  defaultPeriod: Period;
  region: Region;
}

// ============================================================================
// Рабочее место без регистрации (Р8)
// ============================================================================

/**
 * Личное рабочее место на сервере (Р8). Создаётся само при первом входе, ключ
 * запоминается в браузере. В нём — список источников, недавние поиски, исключения
 * и подборки; другие рабочие места их не видят (НТ-7). Каталог края общий.
 */
export interface Workspace {
  id: string;
  createdAt: IsoDateTime;
  sourcesCount: number;
  recentCount: number;
}

/**
 * Ссылка-ключ «Открыть на другом компьютере или в расширении» (Р8). Кто знает
 * ссылку, тот видит и меняет это рабочее место — поэтому ключ неугадываемый.
 */
export interface WorkspaceLink {
  workspaceId: string;
  /** Ключ из ссылки: его передают в `openWorkspace`. */
  key: string;
  /** Готовая ссылка для копирования. */
  url: string;
  createdAt: IsoDateTime;
}

// ============================================================================
// Публикация — единица учёта (НТ-13, ТЗ-Ф29, Ф30)
// ============================================================================

/**
 * Ключ публикации: площадка + владелец + номер поста. Разные адреса одного поста
 * (vk.com, vk.ru, m.vk.com, `?w=wall…`) приводятся к одному ключу и дают одну запись.
 */
export interface PostKey {
  platform: PlatformId;
  ownerId: string;
  postId: string;
}

/** Предложение текста поста: границы в символах (`text.slice(start, end)`). */
export interface Sentence {
  /** Номер предложения с нуля. На него ссылается доказательство (Р5, НТ-8). */
  index: number;
  start: number;
  end: number;
}

/** Отрезок текста поста для подсветки: `text.slice(start, end)`. */
export interface TextRange {
  start: number;
  end: number;
}

/** Насколько можно верить времени публикации (П4). */
export type TimeReliability =
  | 'exact' // время отдала площадка
  | 'approximate' // вычислено (MAX: из номера поста) — «время приблизительное»
  | 'unknown'; // даты нет — «дата неизвестна» (ТЗ-Ф36)

/** Проверка ссылки после поиска (НТ-19, SC-69). */
export interface LinkCheck {
  state: 'ok' | 'deleted' | 'not-checked';
  checkedAt: IsoDateTime | null;
}

/**
 * Публикация — пост на площадке, как его получил сервер. Все поля только из записи
 * поста (Р5, К14): нейросеть их не пишет.
 */
export interface Publication {
  /** Строковый ключ `vk:-100123_4567`; совпадает с `PostKey`. */
  id: string;
  key: PostKey;
  platform: PlatformId;
  source: SourceRef;
  /** Прямая ссылка на пост, построенная сервисом из ключа. */
  url: string;
  /** Другие адреса этого же поста, которые склеены в одну запись (НТ-13). */
  mergedUrls: string[];
  /** Заголовок поста, если площадка его отдаёт (статья, видео); иначе `null`. */
  title: string | null;
  /** «Заголовок или начало поста» для карточки (ТЗ-Ф34): `title` или начало текста. */
  headline: string;
  headlineFrom: 'title' | 'text';
  /** Полный текст поста; `null` — «текст отсутствует» (пост из картинок или видео, НТ-13). */
  text: string | null;
  /** Разбиение текста на предложения; пусто, если текста нет. */
  sentences: Sentence[];
  /** Время публикации; `null` — «дата неизвестна» (ТЗ-Ф36). */
  publishedAt: IsoDateTime | null;
  timeReliability: TimeReliability;
  /** Пост редактировался после публикации (П4). */
  edited: boolean;
  /** Репост: своего текста нет или он короткий (НТ-13). */
  repostOf: { sourceName: string; url: string } | null;
  /** Есть вложения: картинки или видео. Текст на картинках не анализируется. */
  hasMedia: boolean;
  /** Просмотры по данным площадки; `null` — «нет данных» (не 0!, НТ-24). */
  views: number | null;
  /** Реакции (лайки) по данным площадки; `null` — нет данных. */
  reactions: number | null;
  /** Когда сервер получил пост (НТ-19): «получено в 14:32». */
  fetchedAt: IsoDateTime;
  linkCheck: LinkCheck;
  /**
   * Публикация из записанных примеров (демо): источник вымышлен, ссылки на пост нет —
   * карточка показывает «демо-публикация, ссылки нет», в XLSX вместо ссылки та же пометка.
   * У живых публикаций поля нет.
   */
  demo?: boolean;
}

// ============================================================================
// Проверка текста на ИИ (04-decisions.md, «Проверка текста на ИИ» и уточнение)
// ============================================================================

/**
 * Уровень проверки текста на ИИ. Проценты не показываем — только уровень
 * (research/ai-text-detection.md §3). Подписи — src/lib/ai-check.ts.
 * - `likely-ai` — «похоже на ИИ»: score ≥ 0,85;
 * - `signs` — «есть признаки ИИ»: score ≥ 0,60;
 * - `unlikely` — «не похоже на ИИ»: ниже 0,60;
 * - `too-short` — меньше 40 слов: «мало текста для оценки», модель не вызывали;
 * - `unavailable` — модель не ответила. Это НЕ «не похоже»: «проверка недоступна».
 * Пороги — `AI_THRESHOLDS` в src/lib/ai-check.ts (потом откалибруем на своём эталоне).
 */
export type AiLevel = 'likely-ai' | 'signs' | 'unlikely' | 'too-short' | 'unavailable';

/**
 * Результат проверки текста на ИИ. Один и тот же текст всегда даёт один и тот же результат —
 * в отдельной проверке, в подборке и в «Распространении»: текст нормализуется одной функцией
 * (src/lib/ai-normalize.ts), ключ — `textHash` + `model`, первый результат кэшируется.
 * Это оценка модели, а не доказательство: метка ни на что не влияет (не исключает пост,
 * не меняет метку связи, в XLSX не идёт).
 */
export interface AiCheck {
  level: AiLevel;
  /**
   * Оценка модели 0..1 («вероятность ИИ» по мнению модели, не калиброванная).
   * `null` для `too-short` и `unavailable`. В интерфейсе по умолчанию не показываем.
   */
  score: number | null;
  /** Модель и её версия: `gigacheck-classifier-multi@…`; в имитации — `demo`. */
  model: string;
  /** SHA-256 (hex, нижний регистр) нормализованного текста в UTF-8. */
  textHash: string;
  /** Слов в нормализованном тексте (части между пробелами). */
  words: number;
  /** Когда текст проверили впервые (результат из кэша сохраняет это время). */
  checkedAt: IsoDateTime;
}

// ============================================================================
// Запись подборки: публикация + почему она здесь
// ============================================================================

/** Метка связи с запросом (ТЗ-Ф47, Р9). Подписи: «Прямо», «Косвенно», «Спорно — проверьте». */
export type Relevance = 'direct' | 'indirect' | 'disputed';

/**
 * Метод отбора (Р9, Р5):
 * - `copy` — копия: текст совпадает (шаг 1 воронки);
 * - `semantic` — найдено по смыслу (шаг 2);
 * - `ai-confirmed` — подтверждено ИИ (шаг 4);
 * - `ai-unchecked` — не проверено ИИ: нейросеть недоступна или ответила не по схеме (SC-08);
 * - `manual` — добавлено пользователем по ссылке (П8).
 */
export type SelectionMethod = 'copy' | 'semantic' | 'ai-confirmed' | 'ai-unchecked' | 'manual';

/** Тип размещения (П2): дословно / сокращено / пересказ / репост. Для поиска по тексту новости. */
export type PlacementType = 'verbatim' | 'shortened' | 'retold' | 'repost';

/**
 * Почему пост краевой (Р4). Хотя бы одно: источник краевой, источник в списке
 * пользователя (режим «Мои источники») или в тексте упоминается место края.
 * Подпись: «краевой источник · в вашем списке · упоминается: Норильск».
 */
export interface RegionReason {
  regionalSource: boolean;
  /**
   * Пост прошёл, потому что источник в списке пользователя: в режиме «Мои источники»
   * регион не проверяем — человек выбрал источники сам. В режиме «Везде» всегда `false`.
   */
  inMySources: boolean;
  /** Места края, упомянутые в тексте, в именительном падеже: «Норильск», «Канский район». */
  places: string[];
}

/**
 * Доказательство связи (Р5, П3, НТ-8): номер предложения, по которому решили,
 * и отрезки для подсветки. Номер всегда указывает на существующее предложение.
 */
export interface Evidence {
  /** Номер предложения в `publication.sentences`. */
  sentenceIndex: number;
  /**
   * Что подсвечиваем: само предложение или фразы, совпавшие с текстом релиза.
   * Отрезки — в координатах `publication.text`.
   */
  ranges: TextRange[];
  /** Откуда доказательство: решение нейросети, совпадение с релизом, близость по смыслу. */
  basis: 'ai' | 'release-match' | 'semantic';
  /** Пояснение простым языком: «совпадают место, дата и участники». */
  note: string | null;
}

/** Выдержка из оригинала (ТЗ-Ф34): всегда подстрока `publication.text`. */
export interface Excerpt {
  start: number;
  end: number;
  /** То же, что `publication.text.slice(start, end)`. */
  text: string;
  /** Выдержка начинается не с начала текста / заканчивается не в конце — ставим «…». */
  cutStart: boolean;
  cutEnd: boolean;
}

/** Полнота цитирования релиза (П1): доля текста релиза, вошедшая дословно. */
export interface Citation {
  /** Доля от 0 до 1: «перепечатано 72%». */
  share: number;
  /** Какие фрагменты (абзацы) релиза вошли дословно — для карты фрагментов. */
  fragmentIds: string[];
}

/** Запись подборки. Каждое размещение — отдельная запись (ТЗ-Ф29). */
export interface ResultItem {
  /** Совпадает с `publication.id`. */
  id: string;
  publication: Publication;
  relevance: Relevance;
  method: SelectionMethod;
  /** Пояснение к методу: «смысловая проверка недоступна» и т.п. */
  methodNote: string | null;
  regionReason: RegionReason;
  /** Выдержка; `null` — текста нет. */
  excerpt: Excerpt | null;
  /** Доказательство; `null` — подсвечивать нечего (нет текста). */
  evidence: Evidence | null;
  /** Тип размещения (П2) — при поиске по тексту новости и внутри групп копий; иначе `null`. */
  placementType: PlacementType | null;
  /** Это первоисточник релиза (П4). */
  isOriginal: boolean;
  /** Полнота цитирования — только при поиске по тексту новости (П1). */
  citation: Citation | null;
  /** Группа, в которую входит запись (Р9); `null` — вне групп. */
  groupId: string | null;
  /** Пользователь исключил запись («не то», ТЗ-Ф48). Исключённые не идут в XLSX. */
  excluded: boolean;
  /** Новая по сравнению с прежним запуском того же поиска (П12). */
  isNew: boolean;
  /** Порядковый номер прихода в ходе поиска: для «+5 новых — показать» (НТ-2). */
  arrival: number;
  /**
   * Проверка текста поста на ИИ. Нет — пост без текста или проверка ещё не дошла.
   * Метку в карточке показываем только для `likely-ai` и `signs`.
   */
  aiCheck?: AiCheck;
}

/**
 * Группа размещений (Р9): «Релиз „Новая школа в Норильске“ — 15 размещений».
 * Каждое размещение остаётся отдельной записью со своей ссылкой (ТЗ-Ф29, Ф31).
 */
export interface ResultGroup {
  id: string;
  /** «Релиз „Новая школа в Норильске“» */
  title: string;
  kind: 'release' | 'copies';
  itemIds: string[];
  /** id записи-первоисточника. */
  originalItemId: string | null;
  countsByPlatform: Record<PlatformId, number>;
  /** Счётчики по типам размещения в шапке группы (П2). */
  countsByType: Record<PlacementType, number>;
}

/** Счётчики подборки. Считаются БЕЗ исключённых записей. */
export interface SelectionCounts {
  total: number;
  excluded: number;
  byRelevance: Record<Relevance, number>;
  byPlatform: Record<PlatformId, number>;
  /** Только для поиска по тексту новости; иначе нули. */
  byPlacementType: Record<PlacementType, number>;
  /** Сколько записей новые (П12). */
  new: number;
  /** Сколько записей с проверкой на ИИ «похоже на ИИ» (`likely-ai`) — фильтр «Похоже на ИИ». */
  aiLikely: number;
  /** Сколько записей с уровнем «есть признаки ИИ» (`signs`). */
  aiSigns: number;
}

/** Пометка к подборке: ограничения и объяснения (ТЗ-Ф41, НТ-13, НТ-26, SC-16). */
export interface SelectionNotice {
  code:
    | 'other-region' // «Поиск ограничен Красноярским краем» (НТ-26)
    | 'platform-cap' // площадка упёрлась в потолок выдачи (SC-16)
    | 'ai-unavailable' // смысловая проверка недоступна (SC-08)
    | 'images-not-analyzed' // текст на картинках не анализируется (НТ-13)
    | 'undated-included'; // посты без даты показаны с пометкой (ТЗ-Ф36)
  tone: 'info' | 'warning';
  message: string;
}

/** Подборка — результат поиска, как его видит пользователь. */
export interface Selection {
  searchId: string;
  conditions: SearchConditions;
  /** Статус каждой площадки из полного набора (НТ-3). */
  statuses: PlatformStatus[];
  items: ResultItem[];
  groups: ResultGroup[];
  counts: SelectionCounts;
  topic: TopicUnderstanding | null;
  notices: SelectionNotice[];
  /** Доступна ли смысловая проверка (нейросеть). */
  aiAvailable: boolean;
  /** Поиск идёт / закончен / остановлен пользователем. */
  phase: 'running' | 'done' | 'stopped';
}

// ============================================================================
// Ход поиска — поток событий (НТ-2, НТ-6, НТ-23)
// ============================================================================

/** Почему поиск не состоялся целиком (ошибка всего поиска, не одной площадки). */
export interface ApiError {
  code:
    | 'offline' // нет связи с интернетом у пользователя (НТ-23)
    | 'too-many-requests' // слишком много поисков с одного адреса (НТ-6, SC-58)
    | 'too-long' // текст запроса длиннее лимита (НТ-6)
    | 'not-found' // поиск, запись или пост по ссылке не найдены
    | 'invalid' // данные не прошли проверку: ссылка на закрытую группу, не та площадка
    | 'server'; // прочая ошибка сервера
  message: string;
  /** Через сколько секунд имеет смысл повторить. */
  retryAfterSec?: number;
  /**
   * Отказ «уже идёт поиск» (`too-many-requests`, один поиск на рабочее место): id того
   * поиска — к нему можно подключиться (`attachSearch`) и показать его ход или остановить.
   */
  runningSearchId?: string;
}

/**
 * Событие хода поиска. Порядок типичного потока:
 * `queued`* → `started` → `topic` → (`platform` | `items`)* → `finished`.
 * При остановке — `stopped`, при общей ошибке — `failed`.
 */
export type SearchEvent =
  /** Очередь к нейросети или к поиску (НТ-6): «вы в очереди, перед вами 2 поиска». */
  | { type: 'queued'; ahead: number; etaSec: number }
  /** Поиск начался; условия выполненного поиска (НТ-1). */
  | { type: 'started'; conditions: SearchConditions; statuses: PlatformStatus[] }
  /** Карточка «как система поняла тему». */
  | { type: 'topic'; topic: TopicUnderstanding }
  /** Обновился статус или счётчик хода площадки: «VK: 18 из 40». */
  | { type: 'platform'; status: PlatformStatus; currentSource: string | null }
  /** Пришли новые записи. Не сдвигайте то, что человек читает: «+5 новых — показать». */
  | { type: 'items'; items: ResultItem[]; groups: ResultGroup[]; counts: SelectionCounts }
  /** Нейросеть недоступна: спорные получат «не проверено ИИ» (SC-08). */
  | { type: 'ai-unavailable'; message: string }
  /** Пропала связь у пользователя; поиск продолжается на сервере (НТ-23). */
  | { type: 'connection-lost'; message: string }
  /** Связь вернулась; накопленное придёт следующим событием `items`. */
  | { type: 'connection-restored'; message: string }
  /** Поиск закончен. Итоговая подборка. */
  | { type: 'finished'; selection: Selection }
  /** Поиск остановлен пользователем. Найденное сохранено. */
  | { type: 'stopped'; selection: Selection }
  /** Поиск не состоялся. */
  | { type: 'failed'; error: ApiError };

/**
 * Запущенный поиск. Поток событий можно читать двумя способами:
 * - `for await (const e of run) {…}` — AsyncIterable;
 * - `run.subscribe(listener)` — подписка (удобно в React).
 * Оба способа сначала отдают уже случившиеся события, потом новые.
 */
export interface SearchRun extends AsyncIterable<SearchEvent> {
  readonly searchId: string;
  /** Подписаться на события. Возвращает функцию отписки. */
  subscribe(listener: (event: SearchEvent) => void): () => void;
  /** Остановить поиск: найденное сохраняется, придёт событие `stopped`. */
  stop(): void;
  /** Поток закончился (`finished`, `stopped` или `failed`). */
  readonly closed: boolean;
}

// ============================================================================
// Распространение новости (Р10, П1, П4, П5, П6)
// ============================================================================

/** Фрагмент (абзац) текста релиза для карты фрагментов (П1). */
export interface ReleaseFragment {
  id: string;
  index: number;
  text: string;
  /** Сколько размещений взяли этот абзац дословно. */
  takenBy: number;
}

/** Пометки к «Первым опубликовал» (П4). */
export interface OriginNote {
  code:
    | 'approximate-time' // время вычислено (MAX — из номера поста)
    | 'edited' // пост редактировался
    | 'first-among-found'; // первый среди найденного, а не обязательно первый вообще
  message: string;
}

/** Строка таблицы размещений. Ссылается на запись подборки. */
export interface SpreadPlacement {
  itemId: string;
  platform: PlatformId;
  sourceName: string;
  publishedAt: IsoDateTime | null;
  timeReliability: TimeReliability;
  /** Подписчики источника по данным площадки; `null` — нет данных. */
  subscribers: number | null;
  /** Просмотры поста; `null` — нет данных (OK не отдаёт). */
  views: number | null;
  placementType: PlacementType;
  isOriginal: boolean;
  citationShare: number;
  url: string;
  /**
   * Проверка текста размещения на ИИ — та же, что у записи подборки (`ResultItem.aiCheck`).
   * Метку показываем только у пересказов: копия релиза получает оценку самого релиза.
   */
  aiCheck?: AiCheck;
}

/** Точка волны распространения (П6). */
export interface WavePoint {
  /** Начало интервала. */
  start: IsoDateTime;
  count: number;
  byPlatform: Record<PlatformId, number>;
}

/** Честная метрика охвата (П5, НТ-24): цифра, полнота и как посчитано. */
export interface ReachMetric {
  /** Значение; `null` — нет данных ни по одному размещению. */
  value: number | null;
  /** По скольким размещениям или источникам есть данные. */
  withData: number;
  of: number;
  /** «Сумма подписчиков; одни и те же люди могут быть в разных группах». */
  howCounted: string;
}

/** Сводка распространения новости. Никаких AVE, индексов и суммарного «охвата» (П5). */
export interface SpreadReport {
  searchId: string;
  groupId: string;
  /** «Новая школа в Норильске» */
  title: string;
  release: {
    text: string;
    fragments: ReleaseFragment[];
  };
  original: {
    itemId: string;
    sourceName: string;
    platform: PlatformId;
    publishedAt: IsoDateTime | null;
    timeReliability: TimeReliability;
    notes: OriginNote[];
  };
  totals: {
    placements: number;
    byPlatform: Record<PlatformId, number>;
    byType: Record<PlacementType, number>;
  };
  /** Аудитория источников: сумма подписчиков, отдельно от просмотров. */
  audience: ReachMetric;
  /** Просмотры размещений по данным площадок. */
  views: ReachMetric;
  /** Волна по часам и по дням (П6). */
  wave: { hourly: WavePoint[]; daily: WavePoint[] };
  /** Хронология и таблица (сортирует интерфейс). */
  placements: SpreadPlacement[];
  /**
   * Сводка проверки на ИИ — только по пересказам (не исходный, `placementType: 'retold'`):
   * «похожи на ИИ: `likelyAi` из `retold` пересказов». `likelyAi` — уровень `likely-ai`.
   * Нет поля — проверка на ИИ ещё не подключена: строку не показываем.
   */
  aiRetold?: { likelyAi: number; retold: number };
  /** Данные на момент. */
  computedAt: IsoDateTime;
}

// ============================================================================
// Выгрузка XLSX (ТЗ-Ф37, Ф38; НТ-10, НТ-11, НТ-20)
// ============================================================================

/**
 * Что попадает в файл (НТ-11): подборка минус исключённые. Фильтр вида на файл
 * не влияет, если пользователь явно не выбрал «только отфильтрованное».
 */
export interface ExportOptions {
  /** Явно выгрузить только эти метки; не задано — все. */
  onlyRelevance?: Relevance[];
}

export interface ExportColumn {
  id: string;
  title: string;
}

/** Ячейка: всегда текст или число; формулы не допускаются (НТ-10). */
export type ExportCell = string | number | null;

export interface ExportSheetTable {
  name: string;
  columns: ExportColumn[];
  /** Первые строки для предпросмотра. */
  rows: ExportCell[][];
  /** Всего строк на листе. */
  totalRows: number;
}

/** Лист «Сводка» (НТ-20, П7): условия, статусы, время поиска, число записей. */
export interface ExportSummarySheet {
  name: string;
  entries: { label: string; value: string }[];
}

/** Предпросмотр файла: лист «Сводка» и первые строки «Публикаций». */
export interface ExportPreview {
  searchId: string;
  fileName: string;
  /** Записей в файле — это число на кнопке «Скачать XLSX — N записей» (НТ-11). */
  rowCount: number;
  excludedCount: number;
  /** Правило выгрузки простым языком. */
  rule: string;
  /** Применённый явный фильтр; `null` — выгружается вся подборка. */
  appliedFilter: Relevance[] | null;
  summary: ExportSummarySheet;
  publications: ExportSheetTable;
  /** Подпись часового пояса для файла (НТ-12). */
  timeZoneNote: string;
}

/** Готовый файл выгрузки (ТЗ-Ф38): та же подборка, что на экране и в предпросмотре. */
export interface ExportFile {
  /** Имя для сохранения: тема, дата и время поиска — выгрузки в «Загрузках» не путаются. */
  fileName: string;
  rowCount: number;
  /** Сам файл XLSX */
  file: Blob;
}

// ============================================================================
// Недавние поиски (П12) и проверка ссылок (НТ-19)
// ============================================================================

export interface RecentSearch {
  /** id выполненного поиска; его передают в `SearchRequest.repeatOf`. */
  searchId: string;
  conditions: SearchConditions;
  /** Сколько нашли тогда. */
  total: number;
  /** Краткий итог площадок тогда, например «MAX: ошибка». */
  statusSummary: string;
  /** Чтобы повторить, нужен исходный запрос целиком. */
  request: SearchRequest;
}

export interface LinkRecheckReport {
  checked: number;
  ok: number;
  /** Записи, чьи посты удалены после поиска: «удалён после поиска». */
  deletedItemIds: string[];
  checkedAt: IsoDateTime;
}

// ============================================================================
// Состояние стенда (П9, НТ-18) — для дежурного
// ============================================================================

export type HealthState = 'ok' | 'degraded' | 'down';

export interface Quota {
  used: number;
  limit: number;
  /** «в месяц», «в сутки», «кредитов» */
  unit: string;
  resetsAt: IsoDateTime | null;
}

export interface StandStatus {
  checkedAt: IsoDateTime;
  overall: HealthState;
  platforms: {
    platform: PlatformId;
    state: HealthState;
    message: string;
    /** Как ищем на площадке: «VK API», «веб-поиск OK», «индекс MaxStat». */
    via: string;
    /** Задержка данных площадки (НТ-4): MAX ищется через индекс с отставанием ~24 ч. */
    freshness: DataFreshness | null;
    quota: Quota | null;
    lastSuccessAt: IsoDateTime | null;
  }[];
  ai: {
    state: HealthState;
    /** «GigaChat 3.1 Lightning, локально» */
    model: string;
    /** Модель прогрета и готова отвечать (НТ-18). */
    warm: boolean;
    queueLength: number;
    avgSecondsPerPost: number | null;
  };
  queue: { running: number; waiting: number; perClientLimit: number };
  memory: { usedMb: number; totalMb: number };
  /** Последние события для дежурного. */
  events: { at: IsoDateTime; level: 'info' | 'warning' | 'error'; message: string }[];
  version: string;
}

/** Состояние связи с сервером (НТ-23). */
export type ConnectionState = 'online' | 'offline';
