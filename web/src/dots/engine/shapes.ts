/**
 * Формы точек — перенос `site/particles.js` (сайт «Стрежень») без изменения смысла:
 * те же генераторы, веса, цвета и числа. Каждая форма что-то значит в продукте
 * (словарь форм, docs/08-visual-concept.md).
 *
 * Модель — N точек (x, y, z, код). Код = цвет палитры (0–7); +8 — точка «течёт»,
 * а дробная часть — её место на пути (0…1): по пути бегут светлые импульсы.
 * Добавлено для правила честности (ветка, 08 «Правила честности»): +16 — точка-данные,
 * одна публикация; дробная часть — её номер в спирали вокруг города (номер / 1000).
 *
 * Отличия от сайта — только там, где форма получает данные:
 *  - `searching` / `failure`: состояние облака каждой площадки (как в ветке): active — поток
 *    идёт; done — поток закончился; failed — облако серое и мерцает; idle — облако тусклое;
 *  - `found`: вместо золотых облаков демо-набора — ровно столько точек-данных, сколько
 *    публикаций с известным городом (правила 1–3), кольца — вокруг этих городов;
 *  - `spread`: опор ровно столько, сколько размещений, кольцо — очередь публикации.
 * Генерация детерминированная: одинаковые входы дают одинаковые точки.
 */
import type { PlatformId } from '@/api/types';
import {
  KRAI_CITIES,
  KRAI_OUTLINE,
  SEVERNAYA_ZEMLYA,
  TRIBUTARIES as TRIBUTARIES_LONLAT,
  YENISEI as YENISEI_LONLAT,
  type LonLat,
} from '../krai-geo';
import type { DotsCityCount, DotsPlatformState } from '../types';

/* ---------- Палитра ---------- */

export const BLUE = 0;
export const WHITE = 1;
export const GOLD = 2;
export const VK = 3;
export const OK = 4;
export const MAX = 5;
export const GREY = 6;
export const DIM = 7;

/** Палитра сайта (тёмная тема): синий, белый, золото, VK, OK, MAX, серый (сбой), приглушённый. */
// prettier-ignore
export const PALETTE = new Float32Array([
  0.3, 0.55, 1.0, // синий
  0.93, 0.95, 1.0, // белый
  1.0, 0.7, 0.28, // золото
  0.22, 0.52, 1.0, // ВКонтакте
  1.0, 0.5, 0.2, // Одноклассники
  0.18, 0.86, 0.55, // MAX
  0.5, 0.53, 0.6, // серый: сбой площадки, мерцает
  0.36, 0.45, 0.62, // приглушённый: основа карты, погасшие точки
]);

/** Точка-данные (правило честности): +16 к коду, дробная часть — номер в спирали / 1000. */
export const DATA = 16;
/** Сколько точек-данных у одного города различает код (номер в спирали < 1000). */
const DATA_SLOTS = 1000;

/** Точка, которая «течёт»: f — место на пути от 0 до 1 */
function flow(color: number, f: number): number {
  return color + 8 + Math.max(0, Math.min(0.999, f));
}

/* ---------- Случайные числа ---------- */

export function rng(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Сид сайта; у каждой формы свой поток, как у последовательной сборки на сайте. */
const SEED = 20261019;
let R = rng(SEED);
function gauss(): number {
  const u = R() || 1e-6;
  const v = R();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}
function jit(a: number): number {
  return (R() - 0.5) * a;
}
/** Синий, белый или золото по «тону» 0…1 с лёгким разбросом */
function tone(t: number, v?: number): number {
  const x = t + (R() - 0.5) * (v === undefined ? 0.18 : v);
  return x < 0.34 ? BLUE : x < 0.67 ? WHITE : GOLD;
}
/** Индекс по весам */
function pick(weights: readonly number[]): number {
  let s = 0;
  for (const w of weights) s += w;
  let r = R() * s;
  for (let i = 0; i < weights.length; i += 1) {
    r -= weights[i] ?? 0;
    if (r <= 0) return i;
  }
  return weights.length - 1;
}

type Put = (x: number, y: number, z: number, code: number) => void;
type Part = readonly [weight: number, emit: (put: Put) => void];

/** Собирает модель из частей [вес, функция одной точки] */
function compose(parts: readonly Part[], N: number): Float32Array {
  const a = new Float32Array(N * 4);
  let i = 0;
  const total = parts.reduce((s, p) => s + p[0], 0);
  const put: Put = (x, y, z, code) => {
    if (i >= N) return;
    a[i * 4] = x;
    a[i * 4 + 1] = y;
    a[i * 4 + 2] = z;
    a[i * 4 + 3] = code;
    i += 1;
  };
  parts.forEach((p, k) => {
    const n = k === parts.length - 1 ? N - i : Math.round((N * p[0]) / total);
    for (let j = 0; j < n; j += 1) p[1](put);
  });
  return a;
}

/* ---------- География края ---------- */
// Те же данные, что на сайте (krai-geo.ts совпадает с particles.js по каждой точке):
// контур упрощён вручную, реки и города — реальные координаты, проекция Ламберта.

type Pt = readonly [number, number];

/** Города сайта — для декора (крупные ярче). Данные ищут город по всему KRAI_CITIES. */
const CITIES: Readonly<Record<string, readonly [lon: number, lat: number, major: 0 | 1]>> = {
  Красноярск: [92.87, 56.01, 1],
  Норильск: [88.2, 69.35, 1],
  Ачинск: [90.5, 56.27, 1],
  Канск: [95.7, 56.2, 1],
  Минусинск: [91.69, 53.71, 1],
  Лесосибирск: [92.48, 58.23, 0],
  Енисейск: [92.17, 58.45, 0],
  Дудинка: [86.18, 69.4, 0],
  Железногорск: [93.53, 56.25, 0],
  Зеленогорск: [94.59, 56.11, 0],
  Шарыпово: [89.18, 55.54, 0],
  Назарово: [90.4, 56.0, 0],
  Кодинск: [99.18, 58.6, 0],
  Богучаны: [97.45, 58.38, 0],
  Туруханск: [87.98, 65.79, 0],
  Игарка: [86.58, 67.47, 0],
  Тура: [100.22, 64.27, 0],
  Ванавара: [102.28, 60.34, 0],
  Байкит: [96.37, 61.67, 0],
  Хатанга: [102.47, 71.98, 0],
  Диксон: [80.55, 73.51, 0],
};

const RAD = Math.PI / 180;
const LON0 = 96 * RAD;
const LAT1 = 52 * RAD;
const LAT2 = 74 * RAD;
const LAT0 = 64 * RAD;
const tanHalf = (p: number): number => Math.tan(Math.PI / 4 + p / 2);
const NL = Math.log(Math.cos(LAT1) / Math.cos(LAT2)) / Math.log(tanHalf(LAT2) / tanHalf(LAT1));
const FL = (Math.cos(LAT1) * Math.pow(tanHalf(LAT1), NL)) / NL;
const RHO0 = FL / Math.pow(tanHalf(LAT0), NL);
function lambert(p: LonLat): Pt {
  const rho = FL / Math.pow(tanHalf(p[1] * RAD), NL);
  const th = NL * (p[0] * RAD - LON0);
  return [(rho * Math.sin(th)) / RAD, (RHO0 - rho * Math.cos(th)) / RAD]; // y вверх
}

interface Polyline {
  pts: Pt[];
  total: number;
  at: (u: number) => Pt;
}

/** Ломаная с равномерной выборкой по длине */
function polyline(pts: Pt[], closed: boolean): Polyline {
  const p = closed && pts[0] ? [...pts, pts[0]] : pts;
  const cum = [0];
  for (let i = 1; i < p.length; i += 1) {
    const a = p[i - 1] ?? [0, 0];
    const b = p[i] ?? a;
    cum.push((cum[i - 1] ?? 0) + Math.hypot(b[0] - a[0], b[1] - a[1]));
  }
  const total = cum[cum.length - 1] ?? 0;
  return {
    pts,
    total,
    at(u) {
      // точка на доле пути u
      const d = u * total;
      let k = 1;
      while (k < cum.length - 1 && (cum[k] ?? 0) < d) k += 1;
      const a = p[k - 1] ?? [0, 0];
      const b = p[k] ?? a;
      const c0 = cum[k - 1] ?? 0;
      const t = (d - c0) / Math.max(1e-9, (cum[k] ?? c0) - c0);
      return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
    },
  };
}

function inside(x: number, y: number, poly: readonly Pt[]): boolean {
  let inn = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i, i += 1) {
    const a = poly[i];
    const b = poly[j];
    if (!a || !b) continue;
    if (a[1] > y !== b[1] > y && x < ((b[0] - a[0]) * (y - a[1])) / (b[1] - a[1]) + a[0])
      inn = !inn;
  }
  return inn;
}

interface City {
  p: Pt;
  major: boolean;
}

interface Geo {
  outline: Polyline;
  islands: Polyline;
  yenisei: Polyline;
  tribs: Polyline[];
  /** Города сайта — в порядке сайта */
  cities: Map<string, City>;
  /** Все города карты (KRAI_CITIES) — для точек-данных */
  dataCities: Map<string, Pt>;
  bbox: readonly [x0: number, x1: number, y0: number, y1: number];
}

/** Нормируем: край высотой MAP_H по центру начала координат */
const MAP_H = 2.5;
let geoCache: Geo | null = null;

function geo(): Geo {
  if (geoCache) return geoCache;
  const all = [...KRAI_OUTLINE, ...SEVERNAYA_ZEMLYA].map(lambert);
  let x0 = Infinity;
  let x1 = -Infinity;
  let y0 = Infinity;
  let y1 = -Infinity;
  for (const p of all) {
    x0 = Math.min(x0, p[0]);
    x1 = Math.max(x1, p[0]);
    y0 = Math.min(y0, p[1]);
    y1 = Math.max(y1, p[1]);
  }
  const s = MAP_H / (y1 - y0);
  const cx = (x0 + x1) / 2;
  const cy = (y0 + y1) / 2;
  const norm = (p: LonLat): Pt => {
    const q = lambert(p);
    return [(q[0] - cx) * s, (q[1] - cy) * s];
  };
  const cities = new Map<string, City>();
  for (const [name, c] of Object.entries(CITIES))
    cities.set(name, { p: norm([c[0], c[1]]), major: c[2] === 1 });
  const dataCities = new Map<string, Pt>();
  for (const c of KRAI_CITIES) dataCities.set(c.name, norm([c.lon, c.lat]));
  geoCache = {
    outline: polyline(KRAI_OUTLINE.map(norm), true),
    islands: polyline(SEVERNAYA_ZEMLYA.map(norm), true),
    yenisei: polyline(YENISEI_LONLAT.map(norm), false),
    tribs: TRIBUTARIES_LONLAT.map((t) => polyline(t.map(norm), false)),
    cities,
    dataCities,
    bbox: [(x0 - cx) * s, (x1 - cx) * s, (y0 - cy) * s, (y1 - cy) * s],
  };
  return geoCache;
}

function cityAt(name: string): Pt {
  return geo().cities.get(name)?.p ?? [0, 0];
}

/** Лёгкий рельеф: карта не плоская, а чуть «дышит» по глубине */
function relief(x: number, y: number): number {
  return 0.05 * Math.sin(x * 6 + 1) * Math.cos(y * 4) + jit(0.05);
}

interface MapOptions {
  /** Сдвиг и масштаб карты внутри модели */
  s?: number;
  ox?: number;
  oy?: number;
  outline?: number;
  outlineColor?: () => number;
  fill?: number;
  fillColor?: () => number;
  river?: number;
  tribs?: number;
  /** Течёт ли Енисей */
  riverFlow?: boolean;
  riverColor?: number;
  cities?: number;
}

/** Части карты края: веса частей и цвета. */
function mapParts(o: MapOptions): Part[] {
  const G = geo();
  const s = o.s || 1;
  const ox = o.ox || 0;
  const oy = o.oy || 0;
  const T = (p: Pt, z: number): [number, number, number] => [
    ox + p[0] * s,
    oy + p[1] * s,
    (z || 0) * s,
  ];
  const put3 = (put: Put, p: Pt, z: number, code: number) => {
    const q = T(p, z);
    put(q[0], q[1], q[2], code);
  };
  const outlineColor = o.outlineColor ?? (() => BLUE);
  const fillColor = o.fillColor ?? (() => DIM);
  const riverColor = o.riverColor ?? BLUE;
  const parts: Part[] = [];
  if (o.outline)
    parts.push([
      o.outline,
      (put) => {
        const line = R() < 0.92 ? G.outline : G.islands;
        const p = line.at(R());
        put3(put, [p[0] + jit(0.012), p[1] + jit(0.012)], jit(0.04), outlineColor());
      },
    ]);
  if (o.fill)
    parts.push([
      o.fill,
      (put) => {
        const b = G.bbox;
        for (let i = 0; i < 60; i += 1) {
          const x = b[0] + R() * (b[1] - b[0]);
          const y = b[2] + R() * (b[3] - b[2]);
          if (inside(x, y, G.outline.pts) || inside(x, y, G.islands.pts)) {
            put3(put, [x, y], relief(x, y), fillColor());
            return;
          }
        }
        put3(put, G.outline.at(R()), 0, fillColor());
      },
    ]);
  if (o.river)
    parts.push([
      o.river,
      (put) => {
        const u = R(); // Енисей течёт с юга на север
        const p = G.yenisei.at(u);
        put3(
          put,
          [p[0] + jit(0.022), p[1] + jit(0.022)],
          jit(0.03),
          o.riverFlow ? flow(BLUE, u) : riverColor,
        );
      },
    ]);
  if (o.tribs)
    parts.push([
      o.tribs,
      (put) => {
        const k = pick(G.tribs.map((t) => t.total));
        const u = R();
        const p = (G.tribs[k] ?? G.yenisei).at(u);
        put3(
          put,
          [p[0] + jit(0.016), p[1] + jit(0.016)],
          jit(0.03),
          o.riverFlow ? flow(BLUE, u) : riverColor,
        );
      },
    ]);
  if (o.cities)
    parts.push([
      o.cities,
      (put) => {
        const names = [...G.cities.keys()];
        const k = pick(names.map((n) => (G.cities.get(n)?.major ? 3 : 1)));
        const name = names[k] ?? 'Красноярск';
        const c = G.cities.get(name) ?? { p: [0, 0] as Pt, major: false };
        const r = c.major ? 0.026 : 0.013;
        put3(
          put,
          [c.p[0] + gauss() * r, c.p[1] + gauss() * r],
          gauss() * r,
          name === 'Красноярск' ? GOLD : WHITE,
        );
      },
    ]);
  return parts;
}

/* ---------- Формы словаря ---------- */

/** Лендинг, покой: силуэт края с юга до Таймыра, по нему течёт Енисей */
function krai(): Part[] {
  return [
    ...mapParts({
      outline: 0.2,
      outlineColor: () => (R() < 0.65 ? BLUE : WHITE),
      fill: 0.36,
      fillColor: () => (R() < 0.55 ? DIM : BLUE),
      river: 0.2,
      tribs: 0.09,
      riverFlow: true,
      cities: 0.07,
    }),
    [
      0.08,
      (put) => {
        // редкая пыль вокруг карты: гуще у силуэта и мягко сходит на нет с расстоянием —
        // без прямоугольной границы (раньше пыль заполняла прямоугольник вокруг карты,
        // и он читался как подложка)
        const G = geo();
        const p = (R() < 0.92 ? G.outline : G.islands).at(R());
        const a = R() * Math.PI * 2;
        const r = 0.02 - Math.log(1 - R() * 0.997) * 0.13;
        put(p[0] + Math.cos(a) * r, p[1] + Math.sin(a) * r, jit(0.8), R() < 0.7 ? DIM : BLUE);
      },
    ],
  ];
}

/** Человек вводит запрос: облако оживает и тянется к полю ввода (вправо) */
function listening(): Part[] {
  return [
    [
      0.5,
      (put) => {
        // облако
        const r = Math.pow(R(), 0.5);
        put(-0.35 + gauss() * 0.36 * r, gauss() * 0.3 * r, gauss() * 0.32 * r, pick([45, 35, 20]));
      },
    ],
    [
      0.38,
      (put) => {
        // хвост к полю ввода
        const u = Math.pow(R(), 0.8);
        const w = 0.2 * (1 - u) + 0.02;
        put(
          -0.15 + u * 2.05 + jit(0.04),
          0.1 * Math.sin(u * 3.2) - 0.06 * u + gauss() * w * 0.5,
          gauss() * w * 0.5,
          flow(R() < 0.6 ? BLUE : WHITE, u),
        );
      },
    ],
    [
      0.12,
      (put) => {
        // искры вокруг
        const a = R() * Math.PI * 2;
        const r = 0.55 + R() * 0.5;
        put(-0.35 + Math.cos(a) * r, Math.sin(a) * r * 0.8, jit(0.6), R() < 0.5 ? DIM : BLUE);
      },
    ],
  ];
}

export type PlatformStates = Readonly<Record<PlatformId, DotsPlatformState>>;

/** Облака площадок: [площадка, цвет, x, y] — как на сайте. */
const CLOUDS: readonly (readonly [PlatformId, number, number, number])[] = [
  ['vk', VK, -1.05, 0.72],
  ['ok', OK, -1.28, 0.0],
  ['max', MAX, -1.05, -0.72],
];
const TARGETS = ['Красноярск', 'Норильск', 'Канск', 'Ачинск', 'Лесосибирск', 'Минусинск'];

/**
 * Идёт поиск: три облака VK, OK, MAX, из них точки текут на карту.
 * failed — площадка со сбоем: её облако серое и мерцает, поток не идёт.
 * (Ветка:) done — поток закончился, облако своего цвета; idle — облако тусклое.
 */
function clouds(states: PlatformStates): Part[] {
  const MS = 0.72;
  const MX = 0.82;
  const colorOf = (p: PlatformId, color: number): number =>
    states[p] === 'failed' ? GREY : states[p] === 'idle' ? DIM : color;
  const map = mapParts({
    s: MS,
    ox: MX,
    outline: 0.12,
    outlineColor: () => (R() < 0.5 ? BLUE : DIM),
    fill: 0.17,
    fillColor: () => DIM,
    river: 0.05,
    riverFlow: true,
  });
  return [
    ...map,
    [
      0.3,
      (put) => {
        // облака площадок
        const c = CLOUDS[Math.floor(R() * 3)] ?? CLOUDS[0];
        if (!c) return;
        const bad = states[c[0]] === 'failed';
        const r = Math.pow(R(), 0.6) * (bad ? 1.25 : 1);
        put(
          c[2] + gauss() * 0.17 * r,
          c[3] + gauss() * 0.15 * r,
          gauss() * 0.16 * r,
          colorOf(c[0], c[1]),
        );
      },
    ],
    [
      0.36,
      (put) => {
        // потоки к городам на карте
        const c = CLOUDS[Math.floor(R() * 3)] ?? CLOUDS[0];
        if (!c) return;
        if (states[c[0]] !== 'active') {
          // у площадки со сбоем (или без потока) — точки остаются в облаке
          put(c[2] + gauss() * 0.22, c[3] + gauss() * 0.2, gauss() * 0.2, colorOf(c[0], c[1]));
          return;
        }
        const t = cityAt(TARGETS[Math.floor(R() * TARGETS.length)] ?? 'Красноярск');
        const ex = MX + t[0] * MS;
        const ey = t[1] * MS;
        const u = R();
        const cx = (c[2] + ex) / 2;
        const cy = (c[3] + ey) / 2 + 0.35; // дуга
        const x = (1 - u) * (1 - u) * c[2] + 2 * (1 - u) * u * cx + u * u * ex;
        const y = (1 - u) * (1 - u) * c[3] + 2 * (1 - u) * u * cy + u * u * ey;
        const w = 0.035 * (1 - u) + 0.006;
        put(x + jit(w), y + jit(w), jit(w) + Math.sin(u * Math.PI) * 0.12, flow(c[1], u));
      },
    ],
  ];
}

/** Публикации по городам: только города, которые есть на карте (правило 2). */
function knownCities(cities: readonly DotsCityCount[]): (readonly [string, number])[] {
  const G = geo();
  const out: [string, number][] = [];
  for (const c of cities) {
    const n = Math.max(0, Math.floor(c.count));
    if (n > 0 && G.dataCities.has(c.city)) out.push([c.city, n]);
  }
  return out;
}

/** Найдено: на карте загораются города, где вышли публикации */
function found(known: readonly (readonly [string, number])[]): Part[] {
  const G = geo();
  const at = (name: string): Pt => G.dataCities.get(name) ?? [0, 0];
  const parts: Part[] = mapParts({
    outline: 0.15,
    outlineColor: () => (R() < 0.5 ? BLUE : DIM),
    fill: 0.3,
    fillColor: () => DIM,
    river: 0.08,
    tribs: 0.03,
    riverColor: DIM,
  });
  // Золотые облака сайта (вес 0.3) изображали бы данные тысячами точек — их заменяют
  // точки-данные, ровно по одной на публикацию (добавляются в buildShape).
  if (known.length > 0)
    parts.push([
      0.14,
      (put) => {
        // кольца вокруг найденного — расходятся от города
        const f = known[pick(known.map((x) => Math.sqrt(x[1])))] ?? known[0];
        if (!f) return;
        const c = at(f[0]);
        const r0 = 0.04 + 0.025 * Math.sqrt(f[1]);
        const u = R();
        const a = R() * Math.PI * 2;
        const r = r0 + u * 0.12;
        put(c[0] + Math.cos(a) * r, c[1] + Math.sin(a) * r, 0, flow(GOLD, u));
      },
    ]);
  parts.push([
    0.08,
    (put) => {
      // остальные города — тихо
      const names = [...G.cities.keys()];
      const c = cityAt(names[Math.floor(R() * names.length)] ?? 'Красноярск');
      put(c[0] + gauss() * 0.01, c[1] + gauss() * 0.01, 0, DIM);
    },
  ]);
  return parts;
}

const PLATFORM_COLOR: Readonly<Record<PlatformId, number>> = { vk: VK, ok: OK, max: MAX };
/** Пример сайта: 15 размещений, 9 / 4 / 2 */
// prettier-ignore
const EXAMPLE_PLACEMENTS: readonly PlatformId[] = [
  'vk', 'vk', 'vk', 'vk', 'vk', 'vk', 'vk', 'vk', 'vk', 'ok', 'ok', 'ok', 'ok', 'max', 'max',
];

/**
 * «Распространение»: вспышка из точки-источника и волны к перепечаткам.
 * placements не переданы — пример сайта (кольцо = 1 + i % 5). Переданы — опор ровно столько,
 * сколько размещений, кольцо — очередь публикации: раньше опубликовано — ближе к источнику.
 */
function spread(placements: readonly PlatformId[] | undefined): Part[] {
  const SX = 0.1; // источник почти в центре: волны не заходят под текст
  const PY = -0.3;
  const TILT = 0.5;
  const STEP = 0.28;
  const ct = Math.cos(TILT);
  const st = Math.sin(TILT);
  // наклон плоскости к зрителю
  const rot = (x: number, y: number, z: number): [number, number, number] => [
    x,
    ct * y - st * z,
    st * y + ct * z,
  ];
  const plats = placements ?? EXAMPLE_PLACEMENTS;
  const perRing = Math.max(1, Math.ceil(plats.length / 5));
  const nodes = plats.map((p, i) => {
    const ring = placements ? 1 + Math.floor(i / perRing) : 1 + (i % 5);
    const a = (i * 2.399) % (Math.PI * 2);
    return {
      x: SX + Math.cos(a) * ring * STEP,
      z: Math.sin(a) * ring * STEP,
      h: 0.12 + (i % 4) * 0.07,
      c: PLATFORM_COLOR[p],
    };
  });
  const parts: Part[] = [
    [
      0.06,
      (put) => {
        const p = rot(SX + gauss() * 0.04, PY + 0.02 + Math.abs(gauss()) * 0.04, gauss() * 0.04);
        put(p[0], p[1], p[2], GOLD);
      },
    ],
    [
      0.2,
      (put) => {
        // вспышка: лучи от источника вверх и в стороны
        const z = R();
        const ph = R() * Math.PI * 2;
        const s = Math.sqrt(1 - z * z);
        const l = Math.pow(R(), 1.8) * 0.85;
        const p = rot(SX + s * Math.cos(ph) * l, PY + z * l, s * Math.sin(ph) * l);
        put(p[0], p[1], p[2], flow(GOLD, l / 0.85));
      },
    ],
    [
      0.34,
      (put) => {
        // волны по «земле»
        const k = 1 + Math.floor(R() * 5);
        const r = k * STEP + jit(0.03);
        const a = R() * Math.PI * 2;
        const p = rot(SX + Math.cos(a) * r, PY, Math.sin(a) * r);
        put(p[0], p[1], p[2], flow(R() < 0.75 ? BLUE : WHITE, r / (5.5 * STEP)));
      },
    ],
  ];
  if (nodes.length > 0)
    parts.push(
      [
        0.24,
        (put) => {
          // перепечатки: точки цвета площадки на ножках
          const n = nodes[Math.floor(R() * nodes.length)] ?? nodes[0];
          if (!n) return;
          let p: [number, number, number];
          if (R() < 0.35) p = rot(n.x + jit(0.006), PY + R() * n.h, n.z + jit(0.006));
          else p = rot(n.x + gauss() * 0.025, PY + n.h + gauss() * 0.025, n.z + gauss() * 0.025);
          put(p[0], p[1], p[2], n.c);
        },
      ],
      [
        0.16,
        (put) => {
          // дуги от источника к перепечаткам
          const n = nodes[Math.floor(R() * nodes.length)] ?? nodes[0];
          if (!n) return;
          const u = R();
          const x = SX + (n.x - SX) * u;
          const z = n.z * u;
          const y = PY + Math.sin(u * Math.PI) * 0.35 + n.h * u;
          const p = rot(x + jit(0.01), y + jit(0.01), z + jit(0.01));
          put(p[0], p[1], p[2], flow(WHITE, u));
        },
      ],
    );
  return parts;
}

/** Выгрузка XLSX: точки складываются в сетку таблицы */
function grid(): Part[] {
  const W = 1.05;
  const H = 0.72;
  const ROWS = 7;
  const COLS = 5;
  const colX = [-W, -0.78, -0.2, 0.3, 0.72, W]; // № · площадка · заголовок · дата · ссылка
  const rowY = (k: number) => H - k * ((2 * H) / ROWS);
  const cells: [number, number, number][] = [];
  for (let r = 1; r < ROWS; r += 1)
    for (let c = 0; c < COLS; c += 1) cells.push([r, c, 0.35 + R() * 0.55]);
  return [
    [
      0.32,
      (put) => {
        // линии сетки
        if (R() < 0.55) {
          const k = Math.floor(R() * (ROWS + 1));
          put(-W + R() * 2 * W, rowY(k) + jit(0.006), jit(0.02), R() < 0.6 ? BLUE : WHITE);
        } else {
          const x = colX[Math.floor(R() * colX.length)] ?? 0;
          put(x + jit(0.006), -H + R() * 2 * H, jit(0.02), R() < 0.6 ? BLUE : WHITE);
        }
      },
    ],
    [
      0.16,
      (put) => {
        // строка заголовков — золотом
        put(-W + R() * 2 * W, rowY(0) - R() * ((2 * H) / ROWS), jit(0.02), GOLD);
      },
    ],
    [
      0.4,
      (put) => {
        // данные в ячейках
        const cell = cells[Math.floor(R() * cells.length)] ?? [1, 0, 0.5];
        const x0 = (colX[cell[1]] ?? 0) + 0.04;
        const x1 = (colX[cell[1] + 1] ?? 0) - 0.04;
        const y = (rowY(cell[0]) + rowY(cell[0] + 1)) / 2;
        put(
          x0 + R() * (x1 - x0) * cell[2],
          y + jit(0.03),
          jit(0.02),
          cell[1] === COLS - 1 ? BLUE : WHITE,
        );
      },
    ],
    [
      0.12,
      (put) => {
        // искры вокруг: файл «собирается»
        const a = R() * Math.PI * 2;
        const r = 1.3 + R() * 0.6;
        put(Math.cos(a) * r, Math.sin(a) * r * 0.7, jit(0.8), R() < 0.5 ? DIM : GOLD);
      },
    ],
  ];
}

/** Пусто: точки спокойно рассеиваются и гаснут */
function empty(): Part[] {
  return [
    [
      1,
      (put) => {
        put((R() - 0.5) * 8, (R() - 0.5) * 5, -2.4 + R() * 3.2, R() < 0.88 ? DIM : BLUE);
      },
    ],
  ];
}

/** Пыль — модели нет, частицы рассеяны по всему пространству */
function dust(): Part[] {
  return [
    [
      1,
      (put) => {
        put((R() - 0.5) * 7.5, (R() - 0.5) * 4.6, -2.4 + R() * 3.4, pick([40, 35, 25]));
      },
    ],
  ];
}

/** Период моста: повторы периода собирают мост во всю ширину (engine: копии с uShift). */
export const BRIDGE_PERIOD = 4.4;

/**
 * Местный образ: Коммунальный мост через Енисей — тот, что на десятирублёвой купюре.
 * Модель — один «период» моста: семь пролётов от −2.2 до 2.2, без правой опоры и с водой
 * ровно в этих границах. Во всю ширину мост собирается из повторов периода — пролёты те же,
 * густота точек та же (как на сайте).
 */
function bridge(): Part[] {
  const DECK = 0.28;
  const WATER = -0.55;
  const SPRING = WATER + 0.16;
  const CROWN = DECK - 0.05;
  const Z = 0.12;
  const PIERS = [-2.2, -1.62, -1.06, -0.36, 0.36, 1.06, 1.62, 2.2];
  const span = (): [number, number] => {
    const k = Math.floor(R() * (PIERS.length - 1));
    return [PIERS[k] ?? 0, PIERS[k + 1] ?? 0];
  };
  const archY = (t: number) => SPRING + (CROWN - SPRING) * (1 - t * t);
  return [
    [0.22, (put) => put(-2.2 + R() * 4.4, DECK + jit(0.012), jit(2 * Z), R() < 0.7 ? WHITE : BLUE)],
    [
      0.07,
      (put) => {
        // перила и столбики
        const z = R() < 0.5 ? -Z : Z;
        if (R() < 0.7) put(-2.2 + R() * 4.4, DECK + 0.07, z, WHITE);
        else {
          const x = -2.2 + Math.floor(R() * 55) * 0.08;
          put(x, DECK + R() * 0.07, z, WHITE);
        }
      },
    ],
    [
      0.24,
      (put) => {
        // арки
        const s = span();
        const t = R() * 2 - 1;
        const w = s[1] - s[0];
        put(
          s[0] + (w * (t + 1)) / 2 + jit(0.008),
          archY(t) + jit(0.012),
          (R() < 0.5 ? -Z : Z) * 0.85 + jit(0.01),
          GOLD,
        );
      },
    ],
    [
      0.12,
      (put) => {
        // стойки между аркой и настилом
        const s = span();
        const w = s[1] - s[0];
        const t = Math.round((R() * 2 - 1) * 6) / 6;
        const y0 = archY(t);
        put(
          s[0] + (w * (t + 1)) / 2 + jit(0.006),
          y0 + R() * (DECK - y0),
          (R() < 0.5 ? -Z : Z) * 0.85,
          BLUE,
        );
      },
    ],
    [
      0.08,
      (put) => {
        // опоры (правая — это левая опора следующего повтора)
        const x = PIERS[Math.floor(R() * (PIERS.length - 1))] ?? 0;
        put(x + jit(0.06), WATER + R() * (SPRING + 0.04 - WATER), jit(2 * Z), WHITE);
      },
    ],
    [
      0.178,
      (put) => {
        // Енисей под мостом течёт (густота воды — прежняя: 0.21 на 5.2 единицы);
        // четыре импульса на период — на стыках повторов течение не прерывается
        const x = -2.2 + R() * 4.4;
        const z = -0.7 + R() * 1.2;
        put(
          x,
          WATER + 0.02 * Math.sin(x * 6 + z * 4) + jit(0.01),
          z,
          flow(R() < 0.8 ? BLUE : WHITE, (x + 2.2) / 5.5),
        );
      },
    ],
    [
      0.06,
      (put) => {
        // фонари: 15 на период, шаг почти прежний (0.293 вместо 0.3)
        const x = -2.2 + (Math.floor(R() * 15) + 0.5) * (4.4 / 15);
        put(
          x + gauss() * 0.012,
          DECK + 0.2 + gauss() * 0.012,
          (R() < 0.5 ? -Z : Z) + gauss() * 0.012,
          GOLD,
        );
      },
    ],
  ];
}

/** Местный образ: часовня Параскевы Пятницы — восьмерик с окнами, шатёр, луковица, крест */
function chapel(): Part[] {
  const Y = -0.1;
  const octV = (r: number, k: number): Pt => {
    const a = (k * Math.PI) / 4 + Math.PI / 8;
    return [r * Math.cos(a), r * Math.sin(a)];
  };
  const octPt = (r: number, u: number): [number, number, number, number] => {
    const k = Math.floor(u) % 8;
    const f = u - Math.floor(u);
    const A = octV(r, k);
    const B = octV(r, k + 1);
    return [A[0] + (B[0] - A[0]) * f, A[1] + (B[1] - A[1]) * f, k, f];
  };
  const FACE = 2 * 0.42 * Math.sin(Math.PI / 8);
  const WW = 0.05;
  const WTOP = -0.36;
  const WBOT = -0.68;
  const inWindow = (k: number, f: number, y: number): boolean => {
    if (k % 2 === 0) return false;
    const dx = (f - 0.5) * FACE;
    if (Math.abs(dx) > WW) return false;
    if (y > WBOT && y < WTOP) return true;
    const dy = y - WTOP;
    return dy >= 0 && dx * dx + dy * dy < WW * WW;
  };
  return [
    [
      0.07,
      (put) => {
        // цоколь
        let p: [number, number, number, number];
        let y: number;
        if (R() < 0.3) {
          p = octPt(0.42 + R() * 0.08, R() * 8);
          y = -0.88;
        } else {
          p = octPt(0.5, R() * 8);
          y = -1.0 + R() * 0.12;
        }
        put(p[0], y + Y, p[1], tone(0.35));
      },
    ],
    [
      0.3,
      (put) => {
        // стены
        for (let i = 0; i < 30; i += 1) {
          const y = -0.88 + R() * 0.76;
          const p = octPt(0.42, R() * 8);
          if (!inWindow(p[2], p[3], y)) {
            put(p[0], y + Y, p[1], tone(0.55));
            return;
          }
        }
        put(0, -0.5 + Y, 0, WHITE);
      },
    ],
    [
      0.06,
      (put) => {
        // наличники
        const k = 1 + 2 * Math.floor(R() * 4);
        const s = R() * 4;
        let dx: number;
        let y: number;
        if (s < 1) {
          dx = -WW;
          y = WBOT + (WTOP - WBOT) * s;
        } else if (s < 2) {
          dx = WW;
          y = WBOT + (WTOP - WBOT) * (s - 1);
        } else if (s < 2.6) {
          dx = -WW + (2 * WW * (s - 2)) / 0.6;
          y = WBOT;
        } else {
          const a = (Math.PI * (s - 2.6)) / 1.4;
          dx = WW * Math.cos(a);
          y = WTOP + WW * Math.sin(a);
        }
        const p = octPt(0.425, k + 0.5 + dx / FACE);
        put(p[0], y + Y, p[1], tone(0.95, 0.1));
      },
    ],
    [
      0.04,
      (put) => {
        // рёбра стен
        const v = octV(0.425, Math.floor(R() * 8));
        put(v[0] + jit(0.01), -0.88 + R() * 0.76 + Y, v[1] + jit(0.01), tone(0.15));
      },
    ],
    [
      0.04,
      (put) => {
        // карниз
        const p = octPt(0.47 + R() * 0.02, R() * 8);
        put(p[0], -0.12 + R() * 0.06 + Y, p[1], tone(0.75));
      },
    ],
    [
      0.24,
      (put) => {
        // шатёр: равномерно по площади
        let t: number;
        do {
          t = R();
        } while (R() > 1 - t * 0.79);
        const p = octPt(0.48 * (1 - t) + 0.1 * t, R() * 8);
        put(p[0], -0.06 + t * 0.58 + Y, p[1], tone(0.2 + t * 0.25));
      },
    ],
    [
      0.04,
      (put) => {
        // рёбра шатра
        const k = Math.floor(R() * 8);
        const t = R();
        const a = octV(0.48, k);
        const b = octV(0.1, k);
        put(a[0] + (b[0] - a[0]) * t, -0.06 + t * 0.58 + Y, a[1] + (b[1] - a[1]) * t, tone(0.7));
      },
    ],
    [
      0.03,
      (put) => {
        // барабан
        const a = R() * Math.PI * 2;
        put(0.1 * Math.cos(a), 0.52 + R() * 0.12 + Y, 0.1 * Math.sin(a), tone(0.5));
      },
    ],
    [
      0.12,
      (put) => {
        // луковица
        const t = R();
        const r = 0.19 * Math.sin(Math.PI * Math.pow(0.15 + 0.85 * t, 0.8));
        const a = R() * Math.PI * 2;
        put(r * Math.cos(a), 0.64 + t * 0.36 + Y, r * Math.sin(a), tone(0.95, 0.1));
      },
    ],
    [
      0.035,
      (put) => {
        // крест
        const s = R();
        let x: number;
        let y: number;
        if (s < 0.55) {
          x = 0;
          y = 1.0 + R() * 0.34;
        } else if (s < 0.85) {
          x = -0.08 + R() * 0.16;
          y = 1.25;
        } else {
          x = -0.05 + R() * 0.1;
          y = 1.13 + x * 0.35;
        }
        put(x + jit(0.008), y + Y, jit(0.008), GOLD);
      },
    ],
    [
      0.035,
      (put) => {
        // площадка вокруг
        const a = R() * Math.PI * 2;
        const r = 0.6 + R() * 0.3;
        put(r * Math.cos(a), -1.0 + Y, r * Math.sin(a), tone(0.1));
      },
    ],
  ];
}

/* ---------- Параметры форм ---------- */

export type ShapeId =
  | 'krai'
  | 'bridge'
  | 'listening'
  | 'searching'
  | 'found'
  | 'spread'
  | 'grid'
  | 'empty'
  | 'failure'
  | 'dust'
  | 'chapel';

export interface ShapeMeta {
  /** false — облако без формы */
  model: boolean;
  /** Во всю ширину (мост) */
  wide?: boolean;
  width?: number;
  /** Период модели по x: форма повторяется, пока не дойдёт до краёв холста (мост) */
  period?: number;
  /**
   * Поток к полю ввода («система слушает»): src — центр облака, end — конец хвоста в модели.
   * Хвост изгибается так, чтобы его конец упёрся в поле (engine.setTarget).
   */
  tail?: { src: readonly [number, number, number]; end: readonly [number, number, number] };
  /** По кругу; иначе покачивание base ± amp */
  spin?: boolean;
  base: number;
  amp?: number;
  scale: number;
  lift?: number;
  shift?: number;
}

/** Параметры форм сайта: вращение, масштаб, сдвиги — числа из particles.js (META). */
export const META: Readonly<Record<ShapeId, ShapeMeta>> = {
  krai: { model: true, base: 0, amp: 0.32, scale: 1.0 },
  bridge: {
    model: true,
    wide: true,
    width: 5.2,
    period: BRIDGE_PERIOD,
    base: -0.14,
    amp: 0.12,
    scale: 1.0,
  },
  listening: {
    model: true,
    base: 0.1,
    amp: 0.2,
    scale: 1.0,
    tail: { src: [-0.35, 0, 0], end: [1.9, -0.066, 0] },
  },
  searching: { model: true, base: -0.15, amp: 0.16, scale: 0.85 },
  found: { model: true, base: 0.12, amp: 0.25, scale: 1.0 },
  spread: { model: true, base: 0.35, amp: 0.3, scale: 0.92, shift: 0.06 },
  grid: { model: true, base: -0.38, amp: 0.18, scale: 0.9 },
  empty: { model: false, spin: true, base: 0, scale: 1.0 },
  failure: { model: true, base: 0.15, amp: 0.16, scale: 0.85 },
  dust: { model: false, spin: true, base: 0, scale: 1.0 },
  // на сайте — справа от огромной надписи, над колонками подвала
  chapel: { model: true, spin: true, base: 0.5, scale: 0.74, lift: 0.42, shift: 0.06 },
};

/** Порядок форм на сайте — от него зависит свой поток случайных чисел у каждой формы. */
export const SHAPE_IDS = Object.keys(META) as ShapeId[];

/* ---------- Сборка ---------- */

export interface ShapeData {
  /** searching / failure: состояние облака каждой площадки */
  platforms?: Partial<Record<PlatformId, DotsPlatformState>>;
  /** found: публикации по городам */
  cities?: readonly DotsCityCount[];
  /** spread: площадки размещений в порядке публикации */
  placements?: readonly PlatformId[];
}

export interface ShapeRequest {
  id: ShapeId;
  data?: ShapeData;
}

const PLATFORMS: readonly PlatformId[] = ['vk', 'ok', 'max'];

/** Состояния облаков: у `searching` по умолчанию все ищут, у `failure` — как на сайте, сбой MAX. */
function statesFor(req: ShapeRequest): PlatformStates {
  const given = req.data?.platforms ?? {};
  const any = PLATFORMS.some((p) => given[p] !== undefined);
  if (req.id === 'failure' && !any) return { vk: 'active', ok: 'active', max: 'failed' };
  const fallback: DotsPlatformState = req.id === 'failure' ? 'failed' : 'active';
  return { vk: given.vk ?? fallback, ok: given.ok ?? fallback, max: given.max ?? fallback };
}

/** Ключ формы: одинаковые входы — одинаковые точки (кэш буферов). */
export function shapeKey(req: ShapeRequest): string {
  switch (req.id) {
    case 'searching':
    case 'failure': {
      const s = statesFor(req);
      return `${req.id}|${s.vk},${s.ok},${s.max}`;
    }
    case 'found':
      return `found|${knownCities(req.data?.cities ?? [])
        .map(([c, n]) => `${c}:${n}`)
        .join(',')}`;
    case 'spread': {
      const p = req.data?.placements;
      return `spread|${p ? p.join(',') : 'example'}`;
    }
    default:
      return req.id;
  }
}

/** Сколько точек-данных в форме (правило честности 1): для проверки и витрины. */
export function dataCount(req: ShapeRequest): number {
  if (req.id !== 'found') return 0;
  return knownCities(req.data?.cities ?? []).reduce((s, [, n]) => s + n, 0);
}

/**
 * Точки формы для N частиц. Точки-данные `found` занимают последние места буфера
 * (декор не сдвигается — при смене числа публикаций перелетают только они), не больше
 * половины бюджета.
 */
export function buildShape(req: ShapeRequest, N: number): Float32Array {
  R = rng(SEED + SHAPE_IDS.indexOf(req.id) * 7919);
  let parts: Part[];
  let known: (readonly [string, number])[] = [];
  switch (req.id) {
    case 'krai':
      parts = krai();
      break;
    case 'bridge':
      parts = bridge();
      break;
    case 'listening':
      parts = listening();
      break;
    case 'searching':
    case 'failure':
      parts = clouds(statesFor(req));
      break;
    case 'found':
      known = knownCities(req.data?.cities ?? []);
      parts = found(known);
      break;
    case 'spread':
      parts = spread(req.data?.placements);
      break;
    case 'grid':
      parts = grid();
      break;
    case 'empty':
      parts = empty();
      break;
    case 'dust':
      parts = dust();
      break;
    case 'chapel':
      parts = chapel();
      break;
  }
  const a = compose(parts, N);
  if (known.length > 0) {
    const G = geo();
    const total = known.reduce((s, [, n]) => s + n, 0);
    let i = N - Math.min(total, Math.floor(N / 2));
    for (const [city, n] of known) {
      const p = G.dataCities.get(city) ?? [0, 0];
      for (let k = 0; k < n && i < N; k += 1, i += 1) {
        a[i * 4] = p[0];
        a[i * 4 + 1] = p[1];
        a[i * 4 + 2] = 0.02;
        a[i * 4 + 3] = GOLD + DATA + Math.min(k, DATA_SLOTS - 1) / DATA_SLOTS;
      }
    }
  }
  return a;
}
