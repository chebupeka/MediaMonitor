/**
 * Интерфейс сервера Медиамонитора — `MonitorApi`.
 *
 * Его реализуют имитация (src/api/fake) и HTTP-клиент настоящего сервера (src/api/http.ts).
 * Экраны получают реализацию через `import { api } from '@/api'` и не
 * знают, какая она. Все методы асинхронные; ошибки — `ApiError` (reject),
 * сбои площадок — внутри статусов, а не исключениями (ТЗ-Ф42).
 */
import type {
  AiCheck,
  ApiError,
  CatalogSource,
  ConnectionState,
  ExportFile,
  ExportOptions,
  ExportPreview,
  ImportPreview,
  ImportReport,
  LinkRecheckReport,
  PlatformId,
  QueryAnalysis,
  RecentSearch,
  ResultItem,
  SearchRequest,
  SearchRun,
  Selection,
  SelectionCounts,
  Source,
  SourceCheck,
  SourceInput,
  SourcesRecheckReport,
  SpreadReport,
  StandStatus,
  StartState,
  TopicCorrection,
  TopicUnderstanding,
  Workspace,
  WorkspaceLink,
} from './types';

export interface MonitorApi {
  // ---------------------------------------------------------------- старт
  /** Состояние при открытии: первый запуск, пример запроса, период по умолчанию (НТ-14). */
  getStartState(): Promise<StartState>;

  // ---------------------------------------------------------------- запрос
  /** Разобрать поле запроса: подсказки и уточнение многозначного (НТ-21, П14, НТ-26). */
  analyzeQuery(text: string): Promise<QueryAnalysis>;

  /**
   * «Как система поняла тему» до поиска (ТЗ-Ф7, Р5). Можно передать выбранное
   * значение многозначного запроса и уже сделанные правки.
   */
  understandTopic(
    text: string,
    options?: { meaningId?: string; correction?: TopicCorrection },
  ): Promise<TopicUnderstanding>;

  // ---------------------------------------------------------------- поиск
  /**
   * Запустить поиск. Возвращает сразу; ход — потоком событий (НТ-2).
   * Ошибки всего поиска приходят событием `failed`, а не исключением.
   */
  startSearch(request: SearchRequest): SearchRun;

  /** Остановить поиск по id (то же, что `run.stop()`). */
  stopSearch(searchId: string): Promise<void>;

  /** Повторить одну площадку после сбоя (ТЗ-Ф44). Новые записи придут в потоке. */
  retryPlatform(searchId: string, platform: PlatformId): SearchRun;

  /** Текущая подборка поиска (снимок). */
  getSelection(searchId: string): Promise<Selection>;

  /** Исключить записи или вернуть их (ТЗ-Ф48). Возвращает пересчитанные счётчики. */
  setExcluded(searchId: string, itemIds: string[], excluded: boolean): Promise<SelectionCounts>;

  /** Исключить все записи источника одним действием (НТ-25). */
  excludeSource(
    searchId: string,
    sourceId: string,
  ): Promise<{ itemIds: string[]; counts: SelectionCounts }>;

  /** Добавить публикацию по ссылке вручную (П8). */
  addByUrl(searchId: string, url: string): Promise<ResultItem>;

  /** Перепроверить ссылки перед выгрузкой (НТ-19): какие посты удалены после поиска. */
  recheckLinks(searchId: string): Promise<LinkRecheckReport>;

  // ---------------------------------------------------------------- распространение
  /**
   * Сводка распространения новости (Р10). `groupId` — группа-релиз из подборки
   * поиска по тексту новости; не задан — первая такая группа.
   */
  getSpread(searchId: string, groupId?: string): Promise<SpreadReport>;

  // ---------------------------------------------------------------- проверка на ИИ
  /**
   * Проверить текст на ИИ (правый клик «Проверить текст на ИИ», экран «Проверка на ИИ»).
   * Тот же текст (после нормализации, src/lib/ai-normalize.ts) всегда даёт тот же результат,
   * что и `ResultItem.aiCheck` в подборке. Меньше 40 слов — `too-short`; модель не ответила —
   * `unavailable` (не ошибка). Ошибка — только у самого вызова: нет связи, лимит.
   */
  checkAiText(text: string): Promise<AiCheck>;

  // ---------------------------------------------------------------- выгрузка
  /** Предпросмотр XLSX: лист «Сводка» и первые строки (НТ-11, НТ-20). */
  getExportPreview(searchId: string, options?: ExportOptions): Promise<ExportPreview>;

  /** Сам файл XLSX: листы «Сводка» и «Публикации» целиком, ссылки кликабельные. */
  getExportFile(searchId: string, options?: ExportOptions): Promise<ExportFile>;

  // ---------------------------------------------------------------- источники
  listSources(): Promise<Source[]>;
  /** Проверить ссылку перед добавлением (П9). */
  checkSource(url: string): Promise<SourceCheck>;
  addSource(input: SourceInput): Promise<Source>;
  updateSource(id: string, patch: Partial<Omit<SourceInput, 'url'>>): Promise<Source>;
  /** Удалить источник. Удаление можно отменить через `restoreSource` (НТ-7). */
  removeSource(id: string): Promise<void>;
  restoreSource(id: string): Promise<Source>;
  /** Перепроверить весь список: доступность каждого источника (П9, НТ-17). */
  recheckSources(): Promise<SourcesRecheckReport>;
  /**
   * Разобрать файл Excel или CSV и показать, что будет со строками, — ничего не
   * добавляя (ТЗ-Ф16, SC-11). В мокапе файл не читается: отдаются строки демо-файла.
   */
  previewImport(file: File): Promise<ImportPreview>;
  /**
   * Импорт из Excel (ТЗ-Ф16). `previewId` из `previewImport` — добавить ровно строки
   * «добавим» этого разбора (итог совпадает с предпросмотром). Файл — разобрать и сразу
   * добавить, без предпросмотра.
   */
  importSources(source: File | string): Promise<ImportReport>;
  /** Готовый каталог краевых источников (НТ-14). */
  getCatalog(): Promise<CatalogSource[]>;
  addFromCatalog(ids: string[]): Promise<Source[]>;

  // ---------------------------------------------------------------- рабочее место (Р8)
  /** Текущее рабочее место; создаётся само при первом входе. */
  getWorkspace(): Promise<Workspace>;
  /** Ссылка-ключ «Открыть на другом компьютере или в расширении». */
  getWorkspaceLink(): Promise<WorkspaceLink>;
  /** Открыть рабочее место по ключу или ссылке целиком. Неизвестный ключ — `not-found`. */
  openWorkspace(key: string): Promise<Workspace>;

  // ---------------------------------------------------------------- недавние
  listRecent(): Promise<RecentSearch[]>;

  // ---------------------------------------------------------------- стенд
  getStandStatus(): Promise<StandStatus>;

  // ---------------------------------------------------------------- связь
  /** Есть ли связь с сервером (НТ-23). */
  getConnection(): ConnectionState;
  /** Подписка на изменения связи. Возвращает функцию отписки. */
  onConnectionChange(listener: (state: ConnectionState) => void): () => void;
}

/**
 * Ошибка вызова API. Методы `MonitorApi` отклоняют промис именно ею:
 * `catch (e) { if (isApiError(e)) show(e.message) }`.
 */
export class MonitorApiError extends Error implements ApiError {
  readonly code: ApiError['code'];
  readonly retryAfterSec?: number;

  constructor(code: ApiError['code'], message: string, retryAfterSec?: number) {
    super(message);
    this.name = 'MonitorApiError';
    this.code = code;
    if (retryAfterSec !== undefined) this.retryAfterSec = retryAfterSec;
  }
}

/** Проверка, что значение — ошибка контракта (для catch). */
export function isApiError(value: unknown): value is ApiError {
  if (value instanceof MonitorApiError) return true;
  return (
    typeof value === 'object' &&
    value !== null &&
    'code' in value &&
    'message' in value &&
    typeof (value as { message: unknown }).message === 'string'
  );
}

/** Текст ошибки для пользователя из чего угодно, что прилетело в catch. */
export function errorMessage(value: unknown): string {
  if (isApiError(value)) return value.message;
  return 'Что-то пошло не так. Повторите действие.';
}
