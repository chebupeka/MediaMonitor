/**
 * Кнопки вида в шапке — как на сайте (site/index.html, .prefs): тема, «Тёплый свет» и версия
 * для слабовидящих, без окон и меню; aria-pressed. «Тёплый свет» — только в светлой теме:
 * выезжает из-под кнопки темы при наведении или фокусе, включённый виден всегда, после
 * касания показывается на 4 с. В боковой панели кнопки компактнее.
 */
import { useRef, useState, type PointerEvent } from 'react';
import { cx } from '@/components';
import { useShell } from './shell-state';
import styles from './PrefsButtons.module.css';

function ThemeIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="8.25" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <path d="M12 3.75a8.25 8.25 0 0 1 0 16.5z" fill="currentColor" />
    </svg>
  );
}

function WarmIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
    >
      <path d="M3 17.5h18M6.5 17.5a5.5 5.5 0 0 1 11 0M12 6.5v2.2M5.3 9.6l1.6 1.5M18.7 9.6l-1.6 1.5M8.5 20.5h7" />
    </svg>
  );
}

function EyeIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinejoin="round"
    >
      <path d="M2.5 12S6 5.75 12 5.75 21.5 12 21.5 12 18 18.25 12 18.25 2.5 12 2.5 12z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

export function PrefsButtons({ compact }: { compact: boolean }) {
  const { theme, setTheme, warm, setWarm, lowVision, setLowVision } = useShell();
  const light = theme === 'light';
  const [reveal, setReveal] = useState(false);
  const timer = useRef(0);

  // На касании у кнопки нет фокуса (Safari) — «Тёплый свет» показываем на 4 с
  const onThemeClick = (e: PointerEvent<HTMLButtonElement>) => {
    const next = !light;
    setTheme(next ? 'light' : 'dark');
    if (next && e.pointerType && e.pointerType !== 'mouse') {
      setReveal(true);
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setReveal(false), 4000);
    }
  };

  return (
    <div className={cx(styles.prefs, compact && styles.compact)} role="group" aria-label="Вид">
      <div className={cx(styles.themeGroup, reveal && styles.reveal)}>
        <button
          type="button"
          className={styles.pref}
          aria-pressed={light}
          aria-label="Светлая тема"
          title="Светлая тема"
          onClick={onThemeClick}
        >
          <ThemeIcon />
        </button>
        {light && (
          <button
            type="button"
            className={cx(styles.pref, styles.warm)}
            aria-pressed={warm}
            aria-label="Тёплый свет: меньше синего"
            title="Тёплый свет: меньше синего"
            onClick={() => setWarm(!warm)}
          >
            <WarmIcon />
          </button>
        )}
      </div>
      <button
        type="button"
        className={styles.pref}
        aria-pressed={lowVision}
        aria-label="Версия для слабовидящих"
        title="Версия для слабовидящих"
        onClick={() => setLowVision(!lowVision)}
      >
        <EyeIcon />
      </button>
    </div>
  );
}
