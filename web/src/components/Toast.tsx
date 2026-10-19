import { CircleCheck, Info, OctagonX, TriangleAlert, X } from 'lucide-react';
import { Toast as RadixToast } from 'radix-ui';
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';
import styles from './Toast.module.css';
import { cx } from './cx';

/** Уведомления держатся не меньше 10 секунд (НТ-16). */
export const TOAST_MIN_MS = 10_000;

export interface ToastOptions {
  title: string;
  description?: string;
  tone?: 'neutral' | 'good' | 'warning' | 'critical';
  /** Действие в уведомлении, обычно «Отменить» */
  action?: { label: string; onAction: () => void; altText?: string };
  /** Сколько держится, мс; не меньше 10 000 */
  duration?: number;
}

interface ToastItem extends ToastOptions {
  id: number;
  open: boolean;
}

export interface ToastApi {
  /** Показать уведомление. Возвращает id. */
  show: (options: ToastOptions) => number;
  /** «Исключено: 1 публикация [Отменить]» — уведомление с отменой (держится 12 с). */
  undo: (title: string, onUndo: () => void, description?: string) => number;
  dismiss: (id: number) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

const ICON = {
  neutral: <Info />,
  good: <CircleCheck />,
  warning: <TriangleAlert />,
  critical: <OctagonX />,
};

let counter = 0;

/**
 * Провайдер уведомлений — один на приложение (в оболочке). Уведомления
 * не пропадают, пока на них наведён курсор или фокус; F8 переводит фокус к ним.
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const dismiss = useCallback((id: number) => {
    setToasts((list) => list.map((t) => (t.id === id ? { ...t, open: false } : t)));
    setTimeout(() => setToasts((list) => list.filter((t) => t.id !== id)), 400);
  }, []);

  const show = useCallback((options: ToastOptions) => {
    counter += 1;
    const id = counter;
    setToasts((list) => [...list.slice(-3), { ...options, id, open: true }]);
    return id;
  }, []);

  const undo = useCallback(
    (title: string, onUndo: () => void, description?: string) =>
      show({
        title,
        ...(description ? { description } : {}),
        tone: 'neutral',
        duration: 12_000,
        action: { label: 'Отменить', onAction: onUndo, altText: `Отменить: ${title}` },
      }),
    [show],
  );

  const api = useMemo<ToastApi>(() => ({ show, undo, dismiss }), [show, undo, dismiss]);

  return (
    <ToastContext.Provider value={api}>
      <RadixToast.Provider label="Уведомления (F8)" swipeDirection="right" duration={TOAST_MIN_MS}>
        {children}
        {toasts.map((t) => {
          const tone = t.tone ?? 'neutral';
          return (
            <RadixToast.Root
              key={t.id}
              open={t.open}
              onOpenChange={(open) => {
                if (!open) dismiss(t.id);
              }}
              duration={Math.max(TOAST_MIN_MS, t.duration ?? (t.action ? 12_000 : TOAST_MIN_MS))}
              className={cx(styles.toast, styles[tone])}
            >
              <span className={styles.icon} aria-hidden="true">
                {ICON[tone]}
              </span>
              <div className={styles.text}>
                <RadixToast.Title className={styles.title}>{t.title}</RadixToast.Title>
                {t.description && (
                  <RadixToast.Description className={styles.description}>
                    {t.description}
                  </RadixToast.Description>
                )}
              </div>
              {t.action && (
                <RadixToast.Action
                  altText={t.action.altText ?? t.action.label}
                  className={styles.action}
                  onClick={t.action.onAction}
                >
                  {t.action.label}
                </RadixToast.Action>
              )}
              <RadixToast.Close className={styles.close} aria-label="Закрыть уведомление">
                <X aria-hidden="true" />
              </RadixToast.Close>
            </RadixToast.Root>
          );
        })}
        <RadixToast.Viewport className={styles.viewport} />
      </RadixToast.Provider>
    </ToastContext.Provider>
  );
}

/** Показать уведомление: `const toast = useToast(); toast.undo('Исключено', restore)`. */
export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast: нет ToastProvider выше по дереву');
  return ctx;
}
