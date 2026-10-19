/**
 * Карточка публикации: пять обязательных полей (ТЗ-Ф34) — площадка и источник,
 * заголовок или начало поста, дата или «дата неизвестна», прямая ссылка, выдержка
 * с подсветкой доказательства (П3). Плюс причина региона (Р4), метод отбора и метка.
 * Тексты постов выводим только как текст (НТ-9).
 */
import { ExternalLink } from 'lucide-react';
import type { ResultItem } from '@/api/types';
import {
  Button,
  Card,
  CardBody,
  CardFooter,
  CardHeader,
  CardMeta,
  Chip,
  PlatformDot,
} from '@/components';
import { formatPublishedAt } from '@/lib/format';
import { excerptSegments } from '@/lib/highlight';
import { METHOD_LABEL, PLATFORMS, RELEVANCE_SHORT, regionReasonText } from '@/lib/labels';
import styles from './search.module.css';

interface ResultCardProps {
  item: ResultItem;
  onToggleExcluded: (item: ResultItem) => void;
}

export function ResultCard({ item, onToggleExcluded }: ResultCardProps) {
  const pub = item.publication;
  const segments = excerptSegments(item);
  const region = regionReasonText(item.regionReason);
  return (
    <Card as="article" tone={item.excluded ? 'excluded' : 'default'} className={styles.card}>
      <CardHeader
        aside={
          <Chip size="sm" tone={item.relevance === 'disputed' ? 'warning' : 'neutral'}>
            {RELEVANCE_SHORT[item.relevance]}
          </Chip>
        }
      >
        <span className={styles.source}>
          <PlatformDot platform={pub.platform} size="sm" />
          <span className={styles.sourceName}>{pub.source.name}</span>
        </span>
      </CardHeader>
      <CardMeta>
        {PLATFORMS[pub.platform].name} · {formatPublishedAt(pub)}
        {region ? ` · ${region}` : ''}
      </CardMeta>
      <CardBody>
        <h3 className={styles.headline}>{pub.headline}</h3>
        {segments.length > 0 ? (
          <p className={styles.excerpt}>
            {segments.map((s, i) =>
              s.mark ? <mark key={i}>{s.text}</mark> : <span key={i}>{s.text}</span>,
            )}
          </p>
        ) : (
          <p className={styles.noText}>
            Текст в посте отсутствует — только заголовок или вложение.
          </p>
        )}
      </CardBody>
      <CardFooter className={styles.cardFooter}>
        <a className={styles.open} href={pub.url} target="_blank" rel="noopener noreferrer">
          Открыть пост
          <ExternalLink aria-hidden="true" />
        </a>
        <span className={styles.method}>{METHOD_LABEL[item.method]}</span>
        <Button size="sm" variant="ghost" onClick={() => onToggleExcluded(item)}>
          {item.excluded ? 'Вернуть' : 'Исключить'}
        </Button>
      </CardFooter>
    </Card>
  );
}
