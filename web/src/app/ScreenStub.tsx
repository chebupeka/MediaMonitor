/**
 * Плашка заготовки экрана: что здесь будет и кто делает. Исполнитель удаляет её,
 * когда собирает экран.
 */
import { Hammer } from 'lucide-react';
import type { ReactNode } from 'react';
import { Card } from '@/components';
import styles from './ScreenStub.module.css';

export interface ScreenStubProps {
  /** Исполнитель из брифа: «Э-Поиск», «Э-Источники»… */
  owner: string;
  /** Папка исполнителя */
  folder: string;
  /** Что будет на экране — по брифу */
  items: string[];
  /** Ссылки на требования */
  refs: string;
  children?: ReactNode;
}

export function ScreenStub({ owner, folder, items, refs, children }: ScreenStubProps) {
  return (
    <Card as="section" tone="muted" className={styles.stub} aria-label="Заготовка экрана">
      <p className={styles.head}>
        <Hammer aria-hidden="true" className={styles.icon} />
        <span>
          <strong>Заготовка экрана.</strong> Сюда придёт исполнитель «{owner}» — папка{' '}
          <code>{folder}</code>.
        </span>
      </p>
      <ul className={styles.items}>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
      <p className={styles.refs}>Требования: {refs}</p>
      {children && <div className={styles.demo}>{children}</div>}
    </Card>
  );
}
