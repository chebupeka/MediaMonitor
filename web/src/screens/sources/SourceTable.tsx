/**
 * Список источников. Как таблица размещений в «Распространении»: на широкой вкладке —
 * таблица, в узкой боковой панели и при увеличении 200 % строки становятся карточками.
 */
import { Pencil, Trash2 } from 'lucide-react';
import type { CSSProperties } from 'react';
import type { Source } from '@/api/types';
import { cx, IconButton, PlatformDot, StatusBadge } from '@/components';
import { formatCompact, formatDate, formatDateTime, TIME_ZONE_LABEL } from '@/lib/format';
import { PLATFORMS, SOURCE_TYPE_LABEL } from '@/lib/labels';
import { checkView, hasProblem, ORIGIN_LABEL, shortUrl } from './model';
import { OutLink } from './fields';
import styles from './sources.module.css';

export interface SourceTableProps {
  sources: readonly Source[];
  /** Только что добавленные — помечаем «новый» */
  fresh: ReadonlySet<string>;
  onEdit: (source: Source) => void;
  onRemove: (source: Source) => void;
}

export function SourceTable({ sources, fresh, onEdit, onRemove }: SourceTableProps) {
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <caption className="sr-only">Ваши источники. Указано {TIME_ZONE_LABEL}.</caption>
        <thead>
          <tr>
            <th scope="col">Источник</th>
            <th scope="col">Тип</th>
            <th scope="col">Город или район</th>
            <th scope="col" className={styles.num}>
              Подписчики
            </th>
            <th scope="col">Состояние</th>
            <th scope="col">
              <span className="sr-only">Действия</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {sources.map((s, i) => {
            const isFresh = fresh.has(s.id);
            const view = checkView(s.check);
            return (
              <tr
                key={s.id}
                className={cx(styles.reveal, isFresh && styles.rowFresh)}
                style={{ '--i': Math.min(i, 10) } as CSSProperties}
              >
                <th scope="row" className={styles.nameCell}>
                  <span className={styles.source}>
                    <PlatformDot platform={s.platform} size="sm" />
                    <span>
                      {s.name}
                      <span className={styles.sourcePlatform}>
                        {' '}
                        · {PLATFORMS[s.platform].short}
                      </span>
                      {isFresh && (
                        <>
                          {' '}
                          <span className={styles.mark}>новый</span>
                        </>
                      )}
                    </span>
                  </span>
                  <span className={styles.subLine}>
                    <OutLink href={s.url}>{shortUrl(s.url)}</OutLink>
                    <span>
                      {ORIGIN_LABEL[s.origin]} {formatDate(s.addedAt)}
                    </span>
                  </span>
                </th>
                <td data-label="Тип">{SOURCE_TYPE_LABEL[s.type]}</td>
                <td data-label="Город или район">
                  {s.district ?? <span className={styles.noData}>не указан</span>}
                </td>
                <td data-label="Подписчики" className={styles.num}>
                  {s.subscribers === null ? (
                    <span className={styles.noData}>нет данных</span>
                  ) : (
                    formatCompact(s.subscribers)
                  )}
                </td>
                <td data-label="Состояние">
                  <span className={styles.stateCell}>
                    <StatusBadge tone={view.tone} icon={view.icon} size="sm">
                      {view.text}
                    </StatusBadge>
                    {hasProblem(s) && (
                      <span className={styles.checkedAt}>
                        проверен {formatDateTime(s.check.checkedAt)}
                      </span>
                    )}
                  </span>
                </td>
                <td className={styles.actionsCell}>
                  <IconButton
                    size="sm"
                    label={`Изменить «${s.name}»`}
                    icon={<Pencil />}
                    onClick={() => onEdit(s)}
                  />
                  <IconButton
                    size="sm"
                    label={`Удалить «${s.name}»`}
                    icon={<Trash2 />}
                    onClick={() => onRemove(s)}
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
