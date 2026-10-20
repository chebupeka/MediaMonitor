/**
 * Карточка публикации: пять обязательных полей (ТЗ-Ф34) — площадка и источник,
 * заголовок или начало поста, дата или «дата неизвестна», прямая ссылка, выдержка
 * с подсветкой доказательства (П3). Плюс причина региона (Р4), метод отбора и метка;
 * «в вашем списке» (НТ-25) и «новое» после «Повторить» из недавних (П12).
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
import {
  DEMO_POST_NOTE,
  METHOD_LABEL,
  PLATFORMS,
  RELEVANCE_SHORT,
  regionReasonText,
} from '@/lib/labels';
import { AiMark } from '@/screens/ai-check/AiMark';
import styles from './search.module.css';

interface ResultCardProps {
  item: ResultItem;
  onToggleExcluded: (item: ResultItem) => void;
}

export function ResultCard({ item, onToggleExcluded }: ResultCardProps) {
  const pub = item.publication;
  const segments = excerptSegments(item);
  // «в вашем списке» — один раз: причиной региона (режим «Мои источники») или пометкой
  // источника из списка, если он нашёлся в режиме «Везде».
  const region = [
    regionReasonText(item.regionReason),
    pub.source.inMySources && !item.regionReason.inMySources ? 'в вашем списке' : '',
  ]
    .filter(Boolean)
    .join(' · ');
  return (
    <Card
      as="article"
      tone={item.excluded ? 'excluded' : item.isNew ? 'accent' : 'default'}
      className={styles.card}
    >
      <CardHeader
        aside={
          <>
            {item.isNew && (
              <Chip size="sm" tone="info">
                новое
              </Chip>
            )}
            <Chip size="sm" tone={item.relevance === 'disputed' ? 'warning' : 'neutral'}>
              {RELEVANCE_SHORT[item.relevance]}
            </Chip>
          </>
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
        {pub.demo ? (
          // Записанный пример: поста на площадке нет — ссылку не показываем (Р11 п. 3)
          <span className={styles.demoPost}>{DEMO_POST_NOTE}</span>
        ) : (
          <a className={styles.open} href={pub.url} target="_blank" rel="noopener noreferrer">
            Открыть пост
            <ExternalLink aria-hidden="true" />
          </a>
        )}
        <span className={styles.method}>
          {METHOD_LABEL[item.method]}
          {/* Проверка текста на ИИ: метка только у «похоже на ИИ» и «признаки ИИ» */}
          <AiMark check={item.aiCheck} />
        </span>
        <Button size="sm" variant="ghost" onClick={() => onToggleExcluded(item)}>
          {item.excluded ? 'Вернуть' : 'Исключить'}
        </Button>
      </CardFooter>
    </Card>
  );
}
