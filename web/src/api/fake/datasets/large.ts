/**
 * Набор 4. 500 результатов для проверки большого объёма (К26, SC-16). Записи
 * собираются детерминированно из шаблонов по теме БДД: одинаковые при каждом запуске.
 * У Одноклассников — потолок выдачи площадки.
 */
import type { PlatformId, Relevance, SelectionMethod } from '../../types';
import { buildItem, type PostSpec } from '../build';
import { SOURCE_SEEDS } from '../sources';
import type { Dataset } from './types';

/** Детерминированный генератор псевдослучайных чисел (mulberry32). */
function rng(seed: number): () => number {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

interface City {
  nom: string;
  loc: string;
}

const CITIES: City[] = [
  { nom: 'Красноярск', loc: 'В Красноярске' },
  { nom: 'Норильск', loc: 'В Норильске' },
  { nom: 'Ачинск', loc: 'В Ачинске' },
  { nom: 'Канск', loc: 'В Канске' },
  { nom: 'Минусинск', loc: 'В Минусинске' },
  { nom: 'Лесосибирск', loc: 'В Лесосибирске' },
  { nom: 'Железногорск', loc: 'В Железногорске' },
  { nom: 'Зеленогорск', loc: 'В Зеленогорске' },
  { nom: 'Шарыпово', loc: 'В Шарыпово' },
  { nom: 'Назарово', loc: 'В Назарово' },
  { nom: 'Дивногорск', loc: 'В Дивногорске' },
  { nom: 'Боготол', loc: 'В Боготоле' },
  { nom: 'Сосновоборск', loc: 'В Сосновоборске' },
  { nom: 'Енисейск', loc: 'В Енисейске' },
  { nom: 'Дудинка', loc: 'В Дудинке' },
  { nom: 'Уяр', loc: 'В Уяре' },
  { nom: 'Заозёрный', loc: 'В Заозёрном' },
  { nom: 'Бородино', loc: 'В Бородино' },
  { nom: 'Ужур', loc: 'В Ужуре' },
  { nom: 'Емельяново', loc: 'В Емельяново' },
];

const STREETS = [
  'Ленина',
  'Мира',
  'Советской',
  'Победы',
  'Гагарина',
  'Строителей',
  'Октябрьской',
  'Комсомольской',
  'Северной',
  'Школьной',
];
const RAIDS = [
  '«Нетрезвый водитель»',
  '«Внимание, дети!»',
  '«Пешеход»',
  '«Тонировка»',
  '«Автобус»',
];

type Template = (city: City, r: () => number) => string;
const pick = <T>(list: readonly T[], r: () => number): T =>
  list[Math.floor(r() * list.length)] as T;

const LEADS: Record<Relevance, Template[]> = {
  direct: [
    (c, r) => `${c.loc} водитель сбил пешехода на переходе по улице ${pick(STREETS, r)}.`,
    (c, r) =>
      `${c.loc} столкнулись два автомобиля, пострадали ${2 + Math.floor(r() * 3)} человека.`,
    (c, r) => `${c.loc} инспекторы Госавтоинспекции провели рейд ${pick(RAIDS, r)}.`,
    (c) => `${c.loc} у школы обновили разметку «зебра» и поставили новые знаки.`,
    (c, r) => `${c.loc} за неделю задержали ${3 + Math.floor(r() * 12)} нетрезвых водителей.`,
    (c) => `${c.loc} школьники провели акцию «Засветись!» и раздали прохожим световозвращатели.`,
    (c, r) => `${c.loc} с начала года произошло ${10 + Math.floor(r() * 60)} ДТП с пострадавшими.`,
  ],
  indirect: [
    (c, r) => `${c.loc} отремонтировали участок дороги на улице ${pick(STREETS, r)}.`,
    (c) => `${c.loc} из-за снегопада затруднено движение в центре.`,
    (c) => `${c.loc} заменили фонари вдоль въезда в город.`,
    (c) => `${c.loc} дорожники начали посыпать улицы противогололёдной смесью.`,
  ],
  disputed: [
    (c, r) => `${c.loc} жители просят сделать тротуар вдоль улицы ${pick(STREETS, r)}.`,
    (c) => `${c.loc} обсудили, как будут ходить автобусы зимой.`,
    (c) => `${c.loc} на парковке у торгового центра появились новые знаки.`,
  ],
};

const TAILS = [
  'Госавтоинспекция просит водителей быть внимательнее.',
  'Обстоятельства происшествия выясняют.',
  'Пострадавших доставили в больницу.',
  'Работы планируют закончить до конца месяца.',
  'Жители обсуждают новость в комментариях.',
  'Подробности обещают сообщить позже.',
  'Пешеходов просят переходить дорогу только по переходу.',
  'Водителям советуют заранее сменить резину на зимнюю.',
];

export const LARGE_COUNT = 500;
/** Потолок выдачи Одноклассников в демо */
export const OK_CAP = 100;

export function buildLarge(): Dataset {
  const r = rng(2026);
  const sources = SOURCE_SEEDS.filter((s) => s.regional && !s.closed);
  const byPlatform: Record<PlatformId, typeof sources> = {
    vk: sources.filter((s) => s.platform === 'vk'),
    ok: sources.filter((s) => s.platform === 'ok'),
    max: sources.filter((s) => s.platform === 'max'),
  };
  const specs: PostSpec[] = [];
  let okCount = 0;
  for (let i = 0; i < LARGE_COUNT; i += 1) {
    const roll = r();
    let platform: PlatformId = roll < 0.58 ? 'vk' : roll < 0.82 ? 'ok' : 'max';
    // Одноклассники отдают не больше OK_CAP результатов (потолок выдачи, SC-16).
    if (platform === 'ok') {
      if (okCount >= OK_CAP) platform = 'vk';
      else okCount += 1;
    }
    const src = pick(byPlatform[platform], r);
    const relRoll = r();
    const rel: Relevance = relRoll < 0.56 ? 'direct' : relRoll < 0.84 ? 'indirect' : 'disputed';
    // Городской источник пишет о своём городе; краевые и районные — о любом.
    const home = CITIES.find((c) => c.nom === src.district);
    const city = home && r() < 0.8 ? home : pick(CITIES, r);
    const lead = pick(LEADS[rel], r)(city, r);
    const tail = pick(TAILS, r);
    const methodRoll = r();
    const m: SelectionMethod =
      rel === 'direct' && methodRoll < 0.1
        ? 'copy'
        : methodRoll < 0.55
          ? 'semantic'
          : 'ai-confirmed';
    const undated = r() < 0.04;
    const day = 1 + Math.floor(r() * 19);
    // «Сегодня» в демо — 19 октября, 14:32: постов из будущего нет.
    const hour = day === 19 ? 7 + Math.floor(r() * 7) : 7 + Math.floor(r() * 15);
    const minute = Math.floor(r() * 60);
    const atValue = undated
      ? null
      : `2026-10-${String(day).padStart(2, '0')} ${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
    specs.push({
      n: String(700_000 + i),
      src: src.id,
      at: atValue,
      text: [lead, tail],
      ev: 0,
      rel,
      m,
      places: [city.nom],
      facets: [],
    });
  }
  return {
    id: 'large',
    kind: 'topic',
    label: 'Безопасность дорожного движения',
    items: specs.map(buildItem),
    optional: [],
    spare: [],
    groups: [],
    topic: null,
    release: null,
    notices: [
      {
        code: 'platform-cap',
        tone: 'warning',
        message:
          'Одноклассники отдают не больше 100 результатов на один запрос. Чтобы увидеть остальные, сузьте период.',
      },
    ],
  };
}
