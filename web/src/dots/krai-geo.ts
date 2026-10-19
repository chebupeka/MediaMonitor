/**
 * Упрощённая геометрия Красноярского края для статичной карты из точек.
 * Силуэт аппроксимирован вручную по ~65 опорным точкам (долгота, широта) —
 * только для визуального языка, не для аналитики. Точный силуэт из OpenStreetMap
 * (ODbL) подставит исполнитель «Точки» (08-visual-concept.md, «Техника»).
 */

export type LonLat = readonly [lon: number, lat: number];

/** Материковая часть края, по часовой стрелке от Саян. */
export const KRAI_OUTLINE: readonly LonLat[] = [
  [92.3, 52.3],
  [93.2, 51.8],
  [94.3, 52.2],
  [95.6, 52.6],
  [96.5, 53.3],
  [97.4, 54.0],
  [98.1, 54.9],
  [97.6, 55.6],
  [98.5, 56.4],
  [100.0, 57.3],
  [101.5, 58.2],
  [102.2, 59.4],
  [103.6, 60.0],
  [105.6, 60.4],
  [106.4, 61.2],
  [107.5, 62.0],
  [108.6, 62.8],
  [108.5, 64.0],
  [107.7, 65.3],
  [109.2, 66.3],
  [111.6, 66.9],
  [112.8, 68.3],
  [112.3, 69.8],
  [113.2, 71.2],
  [113.8, 72.5],
  [112.0, 73.9],
  [110.2, 74.0],
  [108.0, 73.4],
  [106.5, 73.7],
  [107.5, 74.9],
  [105.0, 75.9],
  [104.3, 77.7],
  [101.5, 77.0],
  [98.0, 76.3],
  [95.0, 76.1],
  [92.0, 75.8],
  [89.0, 75.4],
  [87.0, 74.9],
  [86.0, 74.3],
  [86.8, 73.8],
  [82.0, 73.6],
  [80.4, 73.4],
  [80.6, 72.6],
  [82.3, 71.9],
  [83.2, 70.6],
  [83.4, 69.5],
  [83.0, 68.0],
  [83.6, 66.8],
  [84.5, 65.3],
  [85.2, 63.8],
  [85.0, 62.5],
  [84.6, 61.4],
  [85.6, 60.2],
  [87.0, 59.3],
  [88.6, 58.6],
  [89.3, 57.6],
  [88.6, 56.8],
  [89.2, 56.0],
  [89.8, 55.4],
  [89.3, 54.8],
  [90.4, 54.6],
  [91.4, 53.9],
  [91.5, 53.2],
  [91.0, 52.7],
];

/** Северная Земля. */
export const SEVERNAYA_ZEMLYA: readonly LonLat[] = [
  [95.0, 79.0],
  [97.5, 78.3],
  [100.5, 78.6],
  [104.5, 79.4],
  [101.5, 80.5],
  [97.0, 81.1],
  [93.5, 80.3],
];

/** Енисей с юга на север. */
export const YENISEI: readonly LonLat[] = [
  [91.6, 52.9],
  [91.7, 53.6],
  [91.3, 54.4],
  [91.5, 55.2],
  [92.4, 55.95],
  [92.87, 56.01],
  [93.3, 56.5],
  [92.9, 57.3],
  [92.5, 58.2],
  [92.2, 58.5],
  [92.3, 59.3],
  [91.6, 60.2],
  [90.3, 61.3],
  [89.5, 62.4],
  [88.3, 63.6],
  [87.9, 64.8],
  [87.98, 65.79],
  [86.8, 66.6],
  [86.58, 67.47],
  [86.4, 68.4],
  [86.18, 69.4],
  [85.0, 70.2],
  [83.4, 71.0],
  [82.0, 71.8],
  [81.0, 72.6],
];

/** Крупные притоки: Ангара, Подкаменная и Нижняя Тунгуска (с востока на запад). */
export const TRIBUTARIES: readonly (readonly LonLat[])[] = [
  [
    [101.6, 58.1],
    [99.2, 58.55],
    [97.45, 58.38],
    [95.6, 58.45],
    [94.0, 58.3],
    [92.4, 58.15],
  ],
  [
    [102.6, 60.3],
    [100.4, 60.7],
    [98.2, 61.1],
    [96.37, 61.67],
    [94.5, 61.55],
    [92.3, 61.5],
    [90.2, 61.6],
  ],
  [
    [106.4, 61.6],
    [104.6, 62.6],
    [102.8, 63.6],
    [100.22, 64.27],
    [97.8, 64.6],
    [95.2, 64.9],
    [92.6, 65.3],
    [90.3, 65.7],
    [88.1, 65.8],
  ],
];

export interface KraiCity {
  name: string;
  lon: number;
  lat: number;
  /** Крупный город — точка ярче и больше */
  major: boolean;
}

/** Города и посёлки края (реальные координаты, округлённо). */
export const KRAI_CITIES: readonly KraiCity[] = [
  { name: 'Красноярск', lon: 92.87, lat: 56.01, major: true },
  { name: 'Норильск', lon: 88.2, lat: 69.35, major: true },
  { name: 'Ачинск', lon: 90.5, lat: 56.27, major: true },
  { name: 'Канск', lon: 95.7, lat: 56.2, major: true },
  { name: 'Минусинск', lon: 91.69, lat: 53.71, major: true },
  { name: 'Лесосибирск', lon: 92.48, lat: 58.23, major: false },
  { name: 'Енисейск', lon: 92.17, lat: 58.45, major: false },
  { name: 'Дудинка', lon: 86.18, lat: 69.4, major: false },
  { name: 'Железногорск', lon: 93.53, lat: 56.25, major: false },
  { name: 'Зеленогорск', lon: 94.59, lat: 56.11, major: false },
  { name: 'Шарыпово', lon: 89.18, lat: 55.54, major: false },
  { name: 'Назарово', lon: 90.4, lat: 56.0, major: false },
  { name: 'Дивногорск', lon: 92.38, lat: 55.96, major: false },
  { name: 'Кодинск', lon: 99.18, lat: 58.6, major: false },
  { name: 'Богучаны', lon: 97.45, lat: 58.38, major: false },
  { name: 'Туруханск', lon: 87.98, lat: 65.79, major: false },
  { name: 'Игарка', lon: 86.58, lat: 67.47, major: false },
  { name: 'Тура', lon: 100.22, lat: 64.27, major: false },
  { name: 'Ванавара', lon: 102.28, lat: 60.34, major: false },
  { name: 'Байкит', lon: 96.37, lat: 61.67, major: false },
  { name: 'Хатанга', lon: 102.47, lat: 71.98, major: false },
  { name: 'Диксон', lon: 80.55, lat: 73.51, major: false },
  { name: 'Северо-Енисейский', lon: 93.04, lat: 60.37, major: false },
];

// Равноугольная коническая проекция Ламберта — как на привычных картах России.
const RAD = Math.PI / 180;
const LON0 = 96 * RAD;
const LAT1 = 52 * RAD;
const LAT2 = 74 * RAD;
const LAT0 = 64 * RAD;
const tanHalf = (phi: number): number => Math.tan(Math.PI / 4 + phi / 2);
const N = Math.log(Math.cos(LAT1) / Math.cos(LAT2)) / Math.log(tanHalf(LAT2) / tanHalf(LAT1));
const F = (Math.cos(LAT1) * Math.pow(tanHalf(LAT1), N)) / N;
const RHO0 = F / Math.pow(tanHalf(LAT0), N);

/** Долгота и широта → плоские координаты (ось y вниз), единица ≈ градус широты. */
export function project([lon, lat]: LonLat): [number, number] {
  const rho = F / Math.pow(tanHalf(lat * RAD), N);
  const theta = N * (lon * RAD - LON0);
  const x = rho * Math.sin(theta);
  const y = RHO0 - rho * Math.cos(theta);
  return [x / RAD, -y / RAD];
}

/** Попадает ли точка в многоугольник (луч вправо). */
export function insidePolygon(
  x: number,
  y: number,
  polygon: readonly (readonly [number, number])[],
): boolean {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i, i += 1) {
    const a = polygon[i];
    const b = polygon[j];
    if (!a || !b) continue;
    const [xi, yi] = a;
    const [xj, yj] = b;
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

/** Детерминированный генератор псевдослучайных чисел. */
export function seededRandom(seed: number): () => number {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
