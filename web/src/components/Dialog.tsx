import { X } from 'lucide-react';
import { Dialog as RadixDialog } from 'radix-ui';
import type { ReactNode } from 'react';
import { IconButton } from './Button';
import styles from './Dialog.module.css';
import { cx } from './cx';

export interface DialogProps {
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Элемент, который открывает окно (кнопка). Можно не передавать и управлять `open`. */
  trigger?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  /** Кнопки внизу окна */
  footer?: ReactNode;
  size?: 'sm' | 'md' | 'lg' | 'xl';
  children?: ReactNode;
  className?: string;
}

/**
 * Модальное окно на Radix: фокус внутри окна, Esc закрывает, фокус возвращается
 * на кнопку, которая открыла окно.
 */
export function Dialog({
  open,
  onOpenChange,
  trigger,
  title,
  description,
  footer,
  size = 'md',
  children,
  className,
}: DialogProps) {
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      {trigger && <RadixDialog.Trigger asChild>{trigger}</RadixDialog.Trigger>}
      <RadixDialog.Portal>
        <RadixDialog.Overlay className={styles.overlay} />
        <RadixDialog.Content
          className={cx(styles.content, styles[size], className)}
          {...(description ? {} : { 'aria-describedby': undefined })}
        >
          <div className={styles.header}>
            <div className={styles.titles}>
              <RadixDialog.Title className={styles.title}>{title}</RadixDialog.Title>
              {description && (
                <RadixDialog.Description className={styles.description}>
                  {description}
                </RadixDialog.Description>
              )}
            </div>
            <RadixDialog.Close asChild>
              <IconButton label="Закрыть" icon={<X />} tooltip={false} />
            </RadixDialog.Close>
          </div>
          {children && <div className={styles.body}>{children}</div>}
          {footer && <div className={styles.footer}>{footer}</div>}
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}

/** Кнопка, закрывающая окно (для `footer`): `<DialogClose><Button>Готово</Button></DialogClose>` */
export function DialogClose({ children }: { children: ReactNode }) {
  return <RadixDialog.Close asChild>{children}</RadixDialog.Close>;
}
