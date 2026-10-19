/**
 * Набор 3. Событие с уточнением: запрос «Енисей» многозначный — река (навигация,
 * ледостав) или спортивный клуб. Небольшой набор: 8 записей про реку и 3 про клуб.
 */
import type { TopicUnderstanding } from '../../types';
import { buildItem, type PostSpec } from '../build';
import type { Dataset } from './types';

export const EVENT_MEANINGS = [
  {
    id: 'river',
    label: 'Река Енисей',
    description: 'Навигация, северный завоз, ледостав, переправы',
  },
  {
    id: 'club',
    label: 'Спортивный клуб «Енисей»',
    description: 'Новости клуба, матчи, детская школа',
  },
  { id: 'all', label: 'Всё со словом «Енисей»', description: 'Без уточнения: и река, и клуб' },
] as const;

const RIVER: PostSpec[] = [
  {
    n: '4410',
    src: 'vk-rech-port',
    at: '2026-10-12 10:00',
    text: [
      'Навигация на Енисее подходит к концу: последний пассажирский теплоход из Красноярска в Дудинку ушёл 12 октября.',
      'Обратно в краевой центр судно вернётся к 22 октября.',
      'Билетов на этот рейс больше нет.',
    ],
    ev: 0,
    rel: 'direct',
    m: 'ai-confirmed',
    places: ['Красноярск', 'Дудинка'],
    facets: ['river'],
  },
  {
    n: '87790',
    src: 'vk-tv-kraya',
    at: '2026-10-13 18:30',
    text: [
      'На Енисее в районе Туруханска появились первые забереги.',
      'Синоптики ожидают, что ледостав на севере края начнётся на неделю раньше обычного.',
      'Речники торопятся завершить северный завоз.',
    ],
    ev: 1,
    rel: 'direct',
    m: 'semantic',
    places: ['Туруханск'],
    facets: ['river'],
    views: 16_300,
  },
  {
    n: '5121',
    src: 'max-norilsk',
    at: '2026-10-15 09:40',
    text: [
      'В Дудинку пришло последнее в этом сезоне судно с продуктами для Таймыра.',
      'Северный завоз по Енисею завершён, следующие грузы придут уже по зимнику.',
    ],
    ev: 1,
    rel: 'direct',
    m: 'semantic',
    places: ['Дудинка', 'Таймыр'],
    facets: ['river'],
    views: 6_700,
  },
  {
    n: '61290',
    src: 'vk-lesosib',
    at: '2026-10-16 12:00',
    text: [
      'В Лесосибирске до ледостава закрыли паромную переправу через Енисей.',
      'Жителей правобережья будут возить на катерах на воздушной подушке.',
    ],
    ev: 0,
    rel: 'direct',
    m: 'semantic',
    places: ['Лесосибирск'],
    facets: ['river'],
  },
  {
    n: '9077',
    src: 'ok-gazeta-taimyr',
    at: '2026-10-17 15:00',
    text: [
      'Ледостав на Енисее у Дудинки ожидается в последних числах октября.',
      'Выходить на молодой лёд опасно: его толщина пока меньше пяти сантиметров.',
    ],
    ev: 0,
    rel: 'direct',
    m: 'ai-confirmed',
    places: ['Дудинка'],
    facets: ['river'],
  },
  {
    n: '6688',
    src: 'vk-eniseysk',
    at: '2026-10-18 11:20',
    text: [
      'В Енисейске на берегу реки поставили знаки «Выход на лёд запрещён».',
      'Спасатели будут патрулировать берег, пока лёд не окрепнет.',
    ],
    ev: 0,
    rel: 'indirect',
    m: 'semantic',
    places: ['Енисейск'],
    facets: ['river'],
  },
  {
    n: '77610',
    src: 'vk-portal-krsk',
    at: '2026-10-19 10:15',
    text: [
      'Почему Енисей в Красноярске не замерзает зимой?',
      'Объясняем вместе с гидрологами: дело в плотине ГЭС и тёплой воде из глубины водохранилища.',
    ],
    ev: 0,
    rel: 'indirect',
    m: 'semantic',
    places: ['Красноярск'],
    facets: ['river'],
    views: 27_400,
  },
  {
    n: '4490',
    src: 'max-tv',
    at: '2026-10-18 20:30',
    text: [
      'Пока нет ледовых переправ, в посёлки Туруханского района летают дополнительные авиарейсы.',
      'Расписание публикует районная администрация.',
    ],
    ev: 0,
    rel: 'disputed',
    m: 'semantic',
    places: ['Туруханский район'],
    facets: ['river'],
  },
];

const CLUB: PostSpec[] = [
  {
    n: '30110',
    src: 'vk-sport-krai',
    at: '2026-10-14 19:00',
    text: [
      'Спортивный клуб «Енисей» открыл набор в детскую школу хоккея с мячом.',
      'Занятия бесплатные, форму выдают.',
    ],
    ev: 0,
    rel: 'direct',
    m: 'semantic',
    facets: ['club'],
  },
  {
    n: '30188',
    src: 'vk-sport-krai',
    at: '2026-10-17 12:00',
    text: [
      'Болельщики «Енисея» смогут купить билеты на домашние матчи сезона онлайн.',
      'Продажи стартуют 1 ноября.',
    ],
    ev: 0,
    rel: 'direct',
    m: 'semantic',
    facets: ['club'],
  },
  {
    n: '30455',
    src: 'ok-novosti-kraya',
    at: '2026-10-18 16:00',
    text: [
      'Игроки клуба «Енисей» провели открытую тренировку для школьников Красноярска.',
      'Ребята получили автографы и сфотографировались с командой.',
    ],
    ev: 0,
    rel: 'direct',
    m: 'semantic',
    places: ['Красноярск'],
    facets: ['club'],
  },
];

const RIVER_TOPIC: TopicUnderstanding = {
  summary: 'Река Енисей: завершение навигации, северный завоз, ледостав и переправы.',
  includes: [
    { id: 'navigation', label: 'Навигация и теплоходы', origin: 'system' },
    { id: 'delivery', label: 'Северный завоз', origin: 'system' },
    { id: 'ice', label: 'Ледостав и безопасность на льду', origin: 'system' },
    { id: 'crossings', label: 'Переправы и авиарейсы вместо них', origin: 'system' },
  ],
  excludes: [
    { id: 'club', label: 'Спортивный клуб «Енисей»', cutCount: 3, origin: 'system' },
    {
      id: 'names',
      label: 'Улицы, магазины и компании со словом «Енисей»',
      cutCount: 9,
      origin: 'system',
    },
  ],
  signs: {
    who: ['речники', 'спасатели', 'синоптики'],
    where: ['Енисей', 'Красноярск — Дудинка', 'Лесосибирск', 'Туруханский район'],
    when: ['октябрь 2026'],
    numbers: ['последний рейс 12 октября', 'лёд тоньше 5 см'],
  },
  madeBy: 'ai',
  note: null,
  cutExamples: [
    {
      headline: 'Спортивный клуб «Енисей» открыл набор в детскую школу',
      reason: 'Другое значение: спортивный клуб',
    },
  ],
};

const CLUB_TOPIC: TopicUnderstanding = {
  summary: 'Спортивный клуб «Енисей»: новости клуба, матчи, детская школа.',
  includes: [{ id: 'club', label: 'Новости клуба и матчи', origin: 'system' }],
  excludes: [{ id: 'river', label: 'Река Енисей', cutCount: 8, origin: 'system' }],
  signs: null,
  madeBy: 'ai',
  note: null,
  cutExamples: [
    {
      headline: 'Ледостав на Енисее у Дудинки ожидается в конце октября',
      reason: 'Другое значение: река',
    },
  ],
};

export function buildEvent(meaningId: string | undefined): Dataset {
  const river = RIVER.map(buildItem);
  const club = CLUB.map(buildItem);
  const items = meaningId === 'club' ? club : meaningId === 'river' ? river : [...river, ...club];
  const topic: TopicUnderstanding =
    meaningId === 'club'
      ? CLUB_TOPIC
      : meaningId === 'river'
        ? RIVER_TOPIC
        : {
            ...RIVER_TOPIC,
            summary: 'Всё со словом «Енисей»: и река (навигация, ледостав), и спортивный клуб.',
            includes: [
              ...RIVER_TOPIC.includes,
              { id: 'club', label: 'Спортивный клуб «Енисей»', origin: 'system' },
            ],
            excludes: RIVER_TOPIC.excludes.filter((f) => f.id !== 'club'),
          };
  return {
    id: 'event',
    kind: 'event',
    label:
      meaningId === 'club' ? '«Енисей» (клуб)' : meaningId === 'river' ? 'Енисей (река)' : 'Енисей',
    items,
    optional: [],
    spare: [],
    groups: [],
    topic,
    release: null,
  };
}
