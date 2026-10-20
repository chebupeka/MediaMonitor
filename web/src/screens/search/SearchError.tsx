/**
 * Поиск не запустился или не удался (аудит веб-версии, О1). Причина — текстом от сервера,
 * а кнопки — по смыслу ошибки:
 * - лимит (`too-many-requests`): «Повторить» доступна, когда пройдёт время из Retry-After;
 *   если уже идёт другой поиск этого рабочего места — «Показать идущий поиск»;
 * - запрос не подходит (`too-long`, `invalid`): повторять тот же запрос бессмысленно —
 *   «Исправить запрос»;
 * - нет связи, сбой сервера, поиск не найден — «Повторить».
 */
import { Eye, PenLine, RotateCw } from 'lucide-react';
import { useEffect, useState } from 'react';
import type { ApiError } from '@/api/types';
import { Button, ErrorState } from '@/components';

const TITLES: Record<ApiError['code'], string> = {
  'too-many-requests': 'Поиск пока не запущен',
  'too-long': 'Запрос слишком длинный',
  invalid: 'Запрос не подходит',
  offline: 'Нет связи с сервером',
  'not-found': 'Поиск не найден',
  server: 'Поиск не удался',
};

/** Сколько секунд ещё ждать; обновляется раз в секунду. */
function useCountdown(error: ApiError): number {
  const wait =
    error.code === 'too-many-requests' ? Math.max(0, Math.ceil(error.retryAfterSec ?? 0)) : 0;
  const [left, setLeft] = useState(wait);
  useEffect(() => {
    setLeft(wait);
    if (wait <= 0) return;
    const started = Date.now();
    const timer = window.setInterval(() => {
      const rest = Math.max(0, wait - Math.floor((Date.now() - started) / 1000));
      setLeft(rest);
      if (rest === 0) window.clearInterval(timer);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [error, wait]);
  return left;
}

export function SearchError({
  error,
  onRetry,
  onEdit,
  onShowRunning,
}: {
  error: ApiError;
  onRetry: () => void;
  /** Поставить курсор в поле запроса */
  onEdit: () => void;
  /** Подключиться к идущему поиску (429 «уже идёт поиск») */
  onShowRunning: (searchId: string) => void;
}) {
  const left = useCountdown(error);
  const running = error.code === 'too-many-requests' ? error.runningSearchId : undefined;
  const fixQuery = error.code === 'too-long' || error.code === 'invalid';

  const retry = (
    <Button
      variant={running ? 'secondary' : 'primary'}
      iconStart={<RotateCw />}
      onClick={onRetry}
      disabled={left > 0}
    >
      {left > 0 ? `Повторить через ${left} с` : 'Повторить'}
    </Button>
  );

  return (
    <ErrorState
      title={running ? 'Уже идёт другой поиск' : TITLES[error.code]}
      description={error.message}
      kind={error.code === 'offline' ? 'offline' : 'error'}
      actions={
        fixQuery ? (
          <Button variant="primary" iconStart={<PenLine />} onClick={onEdit}>
            Исправить запрос
          </Button>
        ) : (
          <>
            {running && (
              <Button variant="primary" iconStart={<Eye />} onClick={() => onShowRunning(running)}>
                Показать идущий поиск
              </Button>
            )}
            {retry}
          </>
        )
      }
    />
  );
}
