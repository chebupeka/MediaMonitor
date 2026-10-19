/**
 * Холст точек на WebGL: формы словаря (08-visual-concept.md) в стиле сайта «Стрежень».
 * Декоративный (aria-hidden): факты экран дублирует текстом. Скрытый экран и вкладка
 * на паузе; при «уменьшить движение» — статичная форма без анимации.
 */
import { useEffect, useRef, useState } from 'react';
import { buildForm, formKey, type FormInput } from './particles/forms';
import { ParticleScene, type SceneLook } from './particles/renderer';
import type { DotsForm, DotsSceneProps } from './types';
import styles from './ParticleCanvas.module.css';

/** Бюджет точек (08): спокойная версия в панели — меньше, лендинг — больше. */
const COUNT = { calm: 3200, full: 9000 } as const;

/** Масштаб и покачивание для каждой формы. */
const LOOKS: Record<DotsForm, Omit<SceneLook, 'light'>> = {
  krai: { scale: 1, angle: 0, sway: 0.3 },
  listening: { scale: 0.9, angle: 0.1, sway: 0.2 },
  searching: { scale: 0.9, angle: -0.12, sway: 0.14 },
  failure: { scale: 0.9, angle: 0.12, sway: 0.14 },
  found: { scale: 1, angle: 0.1, sway: 0.22 },
  spread: { scale: 0.85, angle: 0.35, sway: 0.28 },
  empty: { scale: 1, angle: 0, sway: 0.05 },
  export: { scale: 0.9, angle: -0.38, sway: 0.16 },
};

interface ParticleCanvasProps extends DotsSceneProps {
  still: boolean;
  light: boolean;
  /** Нет WebGL — пусть родитель покажет статичную карту */
  onUnsupported: () => void;
}

export function ParticleCanvas({
  form,
  intensity = 'full',
  cities = [],
  platforms = {},
  placements = [],
  height = 220,
  className,
  still,
  light,
  onUnsupported,
}: ParticleCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const sceneRef = useRef<ParticleScene | null>(null);
  const [ready, setReady] = useState(0);
  const count = COUNT[intensity];

  // Сцена живёт, пока не сменились бюджет точек или режим движения
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const scene = ParticleScene.create(canvas, { count, still });
    if (!scene) {
      onUnsupported();
      return;
    }
    sceneRef.current = scene;
    setReady((n) => n + 1);

    let onScreen = true;
    const update = () => scene.setVisible(onScreen && !document.hidden);
    const io = new IntersectionObserver(([entry]) => {
      onScreen = entry?.isIntersecting ?? true;
      update();
    });
    io.observe(canvas);
    const ro = new ResizeObserver(() => scene.redraw());
    ro.observe(canvas);
    document.addEventListener('visibilitychange', update);
    return () => {
      io.disconnect();
      ro.disconnect();
      document.removeEventListener('visibilitychange', update);
      scene.destroy();
      sceneRef.current = null;
    };
  }, [count, still, onUnsupported]);

  const input: FormInput = { form, cities, platforms, placements };
  const key = formKey(input);
  const inputRef = useRef(input);
  inputRef.current = input;

  // Новая форма — точки перелетают в неё
  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene) return;
    scene.setForm(key, () => buildForm(inputRef.current, count), { ...LOOKS[form], light });
  }, [key, form, light, count, ready]);

  return (
    <canvas
      ref={canvasRef}
      className={[styles.canvas, className].filter(Boolean).join(' ')}
      style={{ height }}
      aria-hidden="true"
    />
  );
}
