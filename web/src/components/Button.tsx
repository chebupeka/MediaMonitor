import { LoaderCircle } from 'lucide-react';
import { Slot } from 'radix-ui';
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { Tooltip } from './Tooltip';
import styles from './Button.module.css';
import { cx } from './cx';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'link';
export type ButtonSize = 'sm' | 'md' | 'lg';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Значок слева от текста */
  iconStart?: ReactNode;
  /** Значок справа от текста */
  iconEnd?: ReactNode;
  /** Идёт действие: кнопка недоступна, вместо значка — индикатор */
  loading?: boolean;
  fullWidth?: boolean;
  /** Отрисовать дочерний элемент (например, <a>) со стилями кнопки */
  asChild?: boolean;
}

/** Кнопка. Высота не меньше 28 px, цель нажатия не меньше 24×24 (НТ-16). */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = 'secondary',
    size = 'md',
    iconStart,
    iconEnd,
    loading = false,
    fullWidth = false,
    asChild = false,
    className,
    children,
    disabled,
    type,
    ...rest
  },
  ref,
) {
  const classes = cx(
    styles.button,
    styles[variant],
    styles[size],
    fullWidth && styles.fullWidth,
    className,
  );
  if (asChild) {
    return (
      <Slot.Root ref={ref} className={classes} {...rest}>
        {children}
      </Slot.Root>
    );
  }
  return (
    <button
      ref={ref}
      type={type ?? 'button'}
      className={classes}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? (
        <span className={styles.icon} aria-hidden="true">
          <LoaderCircle className={styles.spinner} />
        </span>
      ) : (
        iconStart && (
          <span className={styles.icon} aria-hidden="true">
            {iconStart}
          </span>
        )
      )}
      {children}
      {iconEnd && (
        <span className={styles.icon} aria-hidden="true">
          {iconEnd}
        </span>
      )}
    </button>
  );
});

export interface IconButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> {
  /** Обязательная подпись: читается скринридером и показывается подсказкой */
  label: string;
  icon: ReactNode;
  variant?: Exclude<ButtonVariant, 'link'>;
  size?: Exclude<ButtonSize, 'lg'>;
  /** Показывать подсказку с подписью при наведении и фокусе (по умолчанию да) */
  tooltip?: boolean;
}

/** Кнопка-значок. Подпись обязательна: без неё кнопка непонятна скринридеру. */
export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, icon, variant = 'ghost', size = 'md', tooltip = true, className, type, ...rest },
  ref,
) {
  const button = (
    <button
      ref={ref}
      type={type ?? 'button'}
      aria-label={label}
      className={cx(styles.button, styles[variant], styles[size], styles.iconOnly, className)}
      {...rest}
    >
      <span className={styles.icon} aria-hidden="true">
        {icon}
      </span>
    </button>
  );
  return tooltip ? <Tooltip content={label}>{button}</Tooltip> : button;
});
