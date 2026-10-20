/**
 * «Расшифровка» — как на сайте (site/ui.js): строка проявляется слева направо, на переднем
 * крае несколько знаков мелькают случайными символами, ещё не проявленная часть прозрачна
 * и держит место. Только для заголовков и подписей разделов — данные не анимируем.
 *
 * Скринридер и выделение видят обычный текст: анимированная копия скрыта (aria-hidden),
 * рядом — тот же текст для скринридера; по окончании остаётся обычный текст. Без анимаций
 * («уменьшить движение», режим для слабовидящих) — сразу обычный текст.
 */
import { useLayoutEffect, useRef, useState } from 'react';
import { motionAllowed } from '@/lib/motion';
import styles from './Scramble.module.css';

const UP = 'АБВГДЕЖЗИКЛМНОПРСТУФХЦЧШЭЮЯ0123456789#%&*+=/<>';
const LO = 'абвгдежзиклмнопрстуфхцчшэюя0123456789#%&*+=/<>';

interface Run {
  a: HTMLSpanElement;
  b: HTMLSpanElement;
  c: HTMLSpanElement;
  text: string;
  t0: number;
  dur: number;
  front: number;
  ia: number;
  ib: number;
  mixing: boolean;
  done: () => void;
}

// Один кадр на все расшифровки, как на сайте
const running = new Set<Run>();
let raf = 0;
let last = 0;

/** Меняет в DOM только то, что изменилось (site/ui.js, render). */
function render(r: Run, n: number): void {
  const L = r.text.length;
  const ia = Math.max(0, Math.min(L, n));
  const ib = Math.max(0, Math.min(L, n + r.front));
  if (ia !== r.ia) {
    r.a.textContent = r.text.slice(0, ia);
    r.ia = ia;
  }
  if (ib !== r.ib) {
    r.c.textContent = r.text.slice(ib);
    r.ib = ib;
  }
  if (ib > ia || r.mixing) {
    let s = '';
    for (let i = ia; i < ib; i += 1) {
      const ch = r.text.charAt(i);
      if (ch === ' ') {
        s += ' ';
        continue;
      }
      const set = ch === ch.toLowerCase() && ch !== ch.toUpperCase() ? LO : UP;
      s += set.charAt(Math.floor(Math.random() * set.length));
    }
    r.b.textContent = s;
    r.mixing = ib > ia;
  }
}

function step(now: number): void {
  raf = 0;
  const tick = now - last > 40; // случайные знаки меняются ~25 раз в секунду
  if (tick) last = now;
  for (const r of running) {
    if (now < r.t0) continue;
    const p = (now - r.t0) / r.dur;
    if (p >= 1) {
      running.delete(r);
      r.done();
      continue;
    }
    if (tick) render(r, Math.floor(p * r.text.length));
  }
  if (running.size > 0) raf = requestAnimationFrame(step);
}

export interface ScrambleTextProps {
  text: string;
  /** Задержка, мс (на сайте у слов заголовка — 0, 150, 300) */
  delay?: number;
  /** Длительность, мс; по умолчанию — по длине строки, как на сайте */
  dur?: number;
  /** Сколько знаков мелькает на переднем крае */
  front?: number;
  /** Начать, когда строка покажется на экране (заголовки разделов ниже первого экрана) */
  onView?: boolean;
}

export function ScrambleText({
  text,
  delay = 0,
  dur,
  front = 5,
  onView = false,
}: ScrambleTextProps) {
  const [done, setDone] = useState(() => !motionAllowed());
  const wrapRef = useRef<HTMLSpanElement>(null);
  const aRef = useRef<HTMLSpanElement>(null);
  const bRef = useRef<HTMLSpanElement>(null);
  const cRef = useRef<HTMLSpanElement>(null);

  // До первой отрисовки: строка прозрачна и держит место
  useLayoutEffect(() => {
    if (done) return;
    const a = aRef.current;
    const b = bRef.current;
    const c = cRef.current;
    const wrap = wrapRef.current;
    if (!a || !b || !c || !wrap) return;
    a.textContent = '';
    b.textContent = '';
    c.textContent = text;
    const run: Run = {
      a,
      b,
      c,
      text,
      t0: Infinity,
      dur: dur ?? Math.max(450, Math.min(1900, text.length * 24)),
      front,
      ia: 0,
      ib: 0,
      mixing: false,
      done: () => setDone(true),
    };
    const begin = () => {
      run.t0 = performance.now() + delay;
      running.add(run);
      if (!raf) raf = requestAnimationFrame(step);
    };
    let io: IntersectionObserver | null = null;
    if (onView && typeof IntersectionObserver !== 'undefined') {
      io = new IntersectionObserver(
        ([entry]) => {
          if (!entry?.isIntersecting) return;
          io?.disconnect();
          begin();
        },
        { rootMargin: '0px 0px -8% 0px', threshold: 0.15 },
      );
      io.observe(wrap);
    } else begin();
    return () => {
      io?.disconnect();
      running.delete(run);
    };
  }, [done, text, delay, dur, front, onView]);

  if (done) return <>{text}</>;
  return (
    <span ref={wrapRef}>
      <span className="sr-only">{text}</span>
      <span aria-hidden="true">
        <span ref={aRef} />
        <span ref={bRef} className={styles.b} />
        <span ref={cRef} className={styles.c} />
      </span>
    </span>
  );
}
