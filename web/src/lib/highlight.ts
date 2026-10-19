/**
 * Подсветка доказательства в выдержке (П3). Возвращает куски текста с пометкой,
 * какие подсвечивать. Выводите их только как текст (НТ-9):
 *
 *   {segments.map((s, i) => s.mark ? <mark key={i}>{s.text}</mark> : <span key={i}>{s.text}</span>)}
 */
import type { ResultItem, TextRange } from '@/api/types';

export interface TextSegment {
  text: string;
  mark: boolean;
}

/** Разрезать `text` на куски по отрезкам подсветки внутри окна `window`. */
export function segmentText(
  text: string,
  ranges: readonly TextRange[],
  window?: TextRange,
): TextSegment[] {
  const from = window?.start ?? 0;
  const to = window?.end ?? text.length;
  const clipped = ranges
    .map((r) => ({ start: Math.max(r.start, from), end: Math.min(r.end, to) }))
    .filter((r) => r.start < r.end)
    .sort((a, b) => a.start - b.start);

  const segments: TextSegment[] = [];
  let cursor = from;
  for (const r of clipped) {
    if (r.end <= cursor) continue;
    const start = Math.max(r.start, cursor);
    if (start > cursor) segments.push({ text: text.slice(cursor, start), mark: false });
    segments.push({ text: text.slice(start, r.end), mark: true });
    cursor = r.end;
  }
  if (cursor < to) segments.push({ text: text.slice(cursor, to), mark: false });
  return segments;
}

/** Куски выдержки записи с подсветкой доказательства. Пусто — у поста нет текста. */
export function excerptSegments(
  item: Pick<ResultItem, 'publication' | 'excerpt' | 'evidence'>,
): TextSegment[] {
  const { publication, excerpt, evidence } = item;
  if (!publication.text || !excerpt) return [];
  return segmentText(publication.text, evidence?.ranges ?? [], {
    start: excerpt.start,
    end: excerpt.end,
  });
}
