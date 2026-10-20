/**
 * Холст точек — React-обёртка движка сайта (`engine/`). Декоративный (aria-hidden):
 * факты экран дублирует текстом.
 *
 * - Холст создаётся заново при каждом монтировании: в StrictMode (`npm run dev`) эффект
 *   срабатывает дважды, и прежний холст уходит вместе с отпущенным контекстом — новый
 *   получает свежий WebGL (дефект ветки: второй запуск получал потерянный контекст).
 * - Бюджет точек — по высоте блока: сайт рисует 20 000 точек на экран (9 000 на слабых
 *   устройствах), блок получает долю по своей высоте; спокойная версия — не больше 4 000.
 * - Скрытый экран, вкладка в фоне или блок вне экрана — кадры не рисуются.
 * - Размер блока движок получает из ResizeObserver, а не читает в кадре.
 * - «Система слушает»: поток течёт к полю ввода — `flowTarget` (CSS-селектор) или, если он
 *   не задан, первое текстовое поле после блока точек (на экране поиска — поле запроса).
 *   Если между облаком и полем поверх холста лежит текст, он помечается `data-flow-cover`:
 *   над ним поток невидим и проявляется у самого поля (как на сайте на узком экране).
 */
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { DotsEngine, SITE_N, SITE_STARS, isLowPower } from './engine/engine';
import { shapeKey, type ShapeRequest } from './engine/shapes';
import styles from './ParticleField.module.css';

/** Спокойная версия в панели (10-frontend-design-proposals §3.4): до 4 000 точек. */
const CALM_CAP = 4000;
/** Меньше — форма рассыпается на отдельные точки. */
const MIN_COUNT = 1500;
/** Высота экрана, на которую рассчитан бюджет сайта. */
const SITE_H = 1080;

/** Текстовые поля, к которым может течь поток «система слушает». */
const FIELDS = 'textarea, input[type="text"], input[type="search"], input:not([type])';

/** Поле ввода для потока: по селектору или первое текстовое поле после блока точек. */
function findFlowTarget(host: HTMLElement | null, selector?: string): Element | null {
  if (!host) return null;
  if (selector) return document.querySelector(selector);
  for (const el of document.querySelectorAll(FIELDS))
    if (host.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) return el;
  return null;
}

/** Поток к полю (или без поля) и текст над полем (`data-flow-cover`), сквозь который он не идёт. */
function setFlow(engine: DotsEngine, host: HTMLElement | null, on: boolean, selector?: string) {
  const field = on ? findFlowTarget(host, selector) : null;
  engine.setTarget(field, field ? document.querySelector('[data-flow-cover]') : null);
}

export function budgetFor(
  w: number,
  h: number,
  intensity: 'full' | 'calm',
  lowPower: boolean,
): number {
  const base = lowPower ? SITE_N.low : SITE_N.normal;
  // Форма вписывается в блок по высоте (а в узком блоке — по ширине)
  const size = Math.min(h, w);
  const raw = (base * size) / SITE_H;
  const cap = intensity === 'calm' ? CALM_CAP : base;
  return Math.max(MIN_COUNT, Math.min(cap, Math.round(raw / 250) * 250));
}

function starsFor(w: number, h: number, intensity: 'full' | 'calm', lowPower: boolean): number {
  if (intensity === 'calm') return 0; // в рабочей панели фон и так со звёздами — не отвлекаем
  const base = lowPower ? SITE_STARS.low : SITE_STARS.normal;
  return Math.round((base * w * h) / (1920 * SITE_H));
}

export interface ParticleFieldProps {
  shape: ShapeRequest;
  intensity: 'full' | 'calm';
  height: number | string;
  className?: string;
  /** «Уменьшить движение»: статичная форма */
  still: boolean;
  lightTheme: boolean;
  /** Нет WebGL — пусть родитель покажет статичную карту */
  onUnsupported: () => void;
  /** Для витрины: доступ к движку (FPS) */
  onEngine?: (engine: DotsEngine | null) => void;
  /** Для витрины: форма слева или справа, как в разделах сайта (по умолчанию — по центру) */
  place?: 'center' | 'left' | 'right';
  /** Для витрины: точное число точек вместо бюджета по размеру */
  count?: number;
  /**
   * «Система слушает»: CSS-селектор поля ввода, к которому течёт поток. Не задан — первое
   * текстовое поле после блока точек.
   */
  flowTarget?: string;
}

export function ParticleField({
  shape,
  intensity,
  height,
  className,
  still,
  lightTheme,
  onUnsupported,
  onEngine,
  place = 'center',
  count: fixedCount,
  flowTarget,
}: ParticleFieldProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const engineRef = useRef<DotsEngine | null>(null);
  const shapeRef = useRef(shape);
  shapeRef.current = shape;
  const themeRef = useRef(lightTheme);
  themeRef.current = lightTheme;
  const onEngineRef = useRef(onEngine);
  onEngineRef.current = onEngine;
  const flowTargetRef = useRef(flowTarget);
  flowTargetRef.current = flowTarget;
  const [mountedAt] = useState(() => performance.now());
  const [lowPower] = useState(isLowPower);
  const [budget, setBudget] = useState<{ count: number; stars: number } | null>(null);

  // Бюджет — по размеру блока; заметно изменился размер — движок пересоздаётся
  useLayoutEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const measure = () => {
      const w = host.clientWidth;
      const h = host.clientHeight;
      if (w === 0 || h === 0) return; // скрытый экран — бюджет посчитаем, когда покажут
      const count = fixedCount ?? budgetFor(w, h, intensity, lowPower);
      const stars = starsFor(w, h, intensity, lowPower);
      setBudget((prev) =>
        prev && Math.abs(count - prev.count) / prev.count < 0.35 && stars === prev.stars
          ? prev
          : { count, stars },
      );
    };
    measure();
    const ro = new ResizeObserver(() => {
      measure();
      // размер — движку, чтобы кадр не читал раскладку
      engineRef.current?.setSize(host.clientWidth, host.clientHeight);
      engineRef.current?.redraw();
    });
    ro.observe(host);
    return () => ro.disconnect();
  }, [intensity, lowPower, fixedCount]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host || !budget) return;
    const canvas = document.createElement('canvas');
    canvas.className = styles.canvas ?? '';
    canvas.setAttribute('aria-hidden', 'true');
    host.appendChild(canvas);
    const engine = DotsEngine.create(canvas, {
      count: budget.count,
      stars: budget.stars,
      still,
      lowPower,
      place,
      // Вступление сайта — только при первом показе, не при пересоздании из-за размера
      intro: performance.now() - mountedAt < 600,
    });
    if (!engine) {
      canvas.remove();
      onUnsupported();
      return;
    }
    engineRef.current = engine;
    engine.setSize(host.clientWidth, host.clientHeight);
    engine.setTheme(themeRef.current);
    engine.setShape(shapeRef.current);
    setFlow(engine, host, shapeRef.current.id === 'listening', flowTargetRef.current);
    onEngineRef.current?.(engine);

    let onScreen = true;
    const update = () => engine.setVisible(onScreen && !document.hidden);
    const io = new IntersectionObserver(([entry]) => {
      onScreen = entry?.isIntersecting ?? true;
      update();
    });
    io.observe(host);
    document.addEventListener('visibilitychange', update);
    return () => {
      io.disconnect();
      document.removeEventListener('visibilitychange', update);
      onEngineRef.current?.(null);
      engine.destroy();
      canvas.remove();
      engineRef.current = null;
    };
  }, [budget, still, lowPower, place, mountedAt, onUnsupported]);

  // Новая форма — точки перелетают в неё
  const key = shapeKey(shape);
  useEffect(() => {
    engineRef.current?.setShape(shapeRef.current);
  }, [key]);

  // «Система слушает» — поток к полю ввода; у остальных форм поля нет
  const listening = shape.id === 'listening';
  useEffect(() => {
    const engine = engineRef.current;
    if (engine) setFlow(engine, hostRef.current, listening, flowTargetRef.current);
  }, [listening, flowTarget]);

  useEffect(() => {
    engineRef.current?.setTheme(lightTheme);
  }, [lightTheme]);

  return (
    <div
      ref={hostRef}
      className={[styles.field, className].filter(Boolean).join(' ')}
      style={{ height }}
      aria-hidden="true"
    />
  );
}
