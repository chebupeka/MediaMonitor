/**
 * Источники для демо-данных. Группы и каналы VK, OK, MAX вымышлены: названия обезличены,
 * реальных СМИ нет; города и районы края — реальные. Сайты СМИ и каналы Дзена — настоящие
 * редакции края из каталога сервера (server/src/mediamonitor/data/krai-media.json): название,
 * район, домен, id канала. Публикации всех источников придуманы для демо. Адреса построены
 * по формату площадок, но ведут на несуществующие посты.
 */
import type { CatalogSource, PlatformId, PlatformInfo, SourceRef, SourceType } from '../types';
import { PLATFORM_ORDER } from '@/lib/labels';

export interface SourceSeed {
  id: string;
  platform: PlatformId;
  name: string;
  /** Короткое имя в адресе (VK, MAX, ник канала Дзена; пусто — канал Дзена по id; у сайта — домен в ссылках) */
  slug: string;
  /**
   * Владелец: VK, OK — числовой id группы; MAX — имя канала; сайт СМИ — домен без `www.`
   * (кириллический — в punycode); Дзен — id издателя канала
   */
  ownerId: string;
  type: SourceType;
  district: string | null;
  subscribers: number | null;
  /** В каталоге краевых источников */
  regional: boolean;
  /** В списке пользователя по умолчанию */
  mine: boolean;
  /** Закрытая группа: посты не видны (НТ-17 — честный сбой в демо-списке) */
  closed?: boolean;
  description: string;
}

const s = (seed: SourceSeed): SourceSeed => seed;

interface MediaSeed {
  name: string;
  district: string;
  mine: boolean;
  description: string;
}

/**
 * Сайт СМИ края: id `site:<домен>`, подписчиков у сайта нет. `host` — домен в ссылках, как
 * у сервера: кириллический — в привычном виде, у «Енисея» — с www; не задан — сам домен.
 */
const site = (seed: MediaSeed & { domain: string; host?: string }): SourceSeed => ({
  id: `site:${seed.domain}`,
  platform: 'site',
  name: seed.name,
  slug: seed.host ?? seed.domain,
  ownerId: seed.domain,
  type: 'media',
  district: seed.district,
  subscribers: null,
  regional: true,
  mine: seed.mine,
  description: seed.description,
});

/** Канал редакции на Дзене: id `dzen:<id издателя>`; ник пуст — адрес канала по id. */
const dzen = (
  seed: MediaSeed & { publisherId: string; nick: string; subscribers: number },
): SourceSeed => ({
  id: `dzen:${seed.publisherId}`,
  platform: 'dzen',
  name: seed.name,
  slug: seed.nick,
  ownerId: seed.publisherId,
  type: 'media',
  district: seed.district,
  subscribers: seed.subscribers,
  regional: true,
  mine: seed.mine,
  description: seed.description,
});

export const SOURCE_SEEDS: SourceSeed[] = [
  // ---------------------------------------------------------------- ВКонтакте
  s({
    id: 'vk-tv-kraya',
    platform: 'vk',
    name: 'Телеканал края',
    slug: 'demo_tv_kraya',
    ownerId: '100101',
    type: 'media',
    district: 'Красноярск',
    subscribers: 212_000,
    regional: true,
    mine: true,
    description: 'новости края, видеосюжеты',
  }),
  s({
    id: 'vk-portal-krsk',
    platform: 'vk',
    name: 'Городской портал Красноярска',
    slug: 'demo_portal_krsk',
    ownerId: '100102',
    type: 'media',
    district: 'Красноярск',
    subscribers: 318_000,
    regional: true,
    mine: true,
    description: 'городские новости Красноярска',
  }),
  s({
    id: 'vk-portal-norilsk',
    platform: 'vk',
    name: 'Городской портал Норильска',
    slug: 'demo_portal_norilsk',
    ownerId: '100103',
    type: 'media',
    district: 'Норильск',
    subscribers: 64_000,
    regional: true,
    mine: true,
    description: 'новости Норильска и Таймыра',
  }),
  s({
    id: 'vk-press-centre',
    platform: 'vk',
    name: 'Пресс-центр края',
    slug: 'demo_press_centre',
    ownerId: '100104',
    type: 'authority',
    district: 'весь край',
    subscribers: 48_000,
    regional: true,
    mine: true,
    description: 'официальные релизы',
  }),
  s({
    id: 'vk-minobr',
    platform: 'vk',
    name: 'Министерство образования края',
    slug: 'demo_minobr',
    ownerId: '100105',
    type: 'authority',
    district: 'весь край',
    subscribers: 37_000,
    regional: true,
    mine: true,
    description: 'образование, школы',
  }),
  s({
    id: 'vk-gai-krai',
    platform: 'vk',
    name: 'Госавтоинспекция края',
    slug: 'demo_gai_krai',
    ownerId: '100106',
    type: 'authority',
    district: 'весь край',
    subscribers: 58_000,
    regional: true,
    mine: true,
    description: 'безопасность на дорогах',
  }),
  s({
    id: 'vk-dorpatrul',
    platform: 'vk',
    name: 'Дорожный патруль Красноярска',
    slug: 'demo_dorpatrul',
    ownerId: '100107',
    type: 'community',
    district: 'Красноярск',
    subscribers: 96_000,
    regional: true,
    mine: true,
    description: 'ДТП и пробки, сообщения читателей',
  }),
  s({
    id: 'vk-achinsk',
    platform: 'vk',
    name: 'Ачинск. Главное',
    slug: 'demo_achinsk',
    ownerId: '100108',
    type: 'community',
    district: 'Ачинск',
    subscribers: 41_000,
    regional: true,
    mine: true,
    description: 'новости Ачинска',
  }),
  s({
    id: 'vk-kansk',
    platform: 'vk',
    name: 'Канск сегодня',
    slug: 'demo_kansk',
    ownerId: '100109',
    type: 'media',
    district: 'Канск',
    subscribers: 29_000,
    regional: true,
    mine: true,
    description: 'новости Канска',
  }),
  s({
    id: 'vk-minusinsk',
    platform: 'vk',
    name: 'Минусинск — наш город',
    slug: 'demo_minusinsk',
    ownerId: '100110',
    type: 'community',
    district: 'Минусинск',
    subscribers: 33_000,
    regional: true,
    mine: false,
    description: 'новости юга края',
  }),
  s({
    id: 'vk-lesosib',
    platform: 'vk',
    name: 'Лесосибирск. Новости',
    slug: 'demo_lesosib',
    ownerId: '100111',
    type: 'media',
    district: 'Лесосибирск',
    subscribers: 18_000,
    regional: true,
    mine: false,
    description: 'новости Лесосибирска',
  }),
  s({
    id: 'vk-zapolyarye',
    platform: 'vk',
    name: 'Заполярье: новости Таймыра',
    slug: 'demo_zapolyarye',
    ownerId: '100112',
    type: 'community',
    district: 'Таймырский район',
    subscribers: 23_000,
    regional: true,
    mine: true,
    description: 'Дудинка, Норильск, посёлки Таймыра',
  }),
  s({
    id: 'vk-parents',
    platform: 'vk',
    name: 'Родительское сообщество края',
    slug: 'demo_parents',
    ownerId: '100113',
    type: 'community',
    district: 'весь край',
    subscribers: 52_000,
    regional: true,
    mine: true,
    description: 'школы, детские сады, безопасность детей',
  }),
  s({
    id: 'vk-adm-norilsk',
    platform: 'vk',
    name: 'Администрация Норильска',
    slug: 'demo_adm_norilsk',
    ownerId: '100114',
    type: 'municipal',
    district: 'Норильск',
    subscribers: 41_000,
    regional: true,
    mine: true,
    description: 'официальная страница города',
  }),
  s({
    id: 'vk-zhel',
    platform: 'vk',
    name: 'Железногорск онлайн',
    slug: 'demo_zhel',
    ownerId: '100115',
    type: 'community',
    district: 'Железногорск',
    subscribers: 27_000,
    regional: true,
    mine: false,
    description: 'городские новости',
  }),
  s({
    id: 'vk-sharypovo',
    platform: 'vk',
    name: 'Шарыпово: город и район',
    slug: 'demo_sharypovo',
    ownerId: '100116',
    type: 'community',
    district: 'Шарыпово',
    subscribers: 12_000,
    regional: true,
    mine: false,
    description: 'новости Шарыпово',
  }),
  s({
    id: 'vk-eniseysk',
    platform: 'vk',
    name: 'Енисейск и район',
    slug: 'demo_eniseysk',
    ownerId: '100117',
    type: 'community',
    district: 'Енисейский район',
    subscribers: 9_800,
    regional: true,
    mine: false,
    description: 'новости Енисейска',
  }),
  s({
    id: 'vk-rech-port',
    platform: 'vk',
    name: 'Речной вокзал: навигация',
    slug: 'demo_rech_port',
    ownerId: '100118',
    type: 'institution',
    district: 'Красноярск',
    subscribers: 7_400,
    regional: true,
    mine: false,
    description: 'расписание и новости навигации',
  }),
  s({
    id: 'vk-auto-krsk',
    platform: 'vk',
    name: 'Автомобилисты Красноярска',
    slug: 'demo_auto_krsk',
    ownerId: '100119',
    type: 'community',
    district: 'Красноярск',
    subscribers: 143_000,
    regional: true,
    mine: false,
    description: 'сообщество водителей',
  }),
  s({
    id: 'vk-boguchany',
    platform: 'vk',
    name: 'Новости Богучан',
    slug: 'demo_boguchany',
    ownerId: '100120',
    type: 'community',
    district: 'Богучанский район',
    subscribers: 6_200,
    regional: true,
    mine: true,
    closed: true,
    description: 'новости Богучанского района (группа закрыта)',
  }),
  s({
    id: 'vk-kodinsk',
    platform: 'vk',
    name: 'Кодинск: соседи',
    slug: 'demo_kodinsk',
    ownerId: '100125',
    type: 'community',
    district: 'Кежемский район',
    subscribers: 4_300,
    regional: true,
    mine: false,
    closed: true,
    description: 'сообщество жителей Кодинска (группа закрыта)',
  }),
  s({
    id: 'vk-fire',
    platform: 'vk',
    name: 'Пожарная охрана края',
    slug: 'demo_fire_krai',
    ownerId: '100121',
    type: 'authority',
    district: 'весь край',
    subscribers: 31_000,
    regional: true,
    mine: false,
    description: 'пожарная безопасность',
  }),
  s({
    id: 'vk-zelenogorsk',
    platform: 'vk',
    name: 'Зеленогорск. Город',
    slug: 'demo_zelenogorsk',
    ownerId: '100122',
    type: 'community',
    district: 'Зеленогорск',
    subscribers: 15_000,
    regional: true,
    mine: false,
    description: 'новости Зеленогорска',
  }),
  s({
    id: 'vk-divnogorsk',
    platform: 'vk',
    name: 'Дивногорск и окрестности',
    slug: 'demo_divnogorsk',
    ownerId: '100123',
    type: 'community',
    district: 'Дивногорск',
    subscribers: 8_100,
    regional: true,
    mine: false,
    description: 'новости Дивногорска',
  }),
  s({
    id: 'vk-sport-krai',
    platform: 'vk',
    name: 'Спорт края',
    slug: 'demo_sport_krai',
    ownerId: '100124',
    type: 'media',
    district: 'весь край',
    subscribers: 44_000,
    regional: true,
    mine: false,
    description: 'спортивные новости',
  }),
  // Вне каталога краевых: край определяется только по упоминанию места (Р4)
  s({
    id: 'vk-news-sibir',
    platform: 'vk',
    name: 'Новости Сибири',
    slug: 'demo_news_sibir',
    ownerId: '100201',
    type: 'media',
    district: null,
    subscribers: 410_000,
    regional: false,
    mine: false,
    description: 'новости Сибирского округа',
  }),
  s({
    id: 'vk-avto-rf',
    platform: 'vk',
    name: 'Автоновости России',
    slug: 'demo_avto_rf',
    ownerId: '100202',
    type: 'media',
    district: null,
    subscribers: 1_250_000,
    regional: false,
    mine: false,
    description: 'федеральные автоновости',
  }),

  // ---------------------------------------------------------------- Одноклассники
  s({
    id: 'ok-novosti-kraya',
    platform: 'ok',
    name: 'Новости края',
    slug: 'demo_ok_novosti',
    ownerId: '5600101',
    type: 'media',
    district: 'весь край',
    subscribers: 95_000,
    regional: true,
    mine: true,
    description: 'новости края',
  }),
  s({
    id: 'ok-gazeta-taimyr',
    platform: 'ok',
    name: 'Районная газета Таймыра',
    slug: 'demo_ok_taimyr',
    ownerId: '5600102',
    type: 'media',
    district: 'Таймырский район',
    subscribers: 18_000,
    regional: true,
    mine: true,
    description: 'газета Таймыра',
  }),
  s({
    id: 'ok-gazeta-kansk',
    platform: 'ok',
    name: 'Районная газета Канского района',
    slug: 'demo_ok_kansk_gazeta',
    ownerId: '5600103',
    type: 'media',
    district: 'Канский район',
    subscribers: 7_000,
    regional: true,
    mine: true,
    description: 'районная газета',
  }),
  s({
    id: 'ok-krasnoyarye',
    platform: 'ok',
    name: 'Новости Красноярья',
    slug: 'demo_ok_krasnoyarye',
    ownerId: '5600104',
    type: 'media',
    district: 'весь край',
    subscribers: 31_000,
    regional: true,
    mine: true,
    description: 'новости края для старшего поколения',
  }),
  s({
    id: 'ok-achinsk',
    platform: 'ok',
    name: 'Ачинск и Ачинский район',
    slug: 'demo_ok_achinsk',
    ownerId: '5600105',
    type: 'community',
    district: 'Ачинск',
    subscribers: 22_000,
    regional: true,
    mine: false,
    description: 'новости Ачинска',
  }),
  s({
    id: 'ok-yug',
    platform: 'ok',
    name: 'Юг края: Минусинск и район',
    slug: 'demo_ok_yug',
    ownerId: '5600106',
    type: 'community',
    district: 'Минусинск',
    subscribers: 14_000,
    regional: true,
    mine: true,
    description: 'новости юга края',
  }),
  s({
    id: 'ok-dolgoletie',
    platform: 'ok',
    name: 'Активное долголетие края',
    slug: 'demo_ok_dolgoletie',
    ownerId: '5600107',
    type: 'community',
    district: 'весь край',
    subscribers: 26_000,
    regional: true,
    mine: false,
    description: 'для старшего поколения',
  }),
  s({
    id: 'ok-kansk',
    platform: 'ok',
    name: 'Канск и Канский район',
    slug: 'demo_ok_kansk',
    ownerId: '5600108',
    type: 'community',
    district: 'Канск',
    subscribers: 16_000,
    regional: true,
    mine: false,
    description: 'новости Канска',
  }),

  // ---------------------------------------------------------------- MAX
  s({
    id: 'max-press',
    platform: 'max',
    name: 'Канал Пресс-центра края',
    slug: 'demo_press_kanal',
    ownerId: 'press',
    type: 'authority',
    district: 'весь край',
    subscribers: 12_000,
    regional: true,
    mine: true,
    description: 'официальные релизы',
  }),
  s({
    id: 'max-portal',
    platform: 'max',
    name: 'Канал городского портала',
    slug: 'demo_portal_kanal',
    ownerId: 'portal',
    type: 'media',
    district: 'Красноярск',
    subscribers: 56_000,
    regional: true,
    mine: true,
    description: 'новости Красноярска',
  }),
  s({
    id: 'max-norilsk',
    platform: 'max',
    name: 'Норильск. Коротко',
    slug: 'demo_norilsk_korotko',
    ownerId: 'norilsk',
    type: 'media',
    district: 'Норильск',
    subscribers: 21_000,
    regional: true,
    mine: true,
    description: 'короткие новости Норильска',
  }),
  s({
    id: 'max-dorogi',
    platform: 'max',
    name: 'Дороги края',
    slug: 'demo_dorogi',
    ownerId: 'dorogi',
    type: 'community',
    district: 'весь край',
    subscribers: 17_000,
    regional: true,
    mine: false,
    description: 'дороги, пробки, ДТП',
  }),
  s({
    id: 'max-tv',
    platform: 'max',
    name: 'Телеканал края в MAX',
    slug: 'demo_tv_max',
    ownerId: 'tv',
    type: 'media',
    district: 'Красноярск',
    subscribers: 34_000,
    regional: true,
    mine: true,
    description: 'новости края',
  }),
  s({
    id: 'max-achinsk',
    platform: 'max',
    name: 'Ачинск 24',
    slug: 'demo_achinsk24',
    ownerId: 'achinsk24',
    type: 'media',
    district: 'Ачинск',
    subscribers: 6_500,
    regional: true,
    mine: false,
    description: 'новости Ачинска',
  }),

  // ---------------------------------------------------------------- Сайты СМИ (каталог края)
  site({
    domain: 'vtruda.ru',
    name: 'Власть труда',
    district: 'Минусинский муниципальный округ',
    mine: true,
    description: 'газета Минусинского округа: лента RSS с полным текстом',
  }),
  site({
    domain: 'severokrai.ru',
    name: 'Заполярье',
    district: 'Норильск',
    mine: true,
    description: 'газета Норильска: лента RSS с полным текстом',
  }),
  site({
    domain: 'enisey.tv',
    host: 'www.enisey.tv',
    name: 'Енисей',
    district: 'весь край',
    mine: false,
    description: 'краевой телеканал: лента RSS с полным текстом',
  }),
  site({
    domain: 'zaren.ru',
    name: 'Заря Енисея',
    district: 'Лесосибирск',
    mine: false,
    description: 'газета Лесосибирска: лента RSS с полным текстом',
  }),
  site({
    domain: 'kvgazeta.ru',
    name: 'Канские ведомости',
    district: 'Канский муниципальный округ',
    mine: false,
    description: 'газета Канского округа: лента RSS с полным текстом',
  }),
  site({
    domain: 'xn--80aaaegnnmj2ctw4e.xn--p1ai',
    host: 'газетарабочий.рф',
    name: 'Рабочий',
    district: 'Сосновоборск',
    mine: false,
    description: 'газета Сосновоборска: лента RSS с полным текстом',
  }),
  site({
    domain: 'angarka.info',
    name: 'Ангарская правда',
    district: 'Богучанский муниципальный округ',
    mine: false,
    description: 'газета Богучанского округа: ленты нет, читаем раздел новостей',
  }),
  site({
    domain: 'xn--b1abhapojjdbxk.xn--p1ai',
    host: 'голосвремени.рф',
    name: 'Голос времени',
    district: 'Рыбинский муниципальный округ',
    mine: false,
    description: 'газета Рыбинского округа: ленты нет, читаем раздел новостей',
  }),
  site({
    domain: 'sovet-prich.ru',
    name: 'Советское Причулымье',
    district: 'Назаровский муниципальный округ',
    mine: false,
    description: 'газета Назаровского округа: лента RSS с полным текстом',
  }),
  site({
    domain: 'tubinka.ru',
    name: 'Тубинские вести',
    district: 'Курагинский муниципальный округ',
    mine: false,
    description: 'газета Курагинского округа: лента RSS с короткими заметками',
  }),

  // ---------------------------------------------------------------- Дзен (каналы редакций)
  dzen({
    publisherId: '647edcf397f79c2656d02daf',
    nick: 'vtruda',
    name: 'Власть труда',
    district: 'Минусинский муниципальный округ',
    subscribers: 2_823,
    mine: true,
    description: 'канал газеты «Власть труда» на Дзене',
  }),
  dzen({
    publisherId: '5a94ca3757906aae1fea2b45',
    nick: 'enisey',
    name: 'Енисей',
    district: 'весь край',
    subscribers: 2_177,
    mine: false,
    description: 'канал телеканала «Енисей» на Дзене',
  }),
  dzen({
    publisherId: '652e006f4d4ed96c76dbd65c',
    nick: 'snknews',
    name: 'Рабочий',
    district: 'Сосновоборск',
    subscribers: 6_006,
    mine: false,
    description: 'канал газеты «Рабочий» на Дзене',
  }),
  dzen({
    publisherId: '6377447224dd3955db090d4c',
    nick: 'eniseyka',
    name: 'Енисейская правда',
    district: 'Енисейский муниципальный округ',
    subscribers: 1_937,
    mine: false,
    description: 'канал газеты «Енисейская правда» на Дзене',
  }),
  dzen({
    publisherId: '616561bd3b86277d535566c7',
    nick: '',
    name: 'Советское Причулымье',
    district: 'Назаровский муниципальный округ',
    subscribers: 942,
    mine: false,
    description: 'канал газеты «Советское Причулымье» на Дзене',
  }),
];

const BY_ID = new Map(SOURCE_SEEDS.map((seed) => [seed.id, seed]));

export function seedById(id: string): SourceSeed {
  const seed = BY_ID.get(id);
  if (!seed) throw new Error(`Неизвестный демо-источник: ${id}`);
  return seed;
}

export function sourceUrl(seed: SourceSeed): string {
  switch (seed.platform) {
    case 'vk':
      return `https://vk.com/${seed.slug}`;
    case 'ok':
      return `https://ok.ru/group/${seed.ownerId}`;
    case 'max':
      return `https://max.ru/${seed.slug}`;
    case 'site':
      return `https://${seed.slug}/`;
    case 'dzen':
      return seed.slug ? `https://dzen.ru/${seed.slug}` : `https://dzen.ru/id/${seed.ownerId}`;
  }
}

/**
 * Прямая ссылка на пост, построенная из ключа (НТ-13). Сайт СМИ: `postId` — путь статьи
 * без первого `/`. Дзен: `a-<id>` — статья (`dzen.ru/a/<id>`), `b-<id>` — пост (`dzen.ru/b/<id>`).
 */
export function postUrl(seed: SourceSeed, postId: string): string {
  switch (seed.platform) {
    case 'vk':
      return `https://vk.com/wall-${seed.ownerId}_${postId}`;
    case 'ok':
      return `https://ok.ru/group/${seed.ownerId}/topic/${postId}`;
    case 'max':
      return `https://max.ru/${seed.slug}/${postId}`;
    case 'site':
      return `https://${seed.slug}/${postId}`;
    case 'dzen':
      return `https://dzen.ru/${postId.startsWith('b-') ? 'b' : 'a'}/${postId.slice(2)}`;
  }
}

/** Другие адреса того же поста — для демонстрации склейки в одну запись (НТ-13). */
export function alternatePostUrls(seed: SourceSeed, postId: string): string[] {
  if (seed.platform === 'vk') {
    return [
      `https://m.vk.com/wall-${seed.ownerId}_${postId}`,
      `https://vk.com/${seed.slug}?w=wall-${seed.ownerId}_${postId}`,
    ];
  }
  if (seed.platform === 'ok') return [`https://m.ok.ru/group/${seed.ownerId}/topic/${postId}`];
  return [];
}

export function toSourceRef(seed: SourceSeed, inMySources: boolean): SourceRef {
  return {
    id: seed.id,
    platform: seed.platform,
    name: seed.name,
    url: sourceUrl(seed),
    type: seed.type,
    district: seed.district,
    subscribers: seed.subscribers,
    inMySources,
    regional: seed.regional,
  };
}

export function catalogSources(myIds: ReadonlySet<string>): CatalogSource[] {
  return SOURCE_SEEDS.filter((seed) => seed.regional && !seed.closed).map((seed) => ({
    ...toSourceRef(seed, myIds.has(seed.id)),
    description: seed.description,
  }));
}

/**
 * Пул «везде»: сколько источников площадки обходим при поиске без ограничения списком.
 * Сайты СМИ — подключённые сайты каталога (43 из 48), Дзен — каналы редакций (25).
 */
export const EVERYWHERE_POOL: Record<PlatformId, number> = {
  vk: 40,
  ok: 18,
  max: 12,
  site: 43,
  dzen: 25,
};

// ---------------------------------------------------------------- площадки сервера

/** Покрытие сайтов СМИ: какие сайты каталога не опрашиваются и почему. */
export const SITE_NOTE =
  'Подключено 43 сайта из 48. Не опрашиваются: «Ачинская газета» и «Маяк Севера» — сайт не открывается; «Наш Красноярский край» — пока не подключён: другой движок сайта; «Огни Енисея» — лента закрыта в robots.txt; «Сельский труженик» — сайт заброшен, последние новости — 2021 год.';

/** Откуда данные Дзена и оговорка о правилах площадки. */
export const DZEN_NOTE =
  'Каналы 25 редакций края, данные — с публичных страниц каналов. Правила Дзена запрещают копировать контент без разрешения (п. 5.1) — серая зона, как у Одноклассников.';

const PLATFORM_INFO_BY_ID: Record<PlatformId, PlatformInfo> = {
  vk: {
    id: 'vk',
    name: 'ВКонтакте',
    short: 'VK',
    required: true,
    enabled: true,
    via: 'VK API (сервисный ключ)',
    note: null,
  },
  ok: {
    id: 'ok',
    name: 'Одноклассники',
    short: 'OK',
    required: true,
    enabled: true,
    via: 'веб-поиск Одноклассников',
    note: null,
  },
  max: {
    id: 'max',
    name: 'MAX',
    short: 'MAX',
    required: true,
    enabled: true,
    via: 'сторонний индекс MaxStat + проверка ссылок на max.ru',
    note: null,
  },
  site: {
    id: 'site',
    name: 'Сайты СМИ',
    short: 'Сайты',
    required: false,
    enabled: true,
    via: 'ленты RSS, разделы новостей и поиск на сайтах СМИ края',
    note: SITE_NOTE,
  },
  dzen: {
    id: 'dzen',
    name: 'Дзен',
    short: 'Дзен',
    required: false,
    enabled: true,
    via: 'страницы каналов редакций на Дзене',
    note: DZEN_NOTE,
  },
};

/** Площадки имитированного сервера — для `StartState.platforms` и стенда. */
export function platformInfo(): PlatformInfo[] {
  return PLATFORM_ORDER.map((p) => ({ ...PLATFORM_INFO_BY_ID[p] }));
}

/** Площадки, по которым имитация ищет, если запрос их не задал: все включённые. */
export function enabledPlatforms(): PlatformId[] {
  return PLATFORM_ORDER.filter((p) => PLATFORM_INFO_BY_ID[p].enabled);
}

/** Постоянная оговорка о покрытии площадки (`PlatformStatus.note`). */
export function platformNote(platform: PlatformId): string | null {
  return PLATFORM_INFO_BY_ID[platform].note;
}

/** «Как ищем» для стенда — с заглавной буквы. */
export function platformVia(platform: PlatformId): string {
  const via = PLATFORM_INFO_BY_ID[platform].via;
  return via.charAt(0).toUpperCase() + via.slice(1);
}

// ---------------------------------------------------------------- ссылки

/**
 * Домены сайтов СМИ из демо-каталога (в punycode и в привычном виде): только они
 * распознаются как площадка «Сайты СМИ».
 */
export const SITE_DOMAINS: readonly string[] = SOURCE_SEEDS.filter(
  (seed) => seed.platform === 'site',
).flatMap((seed) => [seed.ownerId, seed.slug.replace(/^www\./u, '')]);

/**
 * Ссылка на пост, а не на группу (SC-10): `vk.com/wall-100104_60210`, `?w=wall…`,
 * `ok.ru/group/…/topic/…`, `max.ru/канал/номер`, статья на сайте СМИ из каталога,
 * `dzen.ru/a/…` и `dzen.ru/b/…`. Возвращает владельца поста (источник из демо-данных,
 * если он известен) и признак «это пост».
 */
export function postOwner(raw: string): { isPost: boolean; seed: SourceSeed | null } {
  const url = raw.trim().toLowerCase();
  const vk = /wall-?(\d+)_\d+/u.exec(url);
  if (vk)
    return {
      isPost: true,
      seed: SOURCE_SEEDS.find((s) => s.platform === 'vk' && s.ownerId === vk[1]) ?? null,
    };
  const ok = /ok\.ru\/group\/(\d+)\/topic\/\d+/u.exec(url);
  if (ok)
    return {
      isPost: true,
      seed: SOURCE_SEEDS.find((s) => s.platform === 'ok' && s.ownerId === ok[1]) ?? null,
    };
  const max = /max\.ru\/([^/\s?#]+)\/\d+/u.exec(url);
  if (max)
    return {
      isPost: true,
      seed: SOURCE_SEEDS.find((s) => s.platform === 'max' && s.slug === max[1]) ?? null,
    };
  // Пост Дзена: по адресу не видно канал — владельца не подсказываем.
  if (/(^|\/\/|\.)dzen\.ru\/[ab]\/[^/\s?#]+/u.test(url)) return { isPost: true, seed: null };
  // Статья на сайте СМИ: любой путь после домена из каталога.
  const article = /^(?:https?:\/\/)?(?:www\.|m\.)?([^/\s?#]+)\/[^?#\s]*[^/?#\s]/u.exec(url);
  const domain = article?.[1];
  if (domain && SITE_DOMAINS.includes(domain))
    return {
      isPost: true,
      seed:
        SOURCE_SEEDS.find(
          (s) => s.platform === 'site' && (s.ownerId === domain || s.slug === domain),
        ) ?? null,
    };
  return { isPost: false, seed: null };
}
