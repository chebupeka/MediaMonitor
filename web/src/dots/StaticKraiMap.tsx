/**
 * Статичная карта края из точек (SVG). Это запасной вариант и заготовка лендинга:
 * без WebGL, без анимации движения (только мягкое мерцание городов, если можно).
 * Холст декоративный (aria-hidden): факты экран дублирует текстом.
 */
import { memo, useMemo } from 'react';
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
} from './krai-geo';
import type { DotsSceneProps } from './types';
import styles from './StaticKraiMap.module.css';

const SCALE = 26;
const PAD = 1.2;
const STEP = 0.34;

interface Dot {
  x: number;
  y: number;
  r: number;
}

interface Geometry {
  width: number;
  height: number;
  land: Dot[];
  river: Dot[];
  tributaries: Dot[];
  stars: Dot[];
  cities: { name: string; x: number; y: number; major: boolean }[];
  toView: (lon: number, lat: number) => [number, number];
}

let cache: Geometry | null = null;

function geometry(): Geometry {
  if (cache) return cache;
  const outline = KRAI_OUTLINE.map(project);
  const islands = SEVERNAYA_ZEMLYA.map(project);
  const all = [...outline, ...islands];
  const xs = all.map((p) => p[0]);
  const ys = all.map((p) => p[1]);
  const minX = Math.min(...xs) - PAD;
  const maxX = Math.max(...xs) + PAD;
  const minY = Math.min(...ys) - PAD;
  const maxY = Math.max(...ys) + PAD;
  const toView = (x: number, y: number): [number, number] => [
    (x - minX) * SCALE,
    (y - minY) * SCALE,
  ];
  const rnd = seededRandom(56);

  const land: Dot[] = [];
  for (let y = minY; y <= maxY; y += STEP) {
    for (let x = minX; x <= maxX; x += STEP) {
      const jx = x + (rnd() - 0.5) * STEP * 0.55;
      const jy = y + (rnd() - 0.5) * STEP * 0.55;
      if (insidePolygon(jx, jy, outline) || insidePolygon(jx, jy, islands)) {
        const [vx, vy] = toView(jx, jy);
        land.push({ x: vx, y: vy, r: 1.3 + rnd() * 1.1 });
      }
    }
  }

  const sampleLine = (line: readonly LonLat[], spacing: number, radius: number): Dot[] => {
    const dots: Dot[] = [];
    for (let i = 1; i < line.length; i += 1) {
      const a = line[i - 1];
      const b = line[i];
      if (!a || !b) continue;
      const [ax, ay] = project(a);
      const [bx, by] = project(b);
      const len = Math.hypot(bx - ax, by - ay);
      const n = Math.max(1, Math.round(len / spacing));
      for (let k = 0; k < n; k += 1) {
        const t = k / n;
        const [vx, vy] = toView(
          ax + (bx - ax) * t + (rnd() - 0.5) * 0.05,
          ay + (by - ay) * t + (rnd() - 0.5) * 0.05,
        );
        dots.push({ x: vx, y: vy, r: radius + rnd() * 0.5 });
      }
    }
    return dots;
  };
  const river = sampleLine(YENISEI, 0.15, 1.6);
  const tributaries = TRIBUTARIES.flatMap((line) => sampleLine(line, 0.2, 1.1));

  const width = (maxX - minX) * SCALE;
  const height = (maxY - minY) * SCALE;
  const stars: Dot[] = [];
  for (let i = 0; i < 90; i += 1) {
    stars.push({ x: rnd() * width, y: rnd() * height, r: 0.5 + rnd() * 0.6 });
  }

  const cities = KRAI_CITIES.map((c) => {
    const [vx, vy] = toView(...project([c.lon, c.lat]));
    return { name: c.name, x: vx, y: vy, major: c.major };
  });

  cache = {
    width,
    height,
    land,
    river,
    tributaries,
    stars,
    cities,
    toView: (lon, lat) => toView(...project([lon, lat])),
  };
  return cache;
}

/** Облака и точки — только у VK, OK, MAX; у сайтов СМИ и Дзена цвета на карте нет. */
const PLATFORM_COLOR: Readonly<Partial<Record<PlatformId, string>>> = {
  vk: 'var(--color-vk)',
  ok: 'var(--color-ok)',
  max: 'var(--color-max)',
};

/** Точки вокруг города: ровно `count` штук (правило честности). */
function cluster(x: number, y: number, count: number, seed: number): Dot[] {
  const rnd = seededRandom(seed);
  const dots: Dot[] = [];
  for (let i = 0; i < count; i += 1) {
    const angle = i * 2.399963; // золотой угол
    const radius = 3 + Math.sqrt(i) * 3.2 + rnd();
    dots.push({ x: x + Math.cos(angle) * radius, y: y + Math.sin(angle) * radius, r: 2.1 });
  }
  return dots;
}

export const StaticKraiMap = memo(function StaticKraiMap({
  form,
  intensity = 'full',
  cities,
  platforms,
  sourceCity,
  height,
  className,
}: DotsSceneProps) {
  const geo = geometry();
  const dim = form === 'empty' ? 0.35 : form === 'krai' || form === 'listening' ? 1 : 0.6;

  const dataDots = useMemo(() => {
    if (!cities || (form !== 'found' && form !== 'spread')) return [];
    return cities.flatMap((c, idx) => {
      const city = geo.cities.find((g) => g.name === c.city);
      if (!city) return [];
      return cluster(city.x, city.y, c.count, idx + 7).map((d) => ({ ...d, platform: c.platform }));
    });
  }, [cities, form, geo]);

  const source = sourceCity ? geo.cities.find((c) => c.name === sourceCity) : undefined;
  const labels = geo.cities.filter((c) => c.name === 'Красноярск' || c.name === 'Норильск');
  const clouds: PlatformId[] = ['vk', 'ok', 'max'];

  return (
    <svg
      className={[styles.map, intensity === 'calm' ? styles.calm : '', className ?? ''].join(' ')}
      viewBox={`0 0 ${geo.width.toFixed(0)} ${geo.height.toFixed(0)}`}
      preserveAspectRatio="xMidYMid meet"
      style={height !== undefined ? { height } : undefined}
      aria-hidden="true"
      focusable="false"
    >
      <g className={styles.stars}>
        {geo.stars.map((s, i) => (
          <circle key={i} cx={s.x} cy={s.y} r={s.r} />
        ))}
      </g>
      <g className={styles.land} style={{ opacity: dim }}>
        {geo.land.map((d, i) => (
          <circle key={i} cx={d.x} cy={d.y} r={d.r} />
        ))}
      </g>
      <g className={styles.tributaries} style={{ opacity: dim }}>
        {geo.tributaries.map((d, i) => (
          <circle key={i} cx={d.x} cy={d.y} r={d.r} />
        ))}
      </g>
      <g className={styles.river} style={{ opacity: dim }}>
        {geo.river.map((d, i) => (
          <circle key={i} cx={d.x} cy={d.y} r={d.r} />
        ))}
      </g>
      <g className={styles.cities} style={{ opacity: form === 'empty' ? 0.3 : 1 }}>
        {geo.cities.map((c, i) => (
          <g key={c.name} className={styles.city} style={{ animationDelay: `${(i % 7) * 0.45}s` }}>
            <circle cx={c.x} cy={c.y} r={c.major ? 9 : 5.5} className={styles.glow} />
            <circle cx={c.x} cy={c.y} r={c.major ? 3.6 : 2.4} className={styles.core} />
          </g>
        ))}
      </g>
      {intensity === 'full' && form === 'krai' && (
        <g className={styles.labels}>
          {labels.map((c) => (
            <text key={c.name} x={c.x + 12} y={c.y + 4}>
              {c.name}
            </text>
          ))}
        </g>
      )}
      {dataDots.length > 0 && (
        <g className={styles.data}>
          {dataDots.map((d, i) => (
            <circle
              key={i}
              cx={d.x}
              cy={d.y}
              r={d.r}
              style={{ fill: d.platform ? PLATFORM_COLOR[d.platform] : undefined }}
            />
          ))}
        </g>
      )}
      {form === 'spread' && source && (
        <g className={styles.source}>
          <circle cx={source.x} cy={source.y} r={16} />
          <circle cx={source.x} cy={source.y} r={30} />
        </g>
      )}
      {(form === 'searching' || form === 'failure') && (
        <g className={styles.clouds}>
          {clouds.map((p, idx) => {
            const state = platforms?.[p] ?? 'active';
            const cx = geo.width * (0.22 + idx * 0.28);
            const cy = geo.height * 0.06;
            return (
              <g key={p} className={state === 'failed' ? styles.failed : undefined}>
                {cluster(cx, cy, 18, idx + 3).map((d, i) => (
                  <circle
                    key={i}
                    cx={d.x}
                    cy={d.y}
                    r={1.8}
                    style={{ fill: state === 'failed' ? undefined : PLATFORM_COLOR[p] }}
                  />
                ))}
              </g>
            );
          })}
        </g>
      )}
    </svg>
  );
});
