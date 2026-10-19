/**
 * Небольшие локальные элементы экрана «Источники»: поле типа, поле района с подсказками
 * и внешняя ссылка. Общих аналогов в src/components нет; понадобятся другим — через лида.
 */
import { ExternalLink } from 'lucide-react';
import type { ReactNode } from 'react';
import type { SourceType } from '@/api/types';
import { TextField, ToggleGroup } from '@/components';
import { SOURCE_TYPE_LABEL } from '@/lib/labels';
import { SOURCE_TYPE_ORDER } from './model';
import styles from './sources.module.css';

const TYPE_ITEMS = SOURCE_TYPE_ORDER.map((t) => ({ value: t, label: SOURCE_TYPE_LABEL[t] }));

/** Тип источника (П13) — один из шести, переключателем. */
export function TypeField({
  value,
  onChange,
}: {
  value: SourceType;
  onChange: (value: SourceType) => void;
}) {
  return (
    <div className={styles.field}>
      <span className={styles.fieldLabel} aria-hidden="true">
        Тип
      </span>
      <ToggleGroup
        label="Тип источника"
        items={TYPE_ITEMS}
        value={value}
        onValueChange={onChange}
        size="sm"
      />
    </div>
  );
}

/** Город или район края; подсказки — настоящие города и районы и те, что уже есть в списке. */
export function DistrictField({
  id,
  value,
  onChange,
  districts,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  districts: readonly string[];
}) {
  return (
    <>
      <TextField
        label="Город или район"
        value={value}
        list={`${id}-list`}
        placeholder="не указан"
        autoComplete="off"
        hint="«весь край» — если источник пишет обо всём крае"
        onChange={(e) => onChange(e.target.value)}
      />
      <datalist id={`${id}-list`}>
        {districts.map((d) => (
          <option key={d} value={d} />
        ))}
      </datalist>
    </>
  );
}

/** Внешняя ссылка: открывается в новой вкладке — это видно и слышно. */
export function OutLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className={styles.outLink}>
      <span className={styles.outText}>{children}</span>
      <ExternalLink aria-hidden="true" />
      <span className="sr-only"> (откроется в новой вкладке)</span>
    </a>
  );
}
