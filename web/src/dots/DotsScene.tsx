/**
 * СЛОТ «ТОЧКИ». Экраны используют только этот компонент.
 *
 * Точки на WebGL в стиле сайта «Стрежень» (ParticleCanvas): формы словаря из
 * 08-visual-concept.md — край с Енисеем, «система слушает», три облака площадок,
 * загорающиеся города, распространение, пусто, сбой, таблица. Без библиотек:
 * одна сцена `Points` со своим шейдером, Three.js не понадобился.
 * Запасной вариант — статичная карта (StaticKraiMap): без WebGL и при выключенном
 * переключателе «Анимация точек». При «уменьшить движение» формы статичны.
 */
import { useCallback, useState } from 'react';
import { useShell } from '@/app/shell-state';
import { ParticleCanvas } from './ParticleCanvas';
import { StaticKraiMap } from './StaticKraiMap';
import type { DotsSceneProps } from './types';

export function DotsScene(props: DotsSceneProps) {
  const { dotsEnabled, reducedMotion, resolvedTheme } = useShell();
  const [unsupported, setUnsupported] = useState(false);
  const onUnsupported = useCallback(() => setUnsupported(true), []);

  if (!dotsEnabled || unsupported) return <StaticKraiMap {...props} />;
  return (
    <ParticleCanvas
      {...props}
      still={reducedMotion}
      light={resolvedTheme === 'light'}
      onUnsupported={onUnsupported}
    />
  );
}
