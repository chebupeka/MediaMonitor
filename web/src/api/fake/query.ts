/**
 * Разбор поля запроса в имитации (НТ-21, П14, НТ-26) и выбор демо-набора.
 *
 * Какой набор отдаёт имитация (см. web/README.md, «Демо-данные»):
 * - сценарий «Пусто» → пусто; сценарий «500 результатов» → 500 записей на любой запрос;
 * - запрос про другой регион (Новосибирск, Иркутск…) → пусто с пояснением о рамках края;
 * - «школ» + «Норильск» (например, текст релиза) → релиз «Новая школа в Норильске»;
 * - БДД, ДТП, пешеход, водитель, дорожн… → тема «Безопасность дорожного движения»;
 * - Енисей, ледостав, навигация → событие с уточнением;
 * - всё остальное → пусто.
 */
import type {
  Period,
  QueryAnalysis,
  QueryHint,
  QueryKind,
  SelectionNotice,
  TopicUnderstanding,
} from '../types';
import { addDays, demoNowMs, krskDate } from './clock';
import { buildBdd } from './datasets/bdd';
import { EVENT_MEANINGS, buildEvent } from './datasets/event';
import { buildLarge } from './datasets/large';
import { buildRelease } from './datasets/release';
import type { Dataset } from './datasets/types';
import type { DemoScenario } from './scenario';

export const MAX_QUERY_LENGTH = 20_000;

const LINK_RE = /^\s*(https?:\/\/|www\.|vk\.com\/|ok\.ru\/|max\.ru\/)\S*\s*$/iu;
const REGION_RE =
  /\s*(?:в|по)\s+(?:красноярском\s+крае|красноярскому\s+краю|нашем\s+крае|крае)(?=[\s,.!?]|$)/giu;
const CONVERSATIONAL_RE =
  /^\s*(?:пожалуйста[,\s]+)?(?:подбери|найди|покажи|собери|поищи|нужны|нужно найти)(?:те)?(?:[,\s]+пожалуйста)?[,:\s]+(?:мне\s+)?(?:все\s+)?(?:публикации|посты|новости)?\s*(?:про|о|об|по)?\s*/iu;
const TIME_RE =
  /\s*(?:за\s+)?(?:на\s+прошлой\s+неделе|последн(?:юю|ие)\s+(?:неделю|7\s+дней)|за\s+неделю|за\s+месяц|последний\s+месяц|сегодня|вчера)/iu;
const OTHER_REGION_RE =
  /(новосибирск|иркутск|омск|томск|кемеров|москв|петербург|барнаул|абакан|хакаси|тыв[аеуы]|кузбасс|якут|бурят)/iu;
const KRAI_PLACE_RE =
  /(красноярск|норильск|ачинск|канск|минусинск|лесосибирск|железногорск|зеленогорск|шарыпов|дивногорск|енисейск|дудинк|таймыр|эвенки|богучан|назаров|боготол|сосновоборск|край)/iu;

const BDD_RE =
  /(бдд|дтп|дорожн|пешеход|водител|светофор|автомобил|гололёд|гололед|госавтоинспекц|гибдд)/iu;
const EVENT_RE = /(енисе|ледостав|навигаци|северн\w*\s+завоз)/iu;
const AMBIGUOUS_RE = /^\s*енисей\s*$/iu;

function today(): string {
  return krskDate(demoNowMs());
}

export function presetPeriod(preset: Period['preset']): Period {
  const t = today();
  switch (preset) {
    case 'today':
      return { preset, from: t, to: t };
    case '24h':
      return { preset, from: addDays(t, -1), to: t };
    case '7d':
      return { preset, from: addDays(t, -6), to: t };
    case '30d':
    case 'custom':
      return { preset, from: addDays(t, -29), to: t };
  }
}

export function detectKind(text: string): QueryKind {
  const trimmed = text.trim();
  const sentences = trimmed.split(/[.!?…]+\s/u).filter(Boolean).length;
  if (trimmed.length > 240 || sentences >= 3) return 'news-text';
  if (EVENT_RE.test(trimmed)) return 'event';
  return 'topic';
}

export function isOtherRegion(text: string): boolean {
  return OTHER_REGION_RE.test(text) && !KRAI_PLACE_RE.test(text);
}

export function analyze(text: string): QueryAnalysis {
  const trimmed = text.trim();
  const hints: QueryHint[] = [];

  if (trimmed.length > MAX_QUERY_LENGTH) {
    hints.push({
      code: 'too-long',
      message: `Текст длиннее ${MAX_QUERY_LENGTH.toLocaleString('ru-RU')} знаков. Оставьте главное: заголовок и первые абзацы.`,
    });
  }
  if (LINK_RE.test(trimmed)) {
    hints.push({
      code: 'looks-like-link',
      message: 'Похоже, это ссылка. Вставьте текст новости или опишите тему словами.',
    });
  } else if (trimmed.length > 0 && trimmed.length < 3) {
    hints.push({
      code: 'too-short',
      message: 'Слишком короткий запрос. Добавьте пару слов о теме.',
    });
  }

  const withoutRegion = trimmed
    .replace(REGION_RE, '')
    .replace(/\s{2,}/gu, ' ')
    .trim();
  if (withoutRegion !== trimmed && withoutRegion.length > 0) {
    hints.push({
      code: 'region-in-text',
      message:
        'Регион уже выбран: Красноярский край. Слова «в Красноярском крае» искать не нужно — без них найдётся больше.',
      fix: { type: 'replace-text', label: 'Убрать из запроса', text: withoutRegion },
    });
  }

  if (CONVERSATIONAL_RE.test(trimmed)) {
    const cleaned = trimmed.replace(CONVERSATIONAL_RE, '').trim();
    if (cleaned.length > 0 && cleaned !== trimmed) {
      hints.push({
        code: 'conversational',
        message: 'Достаточно написать тему: просьбы вроде «подбери, пожалуйста» можно опустить.',
        fix: { type: 'replace-text', label: `Оставить «${cleaned}»`, text: cleaned },
      });
    }
  }

  const timeMatch = TIME_RE.exec(trimmed);
  if (timeMatch) {
    const words = timeMatch[0].toLowerCase();
    const preset: Period['preset'] = /сегодня/u.test(words)
      ? 'today'
      : /вчера/u.test(words)
        ? '24h'
        : /месяц/u.test(words)
          ? '30d'
          : '7d';
    const period = presetPeriod(preset);
    hints.push({
      code: 'time-words',
      message: 'Период лучше задать кнопками ниже — так поиск будет точнее.',
      fix: { type: 'set-period', label: `Поставить период «${timeMatch[0].trim()}»`, period },
    });
  }

  if (isOtherRegion(trimmed)) {
    hints.push({
      code: 'other-region',
      message:
        'Поиск ограничен Красноярским краем. Публикации о другом регионе найдутся, только если в них упоминается край.',
    });
  }

  const ambiguity = AMBIGUOUS_RE.test(trimmed)
    ? {
        question: 'Уточните, что ищем: «Енисей» — это и река, и спортивный клуб.',
        options: EVENT_MEANINGS.map((m) => ({
          id: m.id,
          label: m.label,
          description: m.description,
        })),
      }
    : null;

  return { text, kind: detectKind(trimmed), hints, ambiguity };
}

function genericTopic(text: string): TopicUnderstanding {
  const label = text.trim().length > 80 ? `${text.trim().slice(0, 80)}…` : text.trim();
  return {
    summary: `Публикации по запросу «${label}» в соцсетях Красноярского края.`,
    includes: [{ id: 'main', label: label || 'Запрос', origin: 'system' }],
    excludes: [],
    signs: null,
    madeBy: 'ai',
    note: null,
    cutExamples: [],
  };
}

function emptyDataset(text: string, notices: SelectionNotice[] = []): Dataset {
  return {
    id: 'empty',
    kind: detectKind(text),
    label: text.trim().length > 40 ? `${text.trim().slice(0, 40)}…` : text.trim(),
    items: [],
    optional: [],
    spare: [],
    groups: [],
    topic: genericTopic(text),
    release: null,
    notices,
  };
}

export function pickDataset(
  text: string,
  meaningId: string | undefined,
  scenario: DemoScenario,
): Dataset {
  if (scenario === 'empty') return emptyDataset(text);
  if (scenario === 'large') {
    const large = buildLarge();
    return { ...large, topic: buildBdd().topic };
  }
  if (isOtherRegion(text)) {
    return emptyDataset(text, [
      {
        code: 'other-region',
        tone: 'info',
        message:
          'Поиск ограничен Красноярским краем. Публикации о другом регионе попадают в подборку, только если в них упоминается край или их опубликовал краевой источник.',
      },
    ]);
  }
  if (/школ/iu.test(text) && /норильск/iu.test(text)) return buildRelease();
  if (BDD_RE.test(text)) return buildBdd();
  if (EVENT_RE.test(text)) return buildEvent(meaningId);
  return emptyDataset(text);
}

export function topicFor(text: string, meaningId: string | undefined): TopicUnderstanding {
  if (/школ/iu.test(text) && /норильск/iu.test(text))
    return buildRelease().topic ?? genericTopic(text);
  if (BDD_RE.test(text)) return buildBdd().topic ?? genericTopic(text);
  if (EVENT_RE.test(text)) return buildEvent(meaningId).topic ?? genericTopic(text);
  return genericTopic(text);
}
