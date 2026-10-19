/**
 * Набор 2. Текст релиза «Новая школа в Норильске»: 15 размещений (VK 9, OK 4, MAX 2)
 * с типами дословно / сокращено / пересказ / репост, полнотой цитирования и картой
 * фрагментов. Первоисточник — Пресс-центр края; у MAX время приблизительное (П4).
 * Плюс две записи вне группы: отклик и спорная — и отсечённая «похожая новость
 * о другом событии» (К17) в «как система поняла тему».
 */
import type { Citation, PlacementType, ResultGroup, TopicUnderstanding } from '../../types';
import { buildItem, type PostSpec } from '../build';
import type { Dataset, ReleaseMeta } from './types';

export const RELEASE_GROUP_ID = 'g-release-school';
export const RELEASE_TITLE = 'Новая школа в Норильске';

const P: string[][] = [
  [
    'В Норильске открылась новая школа на 1 100 мест.',
    'Здание построили в районе Оганер за два года по краевой программе строительства школ.',
  ],
  [
    'В школе 48 классов, два спортивных зала, бассейн и лаборатория робототехники.',
    'Для учеников из Талнаха организован школьный автобус.',
  ],
  [
    '«Это самая большая школа, построенная в Заполярье за последние тридцать лет», — рассказали в министерстве образования края.',
  ],
  [
    'Первые уроки в новом здании пройдут 20 октября.',
    'Запись продолжается: родители могут подать заявление через портал госуслуг.',
  ],
];

const paragraphText = (index: number): string => (P[index] ?? []).join(' ');
const RELEASE_TEXT = P.map((_, i) => paragraphText(i)).join('\n\n');
const RELEASE_LENGTH = P.reduce((sum, _, i) => sum + paragraphText(i).length, 0);

/** Текст релиза — для поиска по тексту новости (и демо-страницы СМИ). */
export const RELEASE_SOURCE_TEXT = RELEASE_TEXT;

function citation(paragraphs: number[], phrases: string[] = []): Citation {
  const covered =
    paragraphs.reduce((sum, i) => sum + paragraphText(i).length, 0) +
    phrases.reduce((sum, phrase) => sum + phrase.length, 0);
  return {
    share: Math.min(1, Math.round((covered / RELEASE_LENGTH) * 100) / 100),
    fragmentIds: paragraphs.map((i) => `p${i + 1}`),
  };
}

interface PlacementSpec {
  n: string;
  src: string;
  at: string;
  type: PlacementType;
  /** Абзацы релиза, вошедшие дословно */
  paragraphs?: number[];
  /** Своё вступление перед текстом релиза */
  intro?: string;
  /** Свой текст (пересказ) */
  own?: string[];
  /** Дословные фразы релиза внутри своего текста */
  phrases?: string[];
  views?: number | null;
  original?: boolean;
  repostOf?: { src: string; n: string };
  places: string[];
}

const TV_INTRO = 'Хорошие новости из Заполярья.';

const PLACEMENTS: PlacementSpec[] = [
  {
    n: '60210',
    src: 'vk-press-centre',
    at: '2026-10-14 10:02',
    type: 'verbatim',
    paragraphs: [0, 1, 2, 3],
    original: true,
    views: 6_100,
    places: ['Норильск'],
  },
  {
    n: '88015',
    src: 'vk-tv-kraya',
    at: '2026-10-14 10:40',
    type: 'verbatim',
    intro: TV_INTRO,
    paragraphs: [0, 1, 2, 3],
    views: 18_400,
    places: ['Норильск'],
  },
  {
    n: '3301',
    src: 'max-press',
    at: '2026-10-14 11:05',
    type: 'verbatim',
    paragraphs: [0, 1, 2, 3],
    views: 2_300,
    places: ['Норильск'],
  },
  {
    n: '77122',
    src: 'vk-portal-krsk',
    at: '2026-10-14 12:15',
    type: 'retold',
    own: [
      'Новая школа на 1 100 учеников заработала в Норильске.',
      'В здании есть бассейн, два спортзала и лаборатория робототехники.',
      'В министерстве образования края подчеркнули, что это самая большая школа, построенная в Заполярье за последние тридцать лет.',
      'Первые уроки в новом здании пройдут 20 октября.',
    ],
    phrases: [
      'самая большая школа, построенная в Заполярье за последние тридцать лет',
      'Первые уроки в новом здании пройдут 20 октября',
    ],
    views: 21_700,
    places: ['Норильск'],
  },
  {
    n: '30377',
    src: 'ok-novosti-kraya',
    at: '2026-10-14 12:50',
    type: 'verbatim',
    paragraphs: [0, 1, 2, 3],
    views: null,
    places: ['Норильск'],
  },
  {
    n: '70120',
    src: 'vk-adm-norilsk',
    at: '2026-10-14 14:30',
    type: 'retold',
    own: [
      'Сегодня в Норильске открыли новую школу в районе Оганер.',
      'В ней смогут учиться 1 100 ребят: для них подготовили 48 классов, бассейн и два спортзала.',
      'Ученики из Талнаха будут добираться на школьном автобусе.',
      'Ждём всех на первых уроках 20 октября!',
    ],
    phrases: ['в районе Оганер', '48 классов'],
    views: 9_800,
    places: ['Норильск', 'Талнах'],
  },
  {
    n: '64388',
    src: 'vk-portal-norilsk',
    at: '2026-10-14 16:10',
    type: 'shortened',
    paragraphs: [0, 1, 3],
    views: 7_200,
    places: ['Норильск'],
  },
  {
    n: '9011',
    src: 'ok-gazeta-taimyr',
    at: '2026-10-14 18:45',
    type: 'verbatim',
    paragraphs: [0, 1, 2, 3],
    views: null,
    places: ['Норильск'],
  },
  {
    n: '45601',
    src: 'vk-minobr',
    at: '2026-10-15 09:20',
    type: 'retold',
    own: [
      'В Норильске начала работу новая школа — самая большая в Заполярье за тридцать лет.',
      'Её построили за два года по краевой программе строительства школ.',
      'В здании 48 классов, бассейн и лаборатория робототехники.',
    ],
    phrases: [
      'по краевой программе строительства школ',
      '48 классов',
      'бассейн и лаборатория робототехники',
    ],
    views: 5_500,
    places: ['Норильск'],
  },
  {
    n: '2236',
    src: 'max-portal',
    at: '2026-10-15 11:00',
    type: 'retold',
    own: [
      'Северяне дождались: в Норильске открылась школа на 1 100 мест.',
      'Уроки начнутся 20 октября, запись ещё идёт через госуслуги.',
    ],
    phrases: ['школа на 1 100 мест'],
    views: 4_900,
    places: ['Норильск'],
  },
  {
    n: '26710',
    src: 'vk-zapolyarye',
    at: '2026-10-15 13:35',
    type: 'shortened',
    paragraphs: [0, 3],
    views: 3_100,
    places: ['Норильск'],
  },
  {
    n: '17802',
    src: 'ok-krasnoyarye',
    at: '2026-10-15 17:20',
    type: 'verbatim',
    paragraphs: [0, 1, 2, 3],
    views: null,
    places: ['Норильск'],
  },
  {
    n: '22140',
    src: 'vk-kansk',
    at: '2026-10-16 08:55',
    type: 'repost',
    intro: TV_INTRO,
    paragraphs: [0, 1, 2, 3],
    repostOf: { src: 'vk-tv-kraya', n: '88015' },
    views: 2_400,
    places: ['Норильск'],
  },
  {
    n: '71533',
    src: 'vk-parents',
    at: '2026-10-16 10:15',
    type: 'retold',
    own: [
      'Родители Норильска, новая школа в Оганере открыта!',
      'Запись продолжается: родители могут подать заявление через портал госуслуг.',
      'Кто уже записал детей — поделитесь, как всё прошло?',
    ],
    phrases: ['Запись продолжается: родители могут подать заявление через портал госуслуг.'],
    views: 2_900,
    places: ['Норильск'],
  },
  {
    n: '40790',
    src: 'ok-kansk',
    at: '2026-10-16 15:40',
    type: 'shortened',
    paragraphs: [0, 1],
    views: null,
    places: ['Норильск'],
  },
];

function toPostSpec(p: PlacementSpec): PostSpec {
  const text: string[][] = [];
  if (p.intro) text.push([p.intro]);
  (p.paragraphs ?? []).forEach((i) => text.push([...(P[i] ?? [])]));
  if (p.own) text.push(p.own);
  const verbatimMarks = (p.paragraphs ?? []).map(paragraphText);
  const marks = [...verbatimMarks, ...(p.phrases ?? [])];
  return {
    n: p.n,
    src: p.src,
    at: p.at,
    text,
    marks,
    basis: 'release-match',
    evNote: p.original
      ? 'Первоисточник: самая ранняя публикация этого текста среди найденного'
      : p.type === 'retold'
        ? 'Пересказ: совпадают место, дата и участники; подсвечены дословные фразы релиза'
        : 'Подсвечен текст, совпавший с релизом',
    rel: 'direct',
    m: p.type === 'retold' ? 'semantic' : 'copy',
    places: p.places,
    views: p.views,
    placement: p.type,
    original: p.original ?? false,
    citation: citation(p.paragraphs ?? [], p.phrases ?? []),
    group: RELEASE_GROUP_ID,
    ...(p.repostOf ? { repostOf: p.repostOf } : {}),
  };
}

const EXTRA: PostSpec[] = [
  {
    n: '64502',
    src: 'vk-portal-norilsk',
    at: '2026-10-17 12:00',
    text: [
      'В Норильске выбрали подрядчика для строительства ещё одной школы — в Талнахе.',
      'Её планируют открыть в 2028 году.',
      'Новая школа в районе Оганер, открытая на этой неделе, уже заполнена на 80%.',
    ],
    ev: 2,
    rel: 'indirect',
    m: 'semantic',
    places: ['Норильск', 'Талнах'],
    evNote: 'Упоминает новую школу, но главная новость — другая',
  },
  {
    n: '5160',
    src: 'max-norilsk',
    at: '2026-10-14 21:00',
    text: [
      'Читатели спрашивают, как будет ходить школьный автобус из Талнаха в новую школу.',
      'Расписание обещают опубликовать до 20 октября.',
    ],
    ev: 0,
    rel: 'disputed',
    m: 'ai-confirmed',
    places: ['Талнах'],
    evNote: 'Вопрос читателей о новой школе: отклик, а не перепечатка',
  },
];

const TOPIC: TopicUnderstanding = {
  summary:
    'Новость: в Норильске открылась новая школа на 1 100 мест в районе Оганер; первые уроки — 20 октября. Ищем перепечатки, сокращения и пересказы.',
  includes: [
    {
      id: 'same-event',
      label: 'Перепечатки, сокращения и пересказы этой новости',
      origin: 'system',
    },
    { id: 'reactions', label: 'Отклики и вопросы о новой школе', origin: 'system' },
  ],
  excludes: [
    {
      id: 'other-schools',
      label: 'Другие школы края: открытия и ремонты',
      example: '«В Ачинске после ремонта открылась школа № 3»',
      cutCount: 4,
      origin: 'system',
    },
    {
      id: 'norilsk-other',
      label: 'Другие новости Норильска',
      example: '«стартовал набор в кружки робототехники»',
      cutCount: 7,
      origin: 'system',
    },
  ],
  signs: {
    who: ['Министерство образования края', 'Пресс-центр края'],
    where: ['Норильск', 'район Оганер', 'Талнах'],
    when: ['14 октября 2026', 'первые уроки 20 октября'],
    numbers: ['1 100 мест', '48 классов', 'за два года'],
  },
  madeBy: 'ai',
  note: null,
  cutExamples: [
    {
      headline: 'В Ачинске после ремонта открылась школа № 3',
      reason: 'Похожая новость о другом событии: другая школа и другой город',
    },
    {
      headline: 'В Норильске стартовал набор в кружки робототехники',
      reason: 'Другая новость Норильска',
    },
  ],
};

export const RELEASE_META: ReleaseMeta = {
  title: RELEASE_TITLE,
  text: RELEASE_TEXT,
  fragments: P.map((_, i) => ({ id: `p${i + 1}`, index: i, text: paragraphText(i) })),
};

export function buildRelease(): Dataset {
  const placements = PLACEMENTS.map((p) => buildItem(toPostSpec(p)));
  const group: ResultGroup = {
    id: RELEASE_GROUP_ID,
    title: `Релиз «${RELEASE_TITLE}»`,
    kind: 'release',
    itemIds: [],
    originalItemId: placements[0]?.item.id ?? null,
    countsByPlatform: { vk: 0, ok: 0, max: 0 },
    countsByType: { verbatim: 0, shortened: 0, retold: 0, repost: 0 },
  };
  return {
    id: 'release',
    kind: 'news-text',
    label: RELEASE_TITLE,
    items: [...placements, ...EXTRA.map(buildItem)],
    optional: [],
    spare: [],
    groups: [group],
    topic: TOPIC,
    release: RELEASE_META,
  };
}
