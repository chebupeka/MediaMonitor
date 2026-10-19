import { Tooltip as RadixTooltip } from 'radix-ui';
import type { ReactElement, ReactNode } from 'react';
import styles from './Tooltip.module.css';

export interface TooltipProps {
  /** Текст подсказки. Важное не прячьте только в подсказку — она не видна на касание. */
  content: ReactNode;
  /** Один фокусируемый элемент (кнопка, ссылка) */
  children: ReactElement;
  side?: 'top' | 'right' | 'bottom' | 'left';
  align?: 'start' | 'center' | 'end';
}

/** Подсказка при наведении и при фокусе с клавиатуры. Провайдер — в оболочке. */
export function Tooltip({ content, children, side = 'top', align = 'center' }: TooltipProps) {
  return (
    <RadixTooltip.Root>
      <RadixTooltip.Trigger asChild>{children}</RadixTooltip.Trigger>
      <RadixTooltip.Portal>
        <RadixTooltip.Content
          className={styles.content}
          side={side}
          align={align}
          sideOffset={6}
          collisionPadding={8}
        >
          {content}
          <RadixTooltip.Arrow className={styles.arrow} width={10} height={5} />
        </RadixTooltip.Content>
      </RadixTooltip.Portal>
    </RadixTooltip.Root>
  );
}

/** Провайдер подсказок: один на приложение (в оболочке). */
export const TooltipProvider = RadixTooltip.Provider;
