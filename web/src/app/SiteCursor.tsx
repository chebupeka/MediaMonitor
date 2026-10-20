/**
 * Свой курсор сайта «Медиарадар» (site/ui.js): точка следует за мышью сразу, кольцо догоняет;
 * над ссылками и кнопками кольцо растёт и становится золотым.
 *
 * Только во вкладке (широкая раскладка) и только с мышью; не в боковой панели — там
 * курсор системный. Без анимаций («уменьшить движение», режим для слабовидящих) — системный
 * курсор. Над полями ввода — системный курсор-«палочка»: так видно, куда встанет текст.
 * Кадр не читает раскладку: только запись transform.
 */
import { useEffect, useRef } from 'react';
import { motionAllowed } from '@/lib/motion';
import { useShell } from './shell-state';
import styles from './SiteCursor.module.css';

/** Над чем кольцо растёт: всё, что нажимается */
const HOT =
  'a, button, summary, select, label, [role="button"], [role="tab"], [role="menuitem"], [role="menuitemradio"], [role="menuitemcheckbox"], [role="option"], [role="radio"], [role="checkbox"], [role="switch"]';
/** Над полями ввода — системный курсор */
const TEXT =
  'textarea, input:not([type="checkbox"], [type="radio"], [type="button"], [type="submit"], [type="range"], [type="file"]), [contenteditable=""], [contenteditable="true"]';

function ease(k: number, dt: number): number {
  return 1 - Math.pow(1 - k, dt * 60);
}

export function SiteCursor() {
  const { lowVision } = useShell();
  const ringRef = useRef<HTMLDivElement>(null);
  const dotRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const ring = ringRef.current;
    const dot = dotRef.current;
    if (!ring || !dot) return;
    if (!motionAllowed() || !window.matchMedia?.('(pointer: fine)').matches) return;
    const root = document.documentElement;
    root.dataset.cursor = 'site';

    const cur = { x: -100, y: -100, rx: -100, ry: -100, moved: false };
    let raf = 0;
    let last = performance.now();

    const frame = (now: number) => {
      raf = 0;
      const dt = Math.min(1, Math.max(0, (now - last) / 1000));
      last = now;
      if (cur.moved) {
        cur.moved = false;
        dot.style.transform = `translate(${cur.x}px, ${cur.y}px)`;
      }
      const dx = cur.x - cur.rx;
      const dy = cur.y - cur.ry;
      if (dx * dx + dy * dy > 0.01) {
        cur.rx += dx * ease(0.16, dt);
        cur.ry += dy * ease(0.16, dt);
        ring.style.transform = `translate(${cur.rx.toFixed(1)}px, ${cur.ry.toFixed(1)}px)`;
        raf = requestAnimationFrame(frame); // кольцо ещё догоняет
      }
    };
    const kick = () => {
      if (!raf) {
        last = performance.now();
        raf = requestAnimationFrame(frame);
      }
    };
    const onMove = (e: PointerEvent) => {
      if (e.pointerType !== 'mouse') return;
      cur.x = e.clientX;
      cur.y = e.clientY;
      cur.moved = true;
      kick();
    };
    const onOver = (e: PointerEvent) => {
      const t = e.target instanceof Element ? e.target : null;
      const text = !!t?.closest(TEXT);
      ring.classList.toggle(styles.big ?? 'big', !text && !!t?.closest(HOT));
      root.toggleAttribute('data-cursor-text', text);
    };
    const onLeave = () => {
      cur.x = -100;
      cur.y = -100;
      cur.moved = true;
      kick();
    };
    window.addEventListener('pointermove', onMove, { passive: true });
    document.addEventListener('pointerover', onOver, { passive: true });
    document.documentElement.addEventListener('pointerleave', onLeave);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('pointermove', onMove);
      document.removeEventListener('pointerover', onOver);
      document.documentElement.removeEventListener('pointerleave', onLeave);
      delete root.dataset.cursor;
      root.removeAttribute('data-cursor-text');
    };
  }, [lowVision]);

  return (
    <>
      <div ref={ringRef} className={styles.ring} aria-hidden="true" />
      <div ref={dotRef} className={styles.dot} aria-hidden="true" />
    </>
  );
}
