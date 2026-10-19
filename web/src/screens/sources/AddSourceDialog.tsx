/**
 * «Добавить по ссылке» с проверкой сразу (П9, SC-10): доступен, закрыт, не та площадка,
 * уже в списке, пишет не только о крае. Проверка — через `api.checkSource`, добавление —
 * `api.addSource`. Название, тип и район подставляются из проверки, их можно поправить.
 */
import { Link2, Plus } from 'lucide-react';
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { api, demoLinks, errorMessage, IS_MOCKUP } from '@/api';
import type { Source, SourceCheck, SourceType } from '@/api/types';
import {
  Button,
  Chip,
  Dialog,
  DialogClose,
  PlatformDot,
  StatusBadge,
  TextField,
  useAnnounce,
} from '@/components';
import { formatDateTime, TIME_ZONE_LABEL } from '@/lib/format';
import { PLATFORMS } from '@/lib/labels';
import { looksLikeUrl, shortUrl, subscribersText, checkView, VERDICT_TITLE } from './model';
import { DistrictField, OutLink, TypeField } from './fields';
import styles from './sources.module.css';

type Phase =
  | { kind: 'idle' }
  | { kind: 'checking'; url: string }
  | { kind: 'checked'; url: string; check: SourceCheck }
  | { kind: 'error'; url: string; message: string };

/** Ссылки для демо: чтобы увидеть все ответы проверки (только мокап). */
const DEMO_EXAMPLES: readonly { label: string; url: string }[] = [
  { label: 'доступна', url: demoLinks.sourceOk },
  { label: 'закрытая', url: demoLinks.sourceClosed },
  { label: 'ссылка на пост', url: demoLinks.sourcePostLink },
  { label: 'не про край', url: demoLinks.sourceNotRegional },
  { label: 'не та площадка', url: demoLinks.sourceNotSupported },
  { label: 'уже в списке', url: demoLinks.sourceDuplicate },
];

export interface AddSourceDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  districts: readonly string[];
  onAdded: (source: Source) => void;
  /** «Показать в списке» для дубля */
  onShowExisting: (name: string) => void;
}

export function AddSourceDialog({
  open,
  onOpenChange,
  districts,
  onAdded,
  onShowExisting,
}: AddSourceDialogProps) {
  const announce = useAnnounce();
  const [url, setUrl] = useState('');
  const [phase, setPhase] = useState<Phase>({ kind: 'idle' });
  const [name, setName] = useState('');
  const [type, setType] = useState<SourceType>('media');
  const [district, setDistrict] = useState('');
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);
  const request = useRef(0);
  const lastChecked = useRef('');
  const inputRef = useRef<HTMLInputElement>(null);

  const runCheck = useCallback(
    async (raw: string) => {
      const value = raw.trim();
      if (!value) return;
      lastChecked.current = value;
      request.current += 1;
      const id = request.current;
      setAddError(null);
      setPhase({ kind: 'checking', url: value });
      try {
        const check = await api.checkSource(value);
        if (id !== request.current) return;
        setPhase({ kind: 'checked', url: value, check });
        if (check.preview) {
          setName(check.preview.name);
          setType(check.preview.suggestedType);
          setDistrict(check.preview.suggestedDistrict ?? '');
        }
        announce(`${VERDICT_TITLE[check.state]}. ${check.message}`);
      } catch (error) {
        if (id !== request.current) return;
        const message = errorMessage(error);
        setPhase({ kind: 'error', url: value, message });
        announce(message);
      }
    },
    [announce],
  );

  // Проверка «сразу»: через 0,7 с после того, как перестали печатать.
  useEffect(() => {
    const value = url.trim();
    if (!looksLikeUrl(value) || value === lastChecked.current) return;
    const timer = window.setTimeout(() => void runCheck(value), 700);
    return () => window.clearTimeout(timer);
  }, [url, runCheck]);

  const reset = (): void => {
    request.current += 1;
    lastChecked.current = '';
    setUrl('');
    setPhase({ kind: 'idle' });
    setName('');
    setType('media');
    setDistrict('');
    setAddError(null);
    setAdding(false);
  };

  const handleOpenChange = (next: boolean): void => {
    if (!next) reset();
    onOpenChange(next);
  };

  const onSubmitUrl = (event: FormEvent): void => {
    event.preventDefault();
    void runCheck(url);
  };

  const addable =
    phase.kind === 'checked' &&
    (phase.check.state === 'ok' || phase.check.state === 'not-regional');
  const canAdd = addable && !adding && name.trim().length > 0;

  const add = async (): Promise<void> => {
    if (phase.kind !== 'checked') return;
    setAdding(true);
    setAddError(null);
    try {
      const source = await api.addSource({
        url: phase.url,
        name: name.trim(),
        type,
        district: district.trim() || null,
      });
      onAdded(source);
      reset();
      onOpenChange(false);
    } catch (error) {
      setAddError(errorMessage(error));
      setAdding(false);
    }
  };

  const tryExample = (value: string): void => {
    setUrl(value);
    void runCheck(value);
    inputRef.current?.focus();
  };

  return (
    <Dialog
      open={open}
      onOpenChange={handleOpenChange}
      size="md"
      title="Добавить по ссылке"
      description="Ссылка на группу ВКонтакте или Одноклассников либо на канал MAX. Проверим её сразу."
      footer={
        <>
          <DialogClose>
            <Button>Отмена</Button>
          </DialogClose>
          <Button
            variant="primary"
            iconStart={<Plus />}
            disabled={!canAdd}
            loading={adding}
            onClick={() => void add()}
          >
            Добавить в список
          </Button>
        </>
      }
    >
      <div className={styles.dialogStack}>
        <form className={styles.urlRow} onSubmit={onSubmitUrl}>
          <TextField
            ref={inputRef}
            label="Ссылка на группу или канал"
            placeholder="vk.com/…, ok.ru/group/… или max.ru/…"
            value={url}
            inputMode="url"
            autoComplete="off"
            spellCheck={false}
            onChange={(e) => setUrl(e.target.value)}
            onPaste={(e) => {
              const pasted = e.clipboardData.getData('text');
              if (pasted.trim()) {
                e.preventDefault();
                setUrl(pasted.trim());
                void runCheck(pasted);
              }
            }}
            aria-describedby="add-source-url-hint"
            className={styles.urlField}
          />
          <Button
            type="submit"
            iconStart={<Link2 />}
            loading={phase.kind === 'checking'}
            disabled={!url.trim()}
          >
            Проверить
          </Button>
        </form>
        <p id="add-source-url-hint" className={styles.hintText}>
          Подойдёт любой вид адреса: vk.com, vk.ru, m.vk.com, club123.
        </p>

        {IS_MOCKUP && (
          <div className={styles.examples}>
            <span className={styles.examplesLabel}>Примеры для демо:</span>
            {DEMO_EXAMPLES.map((ex) => (
              <Chip key={ex.label} size="sm" onClick={() => tryExample(ex.url)}>
                {ex.label}
              </Chip>
            ))}
          </div>
        )}

        <CheckResult
          phase={phase}
          onRetry={() => void runCheck(url)}
          onCheckUrl={tryExample}
          onShowExisting={(n) => {
            handleOpenChange(false);
            onShowExisting(n);
          }}
        />

        {addable && (
          <fieldset className={styles.fields}>
            <legend className={styles.legendTitle}>Как показать в списке</legend>
            <TextField
              label="Название"
              value={name}
              onChange={(e) => setName(e.target.value)}
              error={name.trim() ? undefined : 'Название не может быть пустым'}
            />
            <TypeField value={type} onChange={setType} />
            <DistrictField
              id="add-source-district"
              value={district}
              onChange={setDistrict}
              districts={districts}
            />
          </fieldset>
        )}

        {addError && (
          <p className={styles.errorText} role="alert">
            {addError}
          </p>
        )}
      </div>
    </Dialog>
  );
}

function CheckResult({
  phase,
  onRetry,
  onCheckUrl,
  onShowExisting,
}: {
  phase: Phase;
  onRetry: () => void;
  onCheckUrl: (url: string) => void;
  onShowExisting: (name: string) => void;
}) {
  switch (phase.kind) {
    case 'idle':
      return null;
    case 'checking':
      return (
        <p>
          <StatusBadge tone="progress" icon="progress">
            Проверяем ссылку…
          </StatusBadge>
        </p>
      );
    case 'error':
      return (
        <div className={styles.verdict}>
          <StatusBadge tone="critical" icon="error">
            Не удалось проверить
          </StatusBadge>
          <p className={styles.verdictText}>{phase.message}</p>
          <div>
            <Button size="sm" onClick={onRetry}>
              Проверить снова
            </Button>
          </div>
        </div>
      );
    case 'checked':
      return (
        <Verdict check={phase.check} onCheckUrl={onCheckUrl} onShowExisting={onShowExisting} />
      );
  }
}

function Verdict({
  check,
  onCheckUrl,
  onShowExisting,
}: {
  check: SourceCheck;
  onCheckUrl: (url: string) => void;
  onShowExisting: (name: string) => void;
}) {
  const view = checkView(check);
  const preview = check.preview;
  return (
    <div className={styles.verdict}>
      <StatusBadge tone={view.tone} icon={view.icon} className={styles.wrapBadge}>
        {VERDICT_TITLE[check.state]}
      </StatusBadge>
      {preview && (
        <div className={styles.preview}>
          <p className={styles.previewName}>
            <PlatformDot platform={preview.platform} />
            <span>
              {preview.name}
              <span className={styles.sourcePlatform}> · {PLATFORMS[preview.platform].name}</span>
            </span>
          </p>
          <p className={styles.previewFacts}>
            {preview.lastPostAt
              ? `последний пост ${formatDateTime(preview.lastPostAt)}`
              : 'дата последнего поста неизвестна'}
            {' · '}
            {subscribersText(preview.subscribers)}
          </p>
          <OutLink href={preview.url}>{shortUrl(preview.url)}</OutLink>
        </div>
      )}
      <p className={styles.verdictText}>{check.message}</p>
      {check.state === 'closed' && (
        <p className={styles.verdictText}>
          Посты закрытых групп видят только участники. Мы ищем только публичные посты, поэтому такую
          группу в список не добавляем.
        </p>
      )}
      {check.state === 'post-link' && preview && (
        <div>
          <Button size="sm" onClick={() => onCheckUrl(preview.url)}>
            Проверить {preview.platform === 'max' ? 'этот канал' : 'эту группу'}
          </Button>
        </div>
      )}
      {check.state === 'duplicate' && preview && (
        <div>
          <Button size="sm" onClick={() => onShowExisting(preview.name)}>
            Показать в списке
          </Button>
        </div>
      )}
      <p className={styles.checkedAt}>
        Проверено {formatDateTime(check.checkedAt)}, {TIME_ZONE_LABEL}
      </p>
    </div>
  );
}
