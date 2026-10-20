/**
 * Рабочее место в интерфейсе (Р8; аудит веб-версии, О2; решения Р-В1, Р-В2).
 *
 * - Окно «Рабочее место» (меню ☰): сколько в нём источников и поисков, ссылка-ключ
 *   «Открыть на другом компьютере или в расширении» с кнопкой «Скопировать», открыть другое
 *   место по ссылке или ключу, вернуться в прежнее.
 * - Вопрос при ссылке `#workspace=` на другое место (Р-В2): открыть её или остаться в своём.
 *   Своё место не стирается — вернуться в него можно из того же окна.
 * - Один раз после первого поиска — ненавязчивая подсказка сохранить ссылку (Р-В1).
 *
 * После перехода в другое место страница загружается заново: все разделы показывают его
 * данные, а не смесь двух мест.
 */
import { ArrowLeftRight, Copy, KeyRound, Link2 } from 'lucide-react';
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type FormEvent,
  type ReactNode,
} from 'react';
import { api, errorMessage, isApiError, useAsync } from '@/api';
import type { Workspace } from '@/api/types';
import { Button, cx, Dialog, DialogClose, Skeleton, TextField, useToast } from '@/components';
import { formatCount, WORDS } from '@/lib/format';
import { getHost } from '@/lib/host';
import styles from './workspace.module.css';

/** «12 источников и 5 поисков» */
function contents(w: Workspace): string {
  return `${formatCount(w.sourcesCount, WORDS.source)} и ${formatCount(w.recentCount, WORDS.search)}`;
}

/** Перешли в другое место: забыть прошлый поиск вкладки (он из другого места) и загрузиться заново. */
async function reloadInto(): Promise<void> {
  await getHost().session.set('mm:search', null);
  window.location.reload();
}

/**
 * Скопировать ссылку. Clipboard API есть только на HTTPS и localhost; на стенде по http —
 * запасной путь: выделить текст в поле и скопировать командой браузера.
 */
async function copyText(text: string, field: HTMLInputElement | null): Promise<boolean> {
  try {
    if (window.isSecureContext && navigator.clipboard) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // ниже — запасной путь
  }
  if (!field) return false;
  field.focus();
  field.select();
  try {
    // Устаревшая, но единственная команда копирования без HTTPS.
    return document.execCommand('copy');
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------- окно «Рабочее место»

function WorkspaceDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const workspace = useAsync(
    useCallback(() => (open ? api.getWorkspace() : Promise.resolve(null)), [open]),
  );
  const link = useAsync(
    useCallback(() => (open ? api.getWorkspaceLink() : Promise.resolve(null)), [open]),
  );
  const previousKey = open ? api.previousWorkspaceKey() : null;
  const previous = useAsync(
    useCallback(
      () => (previousKey ? api.peekWorkspace(previousKey) : Promise.resolve(null)),
      [previousKey],
    ),
  );
  const fieldRef = useRef<HTMLInputElement>(null);
  const [copied, setCopied] = useState<'yes' | 'manual' | null>(null);
  const [other, setOther] = useState('');
  const [opening, setOpening] = useState(false);
  const [openError, setOpenError] = useState<string | null>(null);

  useEffect(() => {
    if (open) return;
    setCopied(null);
    setOther('');
    setOpenError(null);
  }, [open]);

  const copy = async () => {
    const url = link.data?.url;
    if (!url) return;
    setCopied((await copyText(url, fieldRef.current)) ? 'yes' : 'manual');
  };

  const switchTo = async (key: string) => {
    setOpening(true);
    setOpenError(null);
    try {
      await api.openWorkspace(key);
      await reloadInto();
    } catch (error) {
      setOpening(false);
      setOpenError(
        isApiError(error) && error.code === 'not-found'
          ? 'Рабочего места по этой ссылке нет. Проверьте, что ссылку скопировали целиком.'
          : errorMessage(error),
      );
    }
  };

  const onOpenOther = (e: FormEvent) => {
    e.preventDefault();
    if (other.trim()) void switchTo(other);
  };

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title="Рабочее место"
      description="Здесь ваши источники и недавние поиски. Входа и пароля нет — доступ даёт ссылка."
      footer={
        <DialogClose>
          <Button variant="secondary">Готово</Button>
        </DialogClose>
      }
    >
      <div className={styles.stack}>
        <p className={styles.summary} aria-live="polite">
          {workspace.data ? (
            <>
              <span className={styles.dot} aria-hidden="true" />
              <span>
                Сейчас в нём <b>{contents(workspace.data)}</b>.
              </span>
            </>
          ) : workspace.status === 'error' ? (
            workspace.error?.message
          ) : (
            <Skeleton width="60%" height={14} />
          )}
        </p>

        <section className={styles.block} aria-labelledby="ws-link-title">
          <h3 id="ws-link-title" className={styles.blockTitle}>
            <Link2 aria-hidden="true" />
            Открыть на другом компьютере или в расширении
          </h3>
          <div className={styles.row}>
            <TextField
              ref={fieldRef}
              label="Ссылка на рабочее место"
              hideLabel
              readOnly
              className={cx(styles.grow, styles.linkField)}
              value={link.data?.url ?? (link.status === 'error' ? '' : 'Получаем ссылку…')}
              onFocus={(e) => e.currentTarget.select()}
              error={link.status === 'error' ? link.error?.message : undefined}
            />
            <Button
              variant="primary"
              iconStart={<Copy />}
              onClick={() => void copy()}
              disabled={!link.data}
            >
              Скопировать
            </Button>
          </div>
          <p className={styles.note} role="status">
            {copied === 'yes'
              ? 'Ссылка скопирована. Откройте её в другом браузере — там будут те же источники и поиски.'
              : copied === 'manual'
                ? 'Скопировать само не получилось: ссылка выделена — нажмите Ctrl+C (на Mac — ⌘+C).'
                : 'Сохраните ссылку, например в заметках: без неё после очистки данных браузера место не открыть.'}
          </p>
          <p className={styles.warning}>
            <KeyRound aria-hidden="true" />
            <span>
              Кто знает ссылку — видит и меняет ваши поиски и источники. Не публикуйте её.
            </span>
          </p>
        </section>

        <section className={styles.block} aria-labelledby="ws-open-title">
          <h3 id="ws-open-title" className={styles.blockTitle}>
            <ArrowLeftRight aria-hidden="true" />
            Открыть другое рабочее место
          </h3>
          <form className={styles.row} onSubmit={onOpenOther}>
            <TextField
              label="Ссылка или ключ рабочего места"
              hideLabel
              placeholder="Вставьте ссылку или ключ"
              className={styles.grow}
              value={other}
              onChange={(e) => setOther(e.target.value)}
              autoComplete="off"
              spellCheck={false}
            />
            <Button type="submit" variant="secondary" disabled={!other.trim()} loading={opening}>
              Открыть
            </Button>
          </form>
          {openError && (
            <p className={styles.error} role="alert">
              {openError}
            </p>
          )}
          {previousKey && previous.status !== 'error' && (
            <div className={styles.previous}>
              <span>
                Прежнее рабочее место
                {previous.data ? `: ${contents(previous.data)}` : ''}.
              </span>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => void switchTo(previousKey)}
                disabled={opening}
              >
                Вернуться в прежнее
              </Button>
            </div>
          )}
          <p className={styles.note}>Текущее место не пропадёт: вернуться в него можно здесь же.</p>
        </section>
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- ссылка на другое место (Р-В2)

function usePendingLink(): string | null {
  return useSyncExternalStore(
    (onChange) => api.onPendingWorkspaceLink(onChange),
    () => api.pendingWorkspaceLink(),
  );
}

function LinkPrompt() {
  const pending = usePendingLink();
  const current = useAsync(
    useCallback(() => (pending ? api.getWorkspace() : Promise.resolve(null)), [pending]),
  );
  const target = useAsync(
    useCallback(() => (pending ? api.peekWorkspace(pending) : Promise.resolve(null)), [pending]),
  );
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const missing = target.status === 'error' && target.error?.code === 'not-found';

  const accept = async () => {
    if (!pending) return;
    setOpening(true);
    setError(null);
    try {
      await api.openWorkspace(pending);
      await reloadInto();
    } catch (e) {
      setOpening(false);
      setError(errorMessage(e));
    }
  };

  return (
    <Dialog
      open={pending !== null}
      onOpenChange={(open) => {
        if (!open) api.dismissWorkspaceLink();
      }}
      size="sm"
      title={missing ? 'Ссылка не подходит' : 'Открыть рабочее место по ссылке?'}
      description={
        missing
          ? 'Рабочего места по этой ссылке нет: возможно, её скопировали не целиком. Остаётесь в своём.'
          : 'Ссылка ведёт в другое рабочее место — с другими источниками и поисками.'
      }
      footer={
        missing ? (
          <DialogClose>
            <Button variant="primary">Понятно</Button>
          </DialogClose>
        ) : (
          <>
            <DialogClose>
              <Button variant="secondary">Остаться в своём</Button>
            </DialogClose>
            <Button variant="primary" onClick={() => void accept()} loading={opening}>
              Открыть по ссылке
            </Button>
          </>
        )
      }
    >
      {!missing && (
        <div className={styles.stack}>
          <dl className={styles.compare}>
            <div>
              <dt>Ваше текущее</dt>
              <dd>{current.data ? contents(current.data) : '…'}</dd>
            </div>
            <div>
              <dt>По ссылке</dt>
              <dd>{target.data ? contents(target.data) : '…'}</dd>
            </div>
          </dl>
          <p className={styles.note}>
            Ваше место не пропадёт: вернуться в него можно в меню ☰ → «Рабочее место».
          </p>
          {error && (
            <p className={styles.error} role="alert">
              {error}
            </p>
          )}
        </div>
      )}
    </Dialog>
  );
}

// ---------------------------------------------------------------- подсказка после первого поиска (Р-В1)

const HINT_KEY = 'mm-workspace-hint';

function hintShown(): boolean {
  try {
    return window.localStorage.getItem(HINT_KEY) === '1';
  } catch {
    return true; // без хранилища подсказку не показываем: она появлялась бы каждый раз
  }
}

function markHintShown(): void {
  try {
    window.localStorage.setItem(HINT_KEY, '1');
  } catch {
    // не запомнили — не страшно
  }
}

// ---------------------------------------------------------------- контекст

interface WorkspaceUi {
  /** Открыть окно «Рабочее место». */
  openDialog: () => void;
  /** Поиск закончился: один раз в этом браузере подсказать сохранить ссылку (Р-В1). */
  suggestSavingLink: () => void;
}

const WorkspaceContext = createContext<WorkspaceUi | null>(null);

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const toast = useToast();
  const openDialog = useCallback(() => setOpen(true), []);
  const suggestSavingLink = useCallback(() => {
    if (hintShown()) return;
    markHintShown();
    toast.show({
      title: 'Сохраните ссылку на рабочее место',
      description: 'С ней ваши поиски и источники откроются на другом компьютере.',
      action: {
        label: 'Показать',
        altText: 'Показать ссылку: меню ☰ → «Рабочее место»',
        onAction: () => setOpen(true),
      },
      duration: 16_000,
    });
  }, [toast]);
  const value = useMemo(() => ({ openDialog, suggestSavingLink }), [openDialog, suggestSavingLink]);
  return (
    <WorkspaceContext.Provider value={value}>
      {children}
      <WorkspaceDialog open={open} onOpenChange={setOpen} />
      <LinkPrompt />
    </WorkspaceContext.Provider>
  );
}

export function useWorkspaceUi(): WorkspaceUi {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error('useWorkspaceUi: нет WorkspaceProvider выше по дереву');
  return ctx;
}
