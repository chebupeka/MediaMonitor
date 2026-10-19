/**
 * Импорт списка из Excel (ТЗ-Ф16, SC-11): выбрать файл → предпросмотр «что добавим, что уже
 * в списке, что пропустим и почему» (`previewImport`, ничего не добавляет) → добавить ровно
 * строки «добавим» (`importSources(previewId)`) → отчёт. Добавленное можно отменить одной
 * кнопкой. Текущий список не затирается: новые источники добавляются к нему.
 */
import { FileSpreadsheet, Undo2, Upload } from 'lucide-react';
import { useRef, useState, type DragEvent } from 'react';
import { api, errorMessage, IS_MOCKUP } from '@/api';
import type { ImportPreview, ImportReport, ImportRow, Source } from '@/api/types';
import {
  Button,
  cx,
  Dialog,
  DialogClose,
  ErrorState,
  PlatformDot,
  SkeletonText,
  StatusBadge,
  useAnnounce,
} from '@/components';
import { formatCount, formatNumber, WORDS } from '@/lib/format';
import { PLATFORMS } from '@/lib/labels';
import styles from './sources.module.css';

type Step =
  | { kind: 'choose'; error: string | null }
  | { kind: 'previewing'; file: File }
  | { kind: 'preview'; file: File; preview: ImportPreview; importing: boolean }
  | { kind: 'done'; file: File; report: ImportReport; undone: boolean; undoing: boolean }
  | { kind: 'failed'; file: File; message: string; preview: ImportPreview | null };

const ACCEPT = '.xlsx,.xls,.csv';
/** Имя демо-файла (только мокап). */
const DEMO_FILE_NAME = 'Источники агентства.xlsx';
const ROW_WORDS = ['строка', 'строки', 'строк'] as const;
const sizeFormat = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 });

function isSpreadsheet(file: File): boolean {
  return /\.(xlsx|xls|csv)$/iu.test(file.name);
}

function fileSize(bytes: number): string {
  if (bytes < 1024) return `${formatNumber(bytes)} Б`;
  if (bytes < 1024 * 1024) return `${sizeFormat.format(bytes / 1024)} КБ`;
  return `${sizeFormat.format(bytes / 1024 / 1024)} МБ`;
}

export interface ImportDialogProps {
  onOpenChange: (open: boolean) => void;
  onImported: (added: Source[]) => void;
  /** Импорт отменён: эти источники убраны из списка */
  onUndone: (ids: string[]) => void;
}

export function ImportDialog({ onOpenChange, onImported, onUndone }: ImportDialogProps) {
  const announce = useAnnounce();
  const [step, setStep] = useState<Step>({ kind: 'choose', error: null });
  const [dragOver, setDragOver] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const doneRef = useRef<HTMLButtonElement>(null);
  /** Разбор последнего выбранного файла: ответ на прежний файл не показываем. */
  const request = useRef(0);

  const runPreview = async (file: File): Promise<void> => {
    request.current += 1;
    const id = request.current;
    setStep({ kind: 'previewing', file });
    try {
      const preview = await api.previewImport(file);
      if (id !== request.current) return;
      setStep({ kind: 'preview', file, preview, importing: false });
      announce(
        `Файл разобран: добавим ${formatCount(preview.counts.add, WORDS.source)}, уже в списке ${formatNumber(preview.counts.duplicate)}, пропустим ${formatCount(preview.counts.skip, ROW_WORDS)}`,
      );
    } catch (e) {
      if (id !== request.current) return;
      setStep({ kind: 'failed', file, message: errorMessage(e), preview: null });
    }
  };

  const pick = (file: File | undefined): void => {
    if (!file) return;
    if (!isSpreadsheet(file)) {
      setStep({
        kind: 'choose',
        error: `«${file.name}» — не таблица. Нужен файл Excel (.xlsx, .xls) или CSV.`,
      });
      return;
    }
    announce(`Выбран файл «${file.name}»`);
    void runPreview(file);
  };

  const takeDemoFile = (): void => {
    pick(
      new File(['демо'], DEMO_FILE_NAME, {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      }),
    );
  };

  const onDrop = (event: DragEvent<HTMLDivElement>): void => {
    event.preventDefault();
    setDragOver(false);
    pick(event.dataTransfer.files[0]);
  };

  /** Добавить строки «добавим» из разбора — ровно то, что в предпросмотре. */
  const runImport = async (file: File, preview: ImportPreview): Promise<void> => {
    setStep({ kind: 'preview', file, preview, importing: true });
    try {
      const report = await api.importSources(preview.previewId);
      setStep({ kind: 'done', file, report, undone: false, undoing: false });
      onImported(report.added);
      announce(
        `Добавлено ${formatCount(report.added.length, WORDS.source)}, не вошло ${formatCount(report.skipped.length, ROW_WORDS)}`,
      );
    } catch (e) {
      setStep({ kind: 'failed', file, message: errorMessage(e), preview });
    }
  };

  /** Отменить импорт: убрать из списка всё, что он добавил. */
  const undo = async (): Promise<void> => {
    if (step.kind !== 'done') return;
    const { report } = step;
    setStep({ ...step, undoing: true });
    const results = await Promise.allSettled(report.added.map((s) => api.removeSource(s.id)));
    const removed = report.added.filter((_, i) => results[i]?.status === 'fulfilled');
    onUndone(removed.map((s) => s.id));
    setStep({ ...step, undone: removed.length > 0, undoing: false });
    // Кнопка «Отменить импорт» исчезла — фокус на «Готово», чтобы он не потерялся.
    window.setTimeout(() => doneRef.current?.focus(), 0);
    announce(
      removed.length === report.added.length
        ? 'Импорт отменён: добавленные источники убраны из списка'
        : `Убрано ${formatNumber(removed.length)} из ${formatNumber(report.added.length)}: часть источников убрать не удалось`,
    );
  };

  const chooseAnother = (): void => {
    request.current += 1;
    setStep({ kind: 'choose', error: null });
  };

  const footer = (() => {
    switch (step.kind) {
      case 'choose':
        return (
          <DialogClose>
            <Button>Отмена</Button>
          </DialogClose>
        );
      case 'previewing':
      case 'preview': {
        const adds = step.kind === 'preview' ? step.preview.counts.add : 0;
        const importing = step.kind === 'preview' && step.importing;
        return (
          <>
            <Button onClick={chooseAnother} disabled={importing}>
              Другой файл
            </Button>
            <Button
              variant="primary"
              iconStart={<Upload />}
              loading={step.kind === 'previewing' || importing}
              disabled={step.kind === 'preview' && adds === 0}
              onClick={() => {
                if (step.kind === 'preview') void runImport(step.file, step.preview);
              }}
            >
              {step.kind === 'preview' && adds > 0
                ? `Добавить ${formatCount(adds, WORDS.source)}`
                : 'Добавить из файла'}
            </Button>
          </>
        );
      }
      case 'failed':
        return (
          <>
            <Button onClick={chooseAnother}>Другой файл</Button>
            {/* Повтор — с разбора: прежний разбор мог устареть (сервер держит его час) */}
            <Button variant="primary" onClick={() => void runPreview(step.file)}>
              Повторить
            </Button>
          </>
        );
      case 'done':
        return (
          <>
            {!step.undone && step.report.added.length > 0 && (
              <Button iconStart={<Undo2 />} loading={step.undoing} onClick={() => void undo()}>
                Отменить импорт
              </Button>
            )}
            <DialogClose>
              <Button ref={doneRef} variant="primary">
                Готово
              </Button>
            </DialogClose>
          </>
        );
    }
  })();

  return (
    <Dialog
      open
      onOpenChange={onOpenChange}
      size="lg"
      title="Загрузить список из Excel"
      description="Таблица, где в одной колонке — ссылки на группы и каналы. Остальные колонки не мешают. Текущий список не изменится: новые источники добавятся к нему."
      footer={footer}
    >
      <div className={styles.dialogStack}>
        {step.kind === 'choose' && (
          <>
            <div
              className={cx(styles.dropZone, dragOver && styles.dropZoneActive)}
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={onDrop}
            >
              <FileSpreadsheet aria-hidden="true" className={styles.dropIcon} />
              <p className={styles.dropTitle}>Перетащите файл сюда или выберите его</p>
              <p className={styles.muted}>Excel (.xlsx, .xls) или CSV, до 1000 строк</p>
              <div className={styles.dropActions}>
                <Button
                  variant="primary"
                  iconStart={<Upload />}
                  onClick={() => fileInput.current?.click()}
                >
                  Выбрать файл
                </Button>
                {IS_MOCKUP && (
                  <Button iconStart={<FileSpreadsheet />} onClick={takeDemoFile}>
                    Взять демо-файл
                  </Button>
                )}
              </div>
              <input
                ref={fileInput}
                type="file"
                accept={ACCEPT}
                hidden
                onChange={(e) => {
                  pick(e.target.files?.[0]);
                  e.target.value = '';
                }}
              />
            </div>
            {step.error && (
              <p className={styles.errorText} role="alert">
                {step.error}
              </p>
            )}
            <Rules />
          </>
        )}

        {(step.kind === 'previewing' || step.kind === 'preview' || step.kind === 'failed') && (
          <p className={styles.fileLine}>
            <FileSpreadsheet aria-hidden="true" />
            <b>{step.file.name}</b>
            <span className={styles.muted}>· {fileSize(step.file.size)}</span>
          </p>
        )}

        {step.kind === 'previewing' && (
          <div role="status">
            <span className="sr-only">Разбираем файл «{step.file.name}»</span>
            <SkeletonText lines={4} />
          </div>
        )}

        {step.kind === 'preview' && <PreviewView preview={step.preview} />}

        {step.kind === 'failed' && (
          <ErrorState
            compact
            title={step.preview ? 'Не удалось добавить источники' : 'Не удалось разобрать файл'}
            description={step.message}
          />
        )}

        {step.kind === 'done' && <Report step={step} />}
      </div>
    </Dialog>
  );
}

function Rules() {
  return (
    <div className={styles.rules}>
      <p className={styles.legendTitle}>Что сделаем с файлом</p>
      <ul className={styles.bullets}>
        <li>Найдём колонку со ссылками: одна строка — одна группа или канал.</li>
        <li>Подойдут любые ссылки VK, OK и MAX: vk.com, vk.ru, m.vk.com, ok.ru, max.ru.</li>
        <li>Заголовок и пустые строки пропустим.</li>
        <li>Закрытые группы и ссылки не на VK, OK или MAX не добавим — скажем почему.</li>
        <li>Источники, которые уже есть в списке, не тронем.</li>
        <li>Сначала покажем, что будет с каждой строкой, — добавим только после «Добавить».</li>
      </ul>
    </div>
  );
}

const ROLE_TEXT: Record<ImportPreview['columns'][number]['role'], string> = {
  url: 'ссылки',
  name: 'названия',
  ignored: 'не используем',
};

function rowsOf<K extends ImportRow['outcome']['kind']>(
  preview: ImportPreview,
  kind: K,
): (ImportRow & { outcome: Extract<ImportRow['outcome'], { kind: K }> })[] {
  return preview.rows.filter(
    (r): r is ImportRow & { outcome: Extract<ImportRow['outcome'], { kind: K }> } =>
      r.outcome.kind === kind,
  );
}

/** Предпросмотр: что будет с каждой строкой файла. Ничего ещё не добавлено. */
function PreviewView({ preview }: { preview: ImportPreview }) {
  const adds = rowsOf(preview, 'add');
  const dups = rowsOf(preview, 'duplicate');
  const skips = rowsOf(preview, 'skip');
  const { counts } = preview;
  return (
    <div className={styles.dialogStack} role="status">
      <div className={styles.examples}>
        <StatusBadge tone={counts.add > 0 ? 'good' : 'neutral'} icon="check">
          Добавим {formatCount(counts.add, WORDS.source)}
        </StatusBadge>
        {counts.duplicate > 0 && (
          <StatusBadge tone="info" icon="info">
            Уже в списке — {formatNumber(counts.duplicate)}
          </StatusBadge>
        )}
        {counts.skip > 0 && (
          <StatusBadge tone="warning" icon="warning">
            Пропустим {formatCount(counts.skip, ROW_WORDS)}
          </StatusBadge>
        )}
      </div>
      <p className={styles.muted}>
        Лист «{preview.sheetName}», {formatCount(preview.totalRows, ROW_WORDS)}
        {preview.headerRow !== null ? `, строка ${preview.headerRow} — заголовок` : ''}
        {counts.empty > 0 ? `, пустых — ${formatNumber(counts.empty)}` : ''}. Колонки:{' '}
        {preview.columns.map((c) => `${c.letter} «${c.title}» — ${ROLE_TEXT[c.role]}`).join('; ')}.
      </p>
      {adds.length > 0 && (
        <section aria-labelledby="import-will-add">
          <h3 id="import-will-add" className={styles.legendTitle}>
            Добавим — {formatNumber(adds.length)}
          </h3>
          <ul className={styles.reportList}>
            {adds.map((r) => (
              <li key={r.row}>
                <span className={styles.rowNum}>строка {r.row}</span>{' '}
                <span className={styles.source}>
                  <PlatformDot platform={r.outcome.source.platform} size="sm" />
                  <span>
                    {r.outcome.source.name}
                    <span className={styles.sourcePlatform}>
                      {' '}
                      · {PLATFORMS[r.outcome.source.platform].short}
                      {r.outcome.source.district ? ` · ${r.outcome.source.district}` : ''}
                    </span>
                  </span>
                </span>
                {r.outcome.note && <span className={styles.muted}> — {r.outcome.note}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}
      {dups.length > 0 && (
        <section aria-labelledby="import-dups">
          <h3 id="import-dups" className={styles.legendTitle}>
            Уже в списке — не тронем
          </h3>
          <ul className={styles.reportList}>
            {dups.map((r) => (
              <li key={r.row}>
                <span className={styles.rowNum}>строка {r.row}</span> {r.outcome.source.name}
              </li>
            ))}
          </ul>
        </section>
      )}
      {skips.length > 0 && (
        <section aria-labelledby="import-skips">
          <h3 id="import-skips" className={styles.legendTitle}>
            Пропустим — {formatCount(skips.length, ROW_WORDS)}
          </h3>
          <ul className={styles.reportList}>
            {skips.map((r) => (
              <li key={r.row}>
                <span className={styles.rowNum}>строка {r.row}</span>{' '}
                <code className={styles.code}>{r.value}</code> — {r.outcome.reason}
              </li>
            ))}
          </ul>
        </section>
      )}
      <p className={styles.muted}>
        Пока ничего не добавлено. После добавления импорт можно отменить одной кнопкой.
      </p>
    </div>
  );
}

function Report({ step }: { step: Extract<Step, { kind: 'done' }> }) {
  const { report, file, undone } = step;
  return (
    <div className={styles.dialogStack} role="status">
      <div>
        {undone ? (
          <StatusBadge tone="neutral" icon="stopped">
            Импорт отменён
          </StatusBadge>
        ) : (
          <StatusBadge tone="good" icon="check">
            Добавлено {formatCount(report.added.length, WORDS.source)}
          </StatusBadge>
        )}
      </div>
      {report.added.length > 0 && (
        <section aria-labelledby="import-added">
          <h3 id="import-added" className={styles.legendTitle}>
            {undone ? 'Были добавлены' : 'Добавлены'} — {formatNumber(report.added.length)}
          </h3>
          <ul className={styles.reportList}>
            {report.added.map((s) => (
              <li key={s.id}>
                <span className={styles.source}>
                  <PlatformDot platform={s.platform} size="sm" />
                  <span>
                    {s.name}
                    <span className={styles.sourcePlatform}>
                      {' '}
                      · {PLATFORMS[s.platform].short}
                      {s.district ? ` · ${s.district}` : ''}
                    </span>
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
      {report.duplicates.length > 0 && (
        <section aria-labelledby="import-duplicates">
          <h3 id="import-duplicates" className={styles.legendTitle}>
            Уже были в списке — {formatNumber(report.duplicates.length)}
          </h3>
          <ul className={styles.reportList}>
            {report.duplicates.map((d) => (
              <li key={`${d.row}-${d.value}`}>
                <span className={styles.rowNum}>строка {d.row}</span> {d.name}
              </li>
            ))}
          </ul>
        </section>
      )}
      {report.skipped.length > 0 && (
        <section aria-labelledby="import-skipped">
          <h3 id="import-skipped" className={styles.legendTitle}>
            Не вошли — {formatCount(report.skipped.length, ROW_WORDS)}
          </h3>
          <ul className={styles.reportList}>
            {report.skipped.map((s) => (
              <li key={`${s.row}-${s.value}`}>
                <span className={styles.rowNum}>строка {s.row}</span>{' '}
                <code className={styles.code}>{s.value}</code> — {s.reason}
              </li>
            ))}
          </ul>
        </section>
      )}
      <p className={styles.muted}>
        Файл «{file.name}».{' '}
        {undone
          ? 'Добавленные из него источники убраны из списка.'
          : 'Источники, которые уже были в списке, не трогали. Заголовок и пустые строки пропустили.'}
      </p>
    </div>
  );
}
