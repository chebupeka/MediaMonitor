/**
 * Предпросмотр XLSX (НТ-11, НТ-20): лист «Сводка» и первые строки «Публикаций».
 * Файл совпадает с тем, что на экране (ТЗ-Ф38). В мокапе сам файл не скачивается.
 */
import { useCallback } from 'react';
import { api, useAsync } from '@/api';
import { Dialog, ErrorState, SkeletonText } from '@/components';
import { DotsScene } from '@/dots';
import styles from './search.module.css';

interface ExportDialogProps {
  searchId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ExportDialog({ searchId, open, onOpenChange }: ExportDialogProps) {
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Файл готов"
      description="Так будет выглядеть выгрузка. В мокапе файл не скачивается."
      size="lg"
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
