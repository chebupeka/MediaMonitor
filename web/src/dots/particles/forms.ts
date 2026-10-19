/**
 * Формы точек по словарю 08-visual-concept.md — тот же язык, что на сайте «Стрежень».
 * Каждая форма — N точек (x, y, z, код). Код:
 *   0–7   — цвет палитры (см. PAL);
 *   +8    — точка «течёт»: дробная часть — её место на пути 0…1, по пути бегут импульсы;
 *   +16   — точка-данные: одна публикация, крупнее и ярче декора (правило честности 1).
 * Генерация детерминированная: одинаковые входы дают одинаковую картинку.
 */
import type { PlatformId } from '@/api/types';
import {
  KRAI_CITIES,
  KRAI_OUTLINE,
  SEVERNAYA_ZEMLYA,
  TRIBUTARIES,
  YENISEI,
  insidePolygon,
  project,
  seededRandom,
  type LonLat,
} from '../krai-geo';
import type { DotsCityCount, DotsForm, DotsPlatformState } from '../types';

/** Индексы палитры */
export const PAL = {
  blue: 0,
  white: 1,
  gold: 2,
  vk: 3,
  ok: 4,
  max: 5,
  grey: 6,
  dim: 7,
} as const;

const FLOW = 8;
const DATA = 16;

const PLATFORM_COLOR: Record<PlatformId, number> = { vk: PAL.vk, ok: PAL.ok, max: PAL.max };

export interface FormInput {
  form: DotsForm;
  cities: readonly DotsCityCount[];
  platforms: Partial<Record<PlatformId, DotsPlatformState>>;
  placements: readonly PlatformId[];
}

type Put = (x: number, y: number, z: number, code: number) => void;
type Part = readonly [weight: number, emit: (put: Put) => void];

// ---------------------------------------------------------------- случайные числа

let R = seededRandom(20261019);
const jit = (a: number): number => (R() - 0.5) * a;
function gauss(): number {
  const u = R() || 1e-6;
  const v = R();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}
function flow(color: number, f: number): number {
  return color + FLOW + Math.max(0, Math.min(0.999, f));
}
function pick(weights: readonly number[]): number {
  let sum = 0;
  for (const w of weights) sum += w;
  let r = R() * sum;
  for (let i = 0; i < weights.length; i += 1) {
    r -= weights[i] ?? 0;
    if (r <= 0) return i;
  }
  return weights.length - 1;
}

// ---------------------------------------------------------------- география

type Pt = readonly [number, number];

interface Polyline {
  pts: Pt[];
  total: number;
  at: (u: number) => Pt;
}

function polyline(pts: Pt[], closed: boolean): Polyline {
  const path = closed && pts[0] ? [...pts, pts[0]] : pts;
  const cum = [0];
  for (let i = 1; i < path.length; i += 1) {
    const a = path[i - 1] ?? [0, 0];
    const b = path[i] ?? [0, 0];
    cum.push((cum[i - 1] ?? 0) + Math.hypot(b[0] - a[0], b[1] - a[1]));
  }
  const total = cum[cum.length - 1] ?? 0;
  return {
    pts,
    total,
    at(u) {
      const d = u * total;
      let k = 1;
      while (k < cum.length - 1 && (cum[k] ?? 0) < d) k += 1;
      const a = path[k - 1] ?? [0, 0];
      const b = path[k] ?? a;
      const c0 = cum[k - 1] ?? 0;
      const t = (d - c0) / Math.max(1e-9, (cum[k] ?? c0) - c0);
      return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
    },
  };
}

/** Край высотой MAP_H с центром в начале координат; ось y — вверх. */
const MAP_H = 2.5;

interface Geo {
  outline: Polyline;
  islands: Polyline;
  yenisei: Polyline;
  tribs: Polyline[];
  cities: Map<string, { p: Pt; major: boolean }>;
  bbox: readonly [x0: number, x1: number, y0: number, y1: number];
}

let geoCache: Geo | null = null;

function geo(): Geo {
  if (geoCache) return geoCache;
  const all = [...KRAI_OUTLINE, ...SEVERNAYA_ZEMLYA].map(project);
  let x0 = Infinity;
  let x1 = -Infinity;
  let y0 = Infinity;
  let y1 = -Infinity;
  for (const [x, y] of all) {
    x0 = Math.min(x0, x);
    x1 = Math.max(x1, x);
    y0 = Math.min(y0, -y);
    y1 = Math.max(y1, -y);
  }
  const s = MAP_H / (y1 - y0);
  const cx = (x0 + x1) / 2;
  const cy = (y0 + y1) / 2;
  // project() даёт ось y вниз — разворачиваем
  const norm = (p: LonLat): Pt => {
    const [x, y] = project(p);
    return [(x - cx) * s, (-y - cy) * s];
  };
  const cities = new Map<string, { p: Pt; major: boolean }>();
  for (const c of KRAI_CITIES) cities.set(c.name, { p: norm([c.lon, c.lat]), major: c.major });
  geoCache = {
    outline: polyline(KRAI_OUTLINE.map(norm), true),
    islands: polyline(SEVERNAYA_ZEMLYA.map(norm), true),
    yenisei: polyline(YENISEI.map(norm), false),
    tribs: TRIBUTARIES.map((t) => polyline(t.map(norm), false)),
    cities,
    bbox: [(x0 - cx) * s, (x1 - cx) * s, (y0 - cy) * s, (y1 - cy) * s],
  };
  return geoCache;
}

const relief = (x: number, y: number): number =>
  0.05 * Math.sin(x * 6 + 1) * Math.cos(y * 4) + jit(0.05);

interface MapOptions {
  s?: number;
  ox?: number;
  outline?: number;
  outlineColor?: () => number;
  fill?: number;
  fillColor?: () => number;
  river?: number;
  tribs?: number;
  riverFlow?: boolean;
  cities?: number;
}

/** Части карты края: контур, заливка, Енисей с притоками, города. */
function mapParts(o: MapOptions): Part[] {
  const g = geo();
  const s = o.s ?? 1;
  const ox = o.ox ?? 0;
  const put3 = (put: Put, p: Pt, z: number, code: number) =>
    put(ox + p[0] * s, p[1] * s, z * s, code);
  const parts: Part[] = [];
  const outlineColor = o.outlineColor ?? (() => PAL.blue);
  const fillColor = o.fillColor ?? (() => PAL.dim);
  if (o.outline)
    parts.push([
      o.outline,
      (put) => {
        const p = (R() < 0.92 ? g.outline : g.islands).at(R());
        put3(put, [p[0] + jit(0.012), p[1] + jit(0.012)], jit(0.04), outlineColor());
      },
    ]);
  if (o.fill)
    parts.push([
      o.fill,
      (put) => {
        const [bx0, bx1, by0, by1] = g.bbox;
        for (let i = 0; i < 60; i += 1) {
          const x = bx0 + R() * (bx1 - bx0);
          const y = by0 + R() * (by1 - by0);
          if (insidePolygon(x, y, g.outline.pts) || insidePolygon(x, y, g.islands.pts)) {
            put3(put, [x, y], relief(x, y), fillColor());
            return;
          }
        }
        put3(put, g.outline.at(R()), 0, fillColor());
      },
    ]);
  if (o.river)
    parts.push([
      o.river,
      (put) => {
        const u = R(); // Енисей течёт с юга на север
        const p = g.yenisei.at(u);
        put3(
          put,
          [p[0] + jit(0.022), p[1] + jit(0.022)],
          jit(0.03),
          o.riverFlow ? flow(PAL.blue, u) : PAL.dim,
        );
      },
    ]);
  if (o.tribs)
    parts.push([
      o.tribs,
      (put) => {
        const t = g.tribs[pick(g.tribs.map((x) => x.total))] ?? g.yenisei;
        const u = R();
        const p = t.at(u);
        put3(
          put,
          [p[0] + jit(0.016), p[1] + jit(0.016)],
          jit(0.03),
          o.riverFlow ? flow(PAL.blue, u) : PAL.dim,
        );
      },
    ]);
  if (o.cities)
    parts.push([
      o.cities,
      (put) => {
        const list = [...g.cities.entries()];
        const [name, c] = list[pick(list.map(([, v]) => (v.major ? 3 : 1)))] ?? [
          '',
          { p: [0, 0] as Pt, major: false },
        ];
        const r = c.major ? 0.026 : 0.013;
        put3(
          put,
          [c.p[0] + gauss() * r, c.p[1] + gauss() * r],
          gauss() * r,
          name === 'Красноярск' ? PAL.gold : PAL.white,
        );
      },
    ]);
  return parts;
}

// ---------------------------------------------------------------- формы

function krai(): Part[] {
  return [
    ...mapParts({
      outline: 0.2,
      outlineColor: () => (R() < 0.65 ? PAL.blue : PAL.white),
      fill: 0.4,
      fillColor: () => (R() < 0.55 ? PAL.dim : PAL.blue),
      river: 0.2,
      tribs: 0.09,
      riverFlow: true,
      cities: 0.07,
    }),
    [
      0.04,
      (put) => {
        const [x0, x1, y0, y1] = geo().bbox;
        put(x0 - 0.4 + R() * (x1 - x0 + 0.8), y0 - 0.2 + R() * (y1 - y0 + 0.4), jit(0.8), PAL.dim);
      },
    ],
  ];
}

/** Система слушает: облако оживает и тянется вниз — к полю ввода под картинкой. */
function listening(): Part[] {
  return [
    [
      0.52,
      (put) => {
        const r = Math.sqrt(R());
        put(gauss() * 0.42 * r, 0.45 + gauss() * 0.3 * r, gauss() * 0.32 * r, pick([45, 35, 20]));
      },
    ],
    [
      0.36,
      (put) => {
        const u = Math.pow(R(), 0.8);
        const w = 0.22 * (1 - u) + 0.02;
        put(
          0.12 * Math.sin(u * 3.2) + gauss() * w * 0.5,
          0.3 - u * 1.75,
          gauss() * w * 0.5,
          flow(R() < 0.6 ? PAL.blue : PAL.white, u),
        );
      },
    ],
    [
      0.12,
      (put) => {
        const a = R() * Math.PI * 2;
        const r = 0.6 + R() * 0.5;
        put(
          Math.cos(a) * r * 1.3,
          0.45 + Math.sin(a) * r * 0.7,
          jit(0.6),
          R() < 0.5 ? PAL.dim : PAL.blue,
        );
      },
    ],
  ];
}

const CLOUDS: readonly (readonly [PlatformId, number, number])[] = [
  ['vk', -1.05, 0.72],
  ['ok', -1.28, 0],
  ['max', -1.05, -0.72],
];
const TARGETS = ['Красноярск', 'Норильск', 'Канск', 'Ачинск', 'Лесосибирск', 'Минусинск'];

/**
 * Идёт поиск: три облака цветов площадок, из них точки текут на карту.
 * active — поток идёт; done — поток закончился; failed — облако серое и мерцает; idle — облако тусклое.
 */
function clouds(
  platforms: Partial<Record<PlatformId, DotsPlatformState>>,
  fallback: DotsPlatformState,
): Part[] {
  const MS = 0.72;
  const MX = 0.82;
  const g = geo();
  const stateOf = (p: PlatformId): DotsPlatformState => platforms[p] ?? fallback;
  const colorOf = (p: PlatformId): number => {
    const st = stateOf(p);
    return st === 'failed' ? PAL.grey : st === 'idle' ? PAL.dim : PLATFORM_COLOR[p];
  };
  return [
    ...mapParts({
      s: MS,
      ox: MX,
      outline: 0.12,
      outlineColor: () => (R() < 0.5 ? PAL.blue : PAL.dim),
      fill: 0.17,
      river: 0.05,
      riverFlow: true,
    }),
    [
      0.3,
      (put) => {
        const [p, cx, cy] = CLOUDS[Math.floor(R() * 3)] ?? CLOUDS[0] ?? ['vk', 0, 0];
        const bad = stateOf(p) === 'failed';
        const r = Math.pow(R(), 0.6) * (bad ? 1.25 : 1);
        put(cx + gauss() * 0.17 * r, cy + gauss() * 0.15 * r, gauss() * 0.16 * r, colorOf(p));
      },
    ],
    [
      0.36,
      (put) => {
        const [p, cx, cy] = CLOUDS[Math.floor(R() * 3)] ?? CLOUDS[0] ?? ['vk', 0, 0];
        if (stateOf(p) !== 'active') {
          // нет потока — точки остаются в облаке
          put(cx + gauss() * 0.22, cy + gauss() * 0.2, gauss() * 0.2, colorOf(p));
          return;
        }
        const t = g.cities.get(TARGETS[Math.floor(R() * TARGETS.length)] ?? 'Красноярск')?.p ?? [
          0, 0,
        ];
        const ex = MX + t[0] * MS;
        const ey = t[1] * MS;
        const u = R();
        const mx = (cx + ex) / 2;
        const my = (cy + ey) / 2 + 0.35; // дуга
        const x = (1 - u) * (1 - u) * cx + 2 * (1 - u) * u * mx + u * u * ex;
        const y = (1 - u) * (1 - u) * cy + 2 * (1 - u) * u * my + u * u * ey;
        const w = 0.035 * (1 - u) + 0.006;
        put(
          x + jit(w),
          y + jit(w),
          jit(w) + Math.sin(u * Math.PI) * 0.12,
          flow(PLATFORM_COLOR[p], u),
        );
      },
    ],
  ];
}

/**
 * Найдено: на карте загораются города. Точек-данных ровно столько, сколько публикаций
 * с известным городом (правила честности 1 и 2); остальное — тихая карта и кольца.
 */
function found(cities: readonly DotsCityCount[], dataDots: { x: number; y: number }[]): Part[] {
  const g = geo();
  const known = cities.filter((c) => g.cities.has(c.city) && c.count > 0);
  for (const c of known) {
    const p = g.cities.get(c.city)?.p ?? [0, 0];
    for (let i = 0; i < c.count; i += 1) {
      // спираль вокруг города: точки не сливаются, их можно сосчитать
      const a = i * 2.399;
      const r = i === 0 ? 0 : 0.028 * Math.sqrt(i);
      dataDots.push({ x: p[0] + Math.cos(a) * r, y: p[1] + Math.sin(a) * r });
    }
  }
  const parts: Part[] = mapParts({
    outline: 0.17,
    outlineColor: () => (R() < 0.5 ? PAL.blue : PAL.dim),
    fill: 0.34,
    river: 0.09,
    tribs: 0.03,
  });
  if (known.length > 0)
    parts.push([
      0.18,
      (put) => {
        const c = known[pick(known.map((k) => Math.sqrt(k.count)))] ?? known[0];
        const p = (c && g.cities.get(c.city)?.p) ?? [0, 0];
        const r0 = 0.05 + 0.025 * Math.sqrt(c?.count ?? 1);
        const u = R();
        const a = R() * Math.PI * 2;
        const r = r0 + u * 0.12;
        put(p[0] + Math.cos(a) * r, p[1] + Math.sin(a) * r, 0, flow(PAL.gold, u));
      },
    ]);
  return parts;
}

/**
 * «Распространение»: вспышка из точки-источника и волны к перепечаткам. Опор ровно
 * столько, сколько размещений (правило честности 1); кольцо — очередь публикации:
 * раньше опубликовано — ближе к источнику. Без данных — пример с сайта (15 размещений).
 */
function spread(placements: readonly PlatformId[]): Part[] {
  const SX = 0.1;
  const PY = -0.3;
  const STEP = 0.28;
  const ct = Math.cos(0.5);
  const st = Math.sin(0.5);
  const rot = (x: number, y: number, z: number): [number, number, number] => [
    x,
    ct * y - st * z,
    st * y + ct * z,
  ];
  const example: PlatformId[] = [
    'vk',
    'vk',
    'vk',
    'vk',
    'vk',
    'vk',
    'vk',
    'vk',
    'vk',
    'ok',
    'ok',
    'ok',
    'ok',
    'max',
    'max',
  ];
  const plats = placements.length > 0 ? placements : example;
  const perRing = Math.max(1, Math.ceil(plats.length / 5));
  const nodes = plats.map((p, i) => {
    const ring = 1 + Math.floor(i / perRing);
    const a = (i * 2.399) % (Math.PI * 2);
    return {
      x: SX + Math.cos(a) * ring * STEP,
      z: Math.sin(a) * ring * STEP,
      h: 0.12 + (i % 4) * 0.07,
      c: PLATFORM_COLOR[p],
    };
  });
  const node = () => nodes[Math.floor(R() * nodes.length)] ?? { x: SX, z: 0, h: 0.1, c: PAL.white };
  return [
    [
      0.06,
      (put) =>
        put(
          ...rot(SX + gauss() * 0.04, PY + 0.02 + Math.abs(gauss()) * 0.04, gauss() * 0.04),
          PAL.gold,
        ),
    ],
    [
      0.2,
      (put) => {
        const z = R();
        const ph = R() * Math.PI * 2;
        const s = Math.sqrt(1 - z * z);
        const l = Math.pow(R(), 1.8) * 0.85;
        put(
          ...rot(SX + s * Math.cos(ph) * l, PY + z * l, s * Math.sin(ph) * l),
          flow(PAL.gold, l / 0.85),
        );
      },
    ],
    [
      0.34,
      (put) => {
        const r = (1 + Math.floor(R() * 5)) * STEP + jit(0.03);
        const a = R() * Math.PI * 2;
        put(
          ...rot(SX + Math.cos(a) * r, PY, Math.sin(a) * r),
          flow(R() < 0.75 ? PAL.blue : PAL.white, r / (5.5 * STEP)),
        );
      },
    ],
    [
      0.24,
      (put) => {
        const n = node();
        if (R() < 0.35) put(...rot(n.x + jit(0.006), PY + R() * n.h, n.z + jit(0.006)), n.c);
        else
          put(
            ...rot(n.x + gauss() * 0.025, PY + n.h + gauss() * 0.025, n.z + gauss() * 0.025),
            n.c,
          );
      },
    ],
    [
      0.16,
      (put) => {
        const n = node();
        const u = R();
        const y = PY + Math.sin(u * Math.PI) * 0.35 + n.h * u;
        put(
          ...rot(SX + (n.x - SX) * u + jit(0.01), y + jit(0.01), n.z * u + jit(0.01)),
          flow(PAL.white, u),
        );
      },
    ],
  ];
}

/** Пусто: точки спокойно рассеиваются и гаснут. */
function empty(): Part[] {
  return [
    [
      1,
      (put) =>
        put((R() - 0.5) * 7, (R() - 0.5) * 3.6, -2.4 + R() * 3.2, R() < 0.88 ? PAL.dim : PAL.blue),
    ],
  ];
}

/** Выгрузка XLSX: точки складываются в сетку таблицы. */
function grid(): Part[] {
  const W = 1.05;
  const H = 0.72;
  const ROWS = 7;
  const COLS = 5;
  const colX = [-W, -0.78, -0.2, 0.3, 0.72, W];
  const rowY = (k: number) => H - k * ((2 * H) / ROWS);
  const cells: [number, number, number][] = [];
  for (let r = 1; r < ROWS; r += 1)
    for (let c = 0; c < COLS; c += 1) cells.push([r, c, 0.35 + R() * 0.55]);
  return [
    [
      0.34,
      (put) => {
        if (R() < 0.55)
          put(
            -W + R() * 2 * W,
            rowY(Math.floor(R() * (ROWS + 1))) + jit(0.006),
            jit(0.02),
            R() < 0.6 ? PAL.blue : PAL.white,
          );
        else
          put(
            (colX[Math.floor(R() * colX.length)] ?? 0) + jit(0.006),
            -H + R() * 2 * H,
            jit(0.02),
            R() < 0.6 ? PAL.blue : PAL.white,
          );
      },
    ],
    [0.16, (put) => put(-W + R() * 2 * W, rowY(0) - R() * ((2 * H) / ROWS), jit(0.02), PAL.gold)],
    [
      0.4,
      (put) => {
        const [row, col, len] = cells[Math.floor(R() * cells.length)] ?? [1, 0, 0.5];
        const x0 = (colX[col] ?? 0) + 0.04;
        const x1 = (colX[col + 1] ?? 0) - 0.04;
        put(
          x0 + R() * (x1 - x0) * len,
          (rowY(row) + rowY(row + 1)) / 2 + jit(0.03),
          jit(0.02),
          col === COLS - 1 ? PAL.blue : PAL.white,
        );
      },
    ],
    [
      0.1,
      (put) => {
        const a = R() * Math.PI * 2;
        const r = 1.3 + R() * 0.5;
        put(Math.cos(a) * r, Math.sin(a) * r * 0.6, jit(0.8), R() < 0.5 ? PAL.dim : PAL.gold);
      },
    ],
  ];
}

// ---------------------------------------------------------------- сборка

/** Ключ формы: одинаковые входы — одинаковые точки (кэш буферов). */
export function formKey(input: FormInput): string {
  const p = input.platforms;
  const cities = input.cities.map((c) => `${c.city}:${c.count}`).join(',');
  return `${input.form}|${p.vk ?? ''}${p.ok ?? ''}${p.max ?? ''}|${cities}|${input.placements.join(',')}`;
}

/** Точки формы для `count` частиц. Точки-данные идут первыми и не перемешиваются с декором. */
export function buildForm(input: FormInput, count: number): Float32Array {
  R = seededRandom(20261019);
  const data: { x: number; y: number }[] = [];
  let parts: Part[];
  switch (input.form) {
    case 'krai':
      parts = krai();
      break;
    case 'listening':
      parts = listening();
      break;
    case 'searching':
      parts = clouds(input.platforms, 'active');
      break;
    case 'failure':
      parts = clouds(input.platforms, 'failed');
      break;
    case 'found':
      parts = found(input.cities, data);
      break;
    case 'spread':
      parts = spread(input.placements);
      break;
    case 'empty':
      parts = empty();
      break;
    case 'export':
      parts = grid();
      break;
  }
  const out = new Float32Array(count * 4);
  let i = 0;
  const put: Put = (x, y, z, code) => {
    if (i >= count) return;
    out[i * 4] = x;
    out[i * 4 + 1] = y;
    out[i * 4 + 2] = z;
    out[i * 4 + 3] = code;
    i += 1;
  };
  for (const d of data) put(d.x, d.y, 0.02, PAL.gold + DATA);
  const total = parts.reduce((s, p) => s + p[0], 0) || 1;
  const budget = count - i;
  parts.forEach(([weight, emit], k) => {
    const n = k === parts.length - 1 ? count - i : Math.round((budget * weight) / total);
    for (let j = 0; j < n; j += 1) emit(put);
  });
  return out;
}
