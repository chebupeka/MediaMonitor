import {
  CircleCheck,
  CircleSlash,
  CircleStop,
  Clock,
  Hourglass,
  Info,
  LoaderCircle,
  Lock,
  OctagonX,
  TriangleAlert,
  Users,
  WifiOff,
} from 'lucide-react';
import type { ReactNode } from 'react';
import type { StatusIcon, StatusTone, StatusView } from '@/lib/labels';
import styles from './StatusBadge.module.css';
import { cx } from './cx';

const ICONS: Record<StatusIcon, ReactNode> = {
  waiting: <Clock />,
  progress: <LoaderCircle className={styles.spin} />,
  check: <CircleCheck />,
  nothing: <CircleSlash />,
  warning: <TriangleAlert />,
  error: <OctagonX />,
  lock: <Lock />,
  stopped: <CircleStop />,
  delay: <Hourglass />,
  info: <Info />,
  offline: <WifiOff />,
  queue: <Users />,
};

const DEFAULT_ICON: Record<StatusTone, StatusIcon> = {
  neutral: 'info',
  progress: 'progress',
  good: 'check',
  info: 'info',
  warning: 'warning',
  critical: 'error',
};

export interface StatusBadgeProps {
  tone: StatusTone;
  /** Значок из набора. По умолчанию — по тону. */
  icon?: StatusIcon;
  /** Свой значок вместо набора (lucide-react) */
  customIcon?: ReactNode;
  children: ReactNode;
  /** `soft` — с подложкой, `plain` — только значок и цветной текст */
  variant?: 'soft' | 'plain';
  size?: 'sm' | 'md';
  className?: string;
}

/**
 * Статус: значок + текст, не только цвет (НТ-3, НТ-16, SC-64).
 * Для статуса площадки удобнее `<StatusBadge {...platformStatusView(s)} />` — см. `fromView`.
 */
export function StatusBadge({
  tone,
  icon,
  customIcon,
  children,
  variant = 'soft',
  size = 'md',
  className,
}: StatusBadgeProps) {
  const iconNode = customIcon ?? ICONS[icon ?? DEFAULT_ICON[tone]];
  return (
    <span className={cx(styles.badge, styles[tone], styles[variant], styles[size], className)}>
      <span className={styles.icon} aria-hidden="true">
        {iconNode}
      </span>
      <span className={styles.text}>{children}</span>
    </span>
  );
}

/** Отрисовать готовое представление статуса из `platformStatusView()`. */
export function StatusBadgeFromView({
  view,
  variant,
  size,
}: {
  view: StatusView;
  variant?: 'soft' | 'plain';
  size?: 'sm' | 'md';
}) {
  return (
    <StatusBadge tone={view.tone} icon={view.icon} variant={variant} size={size}>
      {view.text}
    </StatusBadge>
  );
}
