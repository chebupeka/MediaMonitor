/**
 * СЛОТ «ТОЧКИ». Экраны используют только этот компонент.
 *
 * Точки на WebGL — движок сайта «Медиарадар» (`site/particles.js`), перенесённый один в один
 * (`engine/`): формы словаря из 08-visual-concept.md, перелёт между формами с разлётом
 * по пути, объём, наклон и поворот за мышью, отталкивание от курсора, мерцание.
 * Форму задаёт свойство `form` (на сайте — прокрутка): при его смене точки перелетают
 * так же, как на сайте при прокрутке к следующему разделу.
 * Запасной вариант — статичная карта (StaticKraiMap): без WebGL и при выключенном
 * переключателе «Анимация точек». При «уменьшить движение» форма статична.
 */
import { useCallback, useState } from 'react';
import { useShell } from '@/app/shell-state';
import type { ShapeId, ShapeRequest } from './engine/shapes';
import { ParticleField } from './ParticleField';
import { StaticKraiMap } from './StaticKraiMap';
import type { DotsForm, DotsSceneProps } from './types';

/** Форма слота → форма сайта */
const SHAPE: Readonly<Record<DotsForm, ShapeId>> = {
  krai: 'krai',
  listening: 'listening',
  searching: 'searching',
  found: 'found',
  spread: 'spread',
  empty: 'empty',
  failure: 'failure',
  export: 'grid',
};

export function DotsScene(props: DotsSceneProps) {
  const { dotsEnabled, reducedMotion, resolvedTheme } = useShell();
  const [unsupported, setUnsupported] = useState(false);
  const onUnsupported = useCallback(() => setUnsupported(true), []);

  if (!dotsEnabled || unsupported) return <StaticKraiMap {...props} />;
  const {
    form,
    intensity = 'full',
    cities,
    platforms,
    placements,
    height = 220,
    className,
    flowTarget,
  } = props;
  const shape: ShapeRequest = { id: SHAPE[form], data: { cities, platforms, placements } };
  return (
    <ParticleField
      shape={shape}
      intensity={intensity}
      height={height}
      className={className}
      still={reducedMotion}
      lightTheme={resolvedTheme === 'light'}
      onUnsupported={onUnsupported}
      flowTarget={flowTarget}
    />
  );
}
