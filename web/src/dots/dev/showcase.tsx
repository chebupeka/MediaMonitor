/**
 * Витрина форм точек — только для разработки, в сборку не входит.
 * Открыть: `npm run dev` → http://127.0.0.1:<порт>/src/dots/dev/index.html
 *
 * Параметры адреса:
 *   (без параметров)       все формы сайта в блоках размера панели + блок перелётов
 *   ?shape=krai            одна форма; w, h — размер блока в px или `full` (во всё окно)
 *   &place=right           форма справа/слева, как в разделах сайта
 *   &n=20000               точное число точек (по умолчанию — бюджет по размеру)
 *   &intensity=calm|full   &theme=light   &still=1 (как «уменьшить движение»)
 *   ?cycle=krai,listening  одна область, формы меняются каждые `every` мс (по умолчанию 2600)
 *   &found=Красноярск:6,Норильск:4   данные для found
 */
import { StrictMode, useCallback, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import '@/styles/tokens.css';
import '@/styles/base.css';
import type { DotsEngine } from '../engine/engine';
import { SHAPE_IDS, dataCount, type ShapeId, type ShapeRequest } from '../engine/shapes';
import { ParticleField } from '../ParticleField';
import type { DotsCityCount } from '../types';
import styles from './showcase.module.css';

const params = new URLSearchParams(window.location.search);

/** Найденное по городам — демо-набор сайта (FOUND в particles.js). */
const SITE_FOUND: DotsCityCount[] = [
  { city: 'Красноярск', count: 6 },
  { city: 'Норильск', count: 4 },
  { city: 'Канск', count: 2 },
  { city: 'Ачинск', count: 1 },
  { city: 'Минусинск', count: 1 },
  { city: 'Лесосибирск', count: 1 },
];

function foundData(): DotsCityCount[] {
  const raw = params.get('found');
  if (!raw) return SITE_FOUND;
  return raw.split(',').map((pair) => {
    const [city = '', count = '0'] = pair.split(':');
    return { city, count: Number(count) };
  });
}

function request(id: ShapeId): ShapeRequest {
  if (id === 'found') return { id, data: { cities: foundData() } };
  return { id };
}

function isShape(v: string | null): v is ShapeId {
  return v !== null && (SHAPE_IDS as string[]).includes(v);
}

function size(v: string | null, fallback: number): number | string {
  if (v === 'full') return '100vh';
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

interface CellProps {
  shape: ShapeRequest;
  width: number | string;
  height: number | string;
  label?: string;
}

function Cell({ shape, width, height, label }: CellProps) {
  const [engine, setEngine] = useState<DotsEngine | null>(null);
  const [fps, setFps] = useState(0);
  const [failed, setFailed] = useState(false);
  const onUnsupported = useCallback(() => setFailed(true), []);
  useEffect(() => {
    if (!engine) return;
    // Для проверки из консоли и автоматических снимков: window.__dots — живые движки
    const list = ((window as unknown as { __dots?: DotsEngine[] }).__dots ??= []);
    list.push(engine);
    const t = window.setInterval(() => setFps(engine.fps), 1000);
    return () => {
      window.clearInterval(t);
      list.splice(list.indexOf(engine), 1);
    };
  }, [engine]);
  const n = Number(params.get('n'));
  const intensity = params.get('intensity') === 'full' ? 'full' : 'calm';
  const place = params.get('place');
  const data = dataCount(shape);
  return (
    <figure className={styles.cell} style={{ width }}>
      {failed ? (
        <p className={styles.fail}>WebGL недоступен</p>
      ) : (
        <ParticleField
          shape={shape}
          intensity={intensity}
          height={height}
          still={params.get('still') === '1'}
          lightTheme={params.get('theme') === 'light'}
          onUnsupported={onUnsupported}
          onEngine={setEngine}
          place={place === 'left' || place === 'right' ? place : 'center'}
          count={Number.isFinite(n) && n > 0 ? n : undefined}
        />
      )}
      {label !== '' && (
        <figcaption className={styles.caption} data-testid="caption">
          <b>{label ?? shape.id}</b> · точек {engine?.count ?? '…'}
          {data > 0 && <> · данных {data}</>} · {fps} кадр/с
        </figcaption>
      )}
    </figure>
  );
}

/** Одна область, формы сменяются по кругу — проверка перелётов. */
function Cycle({ ids, every }: { ids: ShapeId[]; every: number }) {
  const [i, setI] = useState(0);
  useEffect(() => {
    const t = window.setInterval(() => setI((k) => (k + 1) % ids.length), every);
    return () => window.clearInterval(t);
  }, [ids.length, every]);
  const id = ids[i] ?? 'krai';
  return (
    <Cell
      shape={request(id)}
      width={size(params.get('w'), 380)}
      height={size(params.get('h'), 200)}
      label={`перелёты: ${id}`}
    />
  );
}

/** Ручной перелёт: кнопки форм. */
function Morph() {
  const [id, setId] = useState<ShapeId>('krai');
  return (
    <section className={styles.morph}>
      <Cell shape={request(id)} width={760} height={320} label={`перелёт → ${id}`} />
      <div className={styles.buttons}>
        {SHAPE_IDS.map((s) => (
          <button
            key={s}
            type="button"
            className={styles.button}
            aria-pressed={s === id}
            onClick={() => setId(s)}
          >
            {s}
          </button>
        ))}
      </div>
    </section>
  );
}

function Showcase() {
  const one = params.get('shape');
  const cycle = params.get('cycle');
  if (params.get('theme') === 'light') document.documentElement.dataset.theme = 'light';
  if (isShape(one)) {
    const full = params.get('w') === 'full';
    return (
      <main className={full ? styles.full : styles.single}>
        <Cell
          shape={request(one)}
          width={full ? '100vw' : size(params.get('w'), 380)}
          height={size(params.get('h'), 200)}
          label={full ? '' : undefined}
        />
      </main>
    );
  }
  if (cycle) {
    const ids = cycle.split(',').filter(isShape);
    return (
      <main className={styles.single}>
        <Cycle ids={ids.length > 0 ? ids : ['krai']} every={Number(params.get('every')) || 2600} />
      </main>
    );
  }
  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Точки: формы сайта «Медиарадар» в блоке панели</h1>
      <div className={styles.grid}>
        {SHAPE_IDS.map((id) => (
          <Cell key={id} shape={request(id)} width={380} height={200} />
        ))}
      </div>
      <Morph />
    </main>
  );
}

const root = document.getElementById('root');
if (root)
  createRoot(root).render(
    <StrictMode>
      <Showcase />
    </StrictMode>,
  );
