/**
 * Можно ли анимировать интерфейс: человек не просил уменьшить движение и не включил версию
 * для слабовидящих (без анимаций, «расшифровки» и своего курсора — 04-decisions.md,
 * «Темы и доступность»; атрибут data-lowvision на <html>, src/app/prefs.ts).
 */
export function motionAllowed(): boolean {
  if (typeof window === 'undefined') return false;
  if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return false;
  return !document.documentElement.hasAttribute('data-lowvision');
}
