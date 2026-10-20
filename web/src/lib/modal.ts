/**
 * Открыто ли модальное окно. Пока окно открыто, всё под затемнением не видно — точки под
 * ним не рисуются (src/dots/ParticleField.tsx): на экране одна сцена, а не две.
 */
type Listener = (open: boolean) => void;

let depth = 0;
const listeners = new Set<Listener>();

/** Окно открылось; вызвать возвращённую функцию, когда закроется. */
export function holdModal(): () => void {
  depth += 1;
  if (depth === 1) listeners.forEach((fn) => fn(true));
  let released = false;
  return () => {
    if (released) return;
    released = true;
    depth -= 1;
    if (depth === 0) listeners.forEach((fn) => fn(false));
  };
}

export function isModalOpen(): boolean {
  return depth > 0;
}

export function onModalChange(fn: Listener): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
