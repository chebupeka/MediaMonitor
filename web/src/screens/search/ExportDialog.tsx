/**
 * Выгрузка XLSX (НТ-11, НТ-20): предпросмотр — лист «Сводка» и первые строки
 * «Публикаций», — и сам файл. Файл совпадает с тем, что на экране (ТЗ-Ф38): исключённые
 * записи в него не попадают, ссылки на посты кликабельные. Имя — тема, дата и время
 * поиска, чтобы выгрузки в «Загрузках» не путались.
 */
import { Download } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { api, errorMessage, useAsync } from '@/api';
import { Button, Dialog, ErrorState, SkeletonText, useAnnounce } from '@/components';
import { DotsScene } from '@/dots';
import { saveFile } from '@/lib/download';
import styles from './search.module.css';

interface ExportDialogProps {
  searchId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ExportDialog({ searchId, open, onOpenChange }: ExportDialogProps) {
  const announce = useAnnounce();
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    if (open) setResult(null);
  }, [open]);

  const download = async () => {
    setBusy(true);
    setResult(null);
    try {
      const { file, fileName } = await api.getExportFile(searchId);
      saveFile(file, fileName);
      setResult({ ok: true, text: `Скачан ${fileName}` });
      announce(`Файл скачан: ${fileName}`);
    } catch (error) {
      setResult({ ok: false, text: errorMessage(error) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Файл готов"
      description="Проверьте сводку и первые строки — в файле та же подборка, что на экране."
      size="lg"
      footer={
        <>
          {result && (
            <p
              className={result.ok ? styles.exportDone : styles.exportFailed}
              role={result.ok ? 'status' : 'alert'}
            >
              {result.text}
            </p>
          )}
          <Button
            variant="primary"
            iconStart={<Download />}
            loading={busy}
            onClick={() => void download()}
          >
            Скачать файл
          </Button>
        </>
      }
    >
      {open && <ExportPreviewBody searchId={searchId} />}
    </Dialog>
  );
}

function ExportPreviewBody({ searchId }: { searchId: string }) {
  const preview = useAsync(useCallback(() => api.getExportPreview(searchId), [searchId]));
  if (preview.status === 'loading' && !preview.data) return <SkeletonText lines={5} />;
  if (preview.status === 'error' || !preview.data)
    return (
      <ErrorState
        compact
        title="Не удалось собрать предпросмотр"
        description={preview.error?.message}
        onRetry={preview.reload}
      />
    );
  const { fileName, rowCount, rule, summary, publications, timeZoneNote } = preview.data;
  return (
    <div className={styles.export}>
      {/* Словарь форм: «выгрузка — точки складываются в сетку таблицы» */}
      <DotsScene form="export" intensity="calm" height={130} />
      <p className={styles.exportFile}>
        <b>{fileName}</b> · {rowCount} {rowCount === 1 ? 'запись' : 'записей'}
      </p>
      <p className={styles.exportRule}>{rule}</p>
      <h3 className={styles.exportSheet}>{summary.name}</h3>
      <dl className={styles.summary}>
        {summary.entries.map((e) => (
          <div key={e.label} className={styles.summaryRow}>
            <dt>{e.label}</dt>
            <dd>{e.value}</dd>
          </div>
        ))}
      </dl>
      <h3 className={styles.exportSheet}>
        {publications.name} · первые {publications.rows.length} из {publications.totalRows}
      </h3>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              {publications.columns.map((c) => (
                <th key={c.id} scope="col">
                  {c.title}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {publications.rows.map((row, r) => (
              <tr key={r}>
                {row.map((cell, c) => (
                  <td key={c}>{cell ?? '—'}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className={styles.exportRule}>{timeZoneNote}</p>
    </div>
  );
}
