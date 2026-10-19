/**
 * СЛОТ «ТОЧКИ». Экраны используют только этот компонент.
 *
 * Сейчас — статичная SVG-карта (StaticKraiMap). Исполнитель «Точки» заменяет
 * реализацию на Three.js (лениво, `import('three')`), сохраняя интерфейс
 * DotsSceneProps и запасной вариант: без WebGL, при `prefers-reduced-motion`
 * и при выключенном переключателе точек — статичная форма.
 *
 * Настройки берите из оболочки: `const { dotsEnabled, reducedMotion, resolvedTheme } = useShell()`
 * (import { useShell } from '@/app/shell-state').
 */
import { StaticKraiMap } from './StaticKraiMap';
import type { DotsSceneProps } from './types';

export function DotsScene(props: DotsSceneProps) {
  // TODO(Э-Точки): при dotsEnabled && !reducedMotion && есть WebGL — 3D-сцена Three.js.
  return <StaticKraiMap {...props} />;
}
