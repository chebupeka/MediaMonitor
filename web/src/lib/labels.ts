/**
 * Подписи для значений контракта — простым языком, без жаргона (ТЗ-Н4, Н5).
 * Один источник правды для всех экранов, XLSX и расширения.
 */
import type {
  PeriodPreset,
  PlacementType,
  PlatformId,
  PlatformStatus,
  QueryKind,
  RegionReason,
  Relevance,
  SearchMode,
  SelectionMethod,
  SourceType,
  TimeReliability,
} from '@/api/types';
import { formatNumber } from './format';

// ---------------------------------------------------------------- площадки

export interface PlatformMeta {
  id: PlatformId;
  /** «ВКонтакте», «Сайты СМИ» */
  name: string;
  /** «VK», «Сайты» */
  short: string;
  /** Одна публикация — для строки выгрузки: «ВКонтакте», «Сайт СМИ» */
  itemName: string;
  /** CSS-переменная цвета площадки */
  colorVar: string;
}

/**
 * Порядок площадок: обязательные по ТЗ (VK, OK, MAX), затем дополнительные — сайты СМИ
 * края и их каналы на Дзене. Какие из них включены на сервере — `StartState.platforms`.
 */
export const PLATFORM_ORDER: readonly PlatformId[] = ['vk', 'ok', 'max', 'site', 'dzen'];

export const PLATFORMS: Record<PlatformId, PlatformMeta> = {
  vk: {
    id: 'vk',
    name: 'ВКонтакте',
    short: 'VK',
    itemName: 'ВКонтакте',
    colorVar: 'var(--color-vk)',
  },
  ok: {
    id: 'ok',
    name: 'Одноклассники',
    short: 'OK',
    itemName: 'Одноклассники',
    colorVar: 'var(--color-ok)',
  },
  max: { id: 'max', name: 'MAX', short: 'MAX', itemName: 'MAX', colorVar: 'var(--color-max)' },
  site: {
    id: 'site',
    name: 'Сайты СМИ',
    short: 'Сайты',
    itemName: 'Сайт СМИ',
    colorVar: 'var(--color-site)',
  },
  dzen: {
    id: 'dzen',
    name: 'Дзен',
    short: 'Дзен',
    itemName: 'Дзен',
    colorVar: 'var(--color-dzen)',
  },
};

// ---------------------------------------------------------------- метки и методы

export const RELEVANCE_ORDER: readonly Relevance[] = ['direct', 'indirect', 'disputed'];

export const RELEVANCE_LABEL: Record<Relevance, string> = {
  direct: 'Прямо',
  indirect: 'Косвенно',
  disputed: 'Спорно — проверьте',
};

export const RELEVANCE_SHORT: Record<Relevance, string> = {
  direct: 'Прямо',
  indirect: 'Косвенно',
  disputed: 'Спорно',
};

export const RELEVANCE_HINT: Record<Relevance, string> = {
  direct: 'Публикация прямо о теме запроса',
  indirect: 'Тема затронута или упомянута',
  disputed: 'Система не уверена — посмотрите сами',
};

export const METHOD_LABEL: Record<SelectionMethod, string> = {
  copy: 'копия',
  semantic: 'найдено по смыслу',
  'ai-confirmed': 'подтверждено ИИ',
  'ai-unchecked': 'не проверено ИИ',
  manual: 'добавлено вручную',
};

export const METHOD_HINT: Record<SelectionMethod, string> = {
  copy: 'Текст совпадает с другой найденной публикацией',
  semantic: 'Близко по смыслу к запросу, хотя слова могут отличаться',
  'ai-confirmed': 'Нейросеть прочитала пост и подтвердила связь с запросом',
  'ai-unchecked': 'Смысловая проверка недоступна: решите сами, подходит ли публикация',
  manual: 'Вы добавили публикацию по ссылке',
};

export const PLACEMENT_TYPE_ORDER: readonly PlacementType[] = [
  'verbatim',
  'shortened',
  'retold',
  'repost',
];

export const PLACEMENT_TYPE_LABEL: Record<PlacementType, string> = {
  verbatim: 'дословно',
  shortened: 'сокращено',
  retold: 'пересказ',
  repost: 'репост',
};

export const PLACEMENT_TYPE_HINT: Record<PlacementType, string> = {
  verbatim: 'Текст релиза целиком',
  shortened: 'Часть текста релиза дословно',
  retold: 'Та же новость своими словами: совпадают место, дата и участники',
  repost: 'Репост чужой публикации с этим текстом',
};

// ---------------------------------------------------------------- запрос

export const QUERY_KIND_LABEL: Record<QueryKind, string> = {
  topic: 'Тема',
  event: 'Событие или человек',
  'news-text': 'Текст новости',
};

export const MODE_LABEL: Record<SearchMode, string> = {
  'my-sources': 'Мои источники',
  everywhere: 'Везде',
};

export const MODE_HINT: Record<SearchMode, string> = {
  'my-sources': 'Только группы и каналы из вашего списка',
  everywhere: 'Все публичные посты, которые относятся к Красноярскому краю',
};

export const PERIOD_PRESET_LABEL: Record<PeriodPreset, string> = {
  today: 'Сегодня',
  '24h': '24 часа',
  '7d': '7 дней',
  '30d': '30 дней',
  custom: 'Свой период',
};

/** Как определяется регион (Р4) — одна фраза для пояснения у значка региона. */
export const REGION_PRINCIPLE =
  'Пост считается краевым, если его опубликовал краевой источник или в тексте упоминается место края: город, район, посёлок.';

// ---------------------------------------------------------------- источники

export const SOURCE_TYPE_LABEL: Record<SourceType, string> = {
  media: 'СМИ',
  authority: 'Органы власти',
  municipal: 'Администрация',
  institution: 'Учреждение',
  community: 'Сообщество',
  blogger: 'Блогер',
};

// ---------------------------------------------------------------- регион, время

/** «краевой источник · в вашем списке · упоминается: Норильск, Талнах» (как в XLSX сервера) */
export function regionReasonText(reason: RegionReason): string {
  const parts: string[] = [];
  if (reason.regionalSource) parts.push('краевой источник');
  if (reason.inMySources) parts.push('в вашем списке');
  if (reason.places.length > 0) parts.push(`упоминается: ${reason.places.join(', ')}`);
  return parts.join(' · ');
}

export const TIME_RELIABILITY_LABEL: Record<TimeReliability, string | null> = {
  exact: null,
  approximate: 'время приблизительное',
  unknown: 'дата неизвестна',
};

export const TIME_RELIABILITY_HINT: Record<TimeReliability, string | null> = {
  exact: null,
  approximate:
    'Площадка не отдала точное время, оно вычислено: у MAX — по номеру поста, у сайта СМИ известна только дата из поиска по сайту',
  unknown: 'Площадка не отдала дату. Попадание в период проверить нельзя',
};

// ---------------------------------------------------------------- статусы площадок (НТ-3)

/** Тон статуса: определяет цвет, но статус всегда читается по значку и тексту. */
export type StatusTone = 'neutral' | 'progress' | 'good' | 'info' | 'warning' | 'critical';

/** Ключ значка — сопоставление с иконками в src/components/StatusBadge.tsx. */
export type StatusIcon =
  | 'waiting'
  | 'progress'
  | 'check'
  | 'nothing'
  | 'warning'
  | 'error'
  | 'lock'
  | 'stopped'
  | 'delay'
  | 'info'
  | 'offline'
  | 'queue';

export interface StatusView {
  tone: StatusTone;
  icon: StatusIcon;
  /** Короткий текст рядом с названием площадки: «найдено 25», «ошибка». */
  text: string;
  /** Пояснение: причина, что делать. Показываем в подсказке или под статусом. */
  detail: string | null;
  /** Показывать ли кнопку «Повторить». */
  retry: boolean;
}

/** Единица хода поиска по источникам: «Проверено 12 из 43 сайтов». */
const SOURCE_UNIT: Record<PlatformId, string> = {
  vk: 'групп и каналов',
  ok: 'групп и каналов',
  max: 'групп и каналов',
  site: 'сайтов',
  dzen: 'каналов',
};

/** Как показать статус площадки (полный набор, НТ-3). */
export function platformStatusView(status: PlatformStatus): StatusView {
  const { progress, problem } = status;
  const progressText = progress
    ? `${formatNumber(progress.done)} из ${formatNumber(progress.total)}`
    : '';
  switch (status.state) {
    case 'waiting':
      return { tone: 'neutral', icon: 'waiting', text: 'ожидает', detail: null, retry: false };
    case 'searching':
      return {
        tone: 'progress',
        icon: 'progress',
        text: progress && progress.total > 0 ? `ищем: ${progressText}` : 'ищем',
        detail: progress
          ? progress.unit === 'sources'
            ? `Проверено ${progressText} ${SOURCE_UNIT[status.platform]}`
            : `Просмотрено ${progressText} страниц поиска`
          : null,
        retry: false,
      };
    case 'found':
      return {
        tone: 'good',
        icon: 'check',
        text: `найдено ${formatNumber(status.found)}`,
        detail: status.cap?.note ?? null,
        retry: false,
      };
    case 'nothing':
      return {
        tone: 'neutral',
        icon: 'nothing',
        text: progress && progress.total === 0 ? 'нет источников в списке' : 'ничего не найдено',
        detail:
          progress && progress.total === 0
            ? 'В вашем списке нет источников этой площадки'
            : 'Площадка ответила, подходящих публикаций нет. Это не ошибка',
        retry: false,
      };
    case 'partial':
      return {
        tone: 'warning',
        icon: 'warning',
        text: `частично: ${progressText}`,
        detail: problem?.message ?? null,
        retry: problem?.retryable ?? false,
      };
    case 'error':
      return {
        tone: 'critical',
        icon: 'error',
        text: problem?.code === 'bad-response' ? 'ошибка обработки ответа' : 'ошибка',
        detail: problem?.message ?? null,
        retry: problem?.retryable ?? true,
      };
    case 'no-access':
      return {
        tone: 'critical',
        icon: 'lock',
        text: problem?.code === 'quota-exhausted' ? 'лимит на сегодня исчерпан' : 'нет доступа',
        detail: problem?.message ?? null,
        retry: problem?.retryable ?? false,
      };
    case 'stopped':
      return {
        tone: 'neutral',
        icon: 'stopped',
        text: progress ? `остановлено: ${progressText}` : 'остановлено',
        detail: 'Поиск остановлен. Найденное до остановки сохранено',
        retry: true,
      };
  }
}

/** Пометка «данные с задержкой» (НТ-4) — отдельно от состояния. */
export function freshnessView(status: PlatformStatus): StatusView | null {
  if (!status.freshness) return null;
  return {
    tone: 'info',
    icon: 'delay',
    text: `данные с задержкой до ~${status.freshness.delayHours} ч`,
    detail: status.freshness.note,
    retry: false,
  };
}
