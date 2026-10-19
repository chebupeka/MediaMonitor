/**
 * Сборка демо-записей из компактного описания. Гарантирует правила контракта:
 * выдержка — подстрока текста поста, номер предложения-доказательства указывает
 * на реальное предложение, отрезки подсветки лежат внутри текста.
 */
import type {
  Citation,
  Evidence,
  Excerpt,
  PlacementType,
  Publication,
  Relevance,
  ResultItem,
  SelectionMethod,
  Sentence,
  TextRange,
} from '../types';
import { at } from './clock';
import { alternatePostUrls, postUrl, seedById, toSourceRef } from './sources';

export interface PostSpec {
  /** Номер поста у владельца */
  n: string;
  /** id источника из sources.ts */
  src: string;
  /** Время публикации `YYYY-MM-DD HH:MM` по Красноярску; `null` — дата неизвестна */
  at: string | null;
  /** Текст: предложения одного абзаца или абзацы из предложений; `null` — текста нет */
  text: string[] | string[][] | null;
  /** Заголовок, если площадка его отдаёт (видео, статья) */
  title?: string;
  /** Номер предложения-доказательства (по умолчанию 0) */
  ev?: number;
  /** Фразы для подсветки (должны входить в текст); по умолчанию — всё предложение */
  marks?: string[];
  basis?: Evidence['basis'];
  evNote?: string;
  rel: Relevance;
  m: SelectionMethod;
  methodNote?: string;
  /** Упомянутые места края (именительный падеж) */
  places?: string[];
  views?: number | null;
  reactions?: number | null;
  edited?: boolean;
  /** Репост: id источника оригинала и номер его поста */
  repostOf?: { src: string; n: string };
  media?: boolean;
  /** Пост найден по нескольким адресам (склейка, НТ-13) */
  merged?: boolean;
  /** Грани темы, к которым относится пост (для правки «как система поняла») */
  facets?: string[];
  placement?: PlacementType;
  original?: boolean;
  citation?: Citation;
  group?: string;
  /**
   * Заданная оценка проверки на ИИ (0..1) — только имитация: чтобы в демо были все уровни.
   * Привязана к ТЕКСТУ поста (fake/ai.ts): тот же текст где угодно даёт ту же оценку.
   */
  ai?: number;
}

/** Запись подборки + служебные сведения имитации. */
export interface DemoItem {
  item: ResultItem;
  facets: string[];
  /** Момент публикации, мс; `null` — без даты */
  publishedMs: number | null;
}

interface BuiltText {
  text: string;
  sentences: Sentence[];
}

export function buildText(spec: PostSpec['text']): BuiltText | null {
  if (!spec || spec.length === 0) return null;
  const paragraphs: string[][] = Array.isArray(spec[0]) ? (spec as string[][]) : [spec as string[]];
  let text = '';
  const sentences: Sentence[] = [];
  paragraphs.forEach((paragraph, pIndex) => {
    if (pIndex > 0) text += '\n\n';
    paragraph.forEach((sentence, sIndex) => {
      if (sIndex > 0) text += ' ';
      const start = text.length;
      text += sentence;
      sentences.push({ index: sentences.length, start, end: text.length });
    });
  });
  return { text, sentences };
}

function truncate(value: string, max: number): string {
  if (value.length <= max) return value;
  const cut = value.slice(0, max);
  const space = cut.lastIndexOf(' ');
  return `${cut.slice(0, space > max * 0.6 ? space : max).replace(/[,.;:—\s-]+$/u, '')}…`;
}

function sentenceAt(sentences: Sentence[], offset: number): Sentence {
  return (
    sentences.find((s) => offset >= s.start && offset < s.end) ??
    sentences[sentences.length - 1] ?? { index: 0, start: 0, end: 0 }
  );
}

const EXCERPT_MAX = 280;

function buildExcerpt(built: BuiltText, from: Sentence): Excerpt {
  const start = from.start;
  let end = from.end;
  for (let j = from.index + 1; j < built.sentences.length && j <= from.index + 2; j += 1) {
    const next = built.sentences[j];
    if (!next || next.end - start > EXCERPT_MAX) break;
    end = next.end;
  }
  return {
    start,
    end,
    text: built.text.slice(start, end),
    cutStart: start > 0,
    cutEnd: end < built.text.length,
  };
}

/** Заданные оценки проверки на ИИ из описаний постов: пары «полный текст поста — оценка». */
export function aiScoresOf(specs: readonly PostSpec[]): [string, number][] {
  return specs.flatMap((spec): [string, number][] => {
    if (spec.ai === undefined) return [];
    const built = buildText(spec.text);
    return built ? [[built.text, spec.ai]] : [];
  });
}

let arrivalSeed = 0;

/** Собрать запись подборки по описанию. */
export function buildItem(spec: PostSpec): DemoItem {
  const seed = seedById(spec.src);
  const built = buildText(spec.text);
  const publishedAt = spec.at ? at(spec.at) : null;
  const firstSentence = built?.sentences[0];
  const headlineSource =
    spec.title ??
    (built && firstSentence
      ? built.text.slice(firstSentence.start, firstSentence.end)
      : 'Пост без текста');

  let evidence: Evidence | null = null;
  let excerpt: Excerpt | null = null;
  if (built) {
    let ranges: TextRange[];
    let evSentence: Sentence;
    if (spec.marks && spec.marks.length > 0) {
      ranges = spec.marks.map((phrase) => {
        const start = built.text.indexOf(phrase);
        if (start < 0)
          throw new Error(`Фраза подсветки не найдена в посте ${spec.src}/${spec.n}: «${phrase}»`);
        return { start, end: start + phrase.length };
      });
      ranges.sort((a, b) => a.start - b.start);
      evSentence = sentenceAt(built.sentences, ranges[0]?.start ?? 0);
    } else {
      const index = Math.min(spec.ev ?? 0, built.sentences.length - 1);
      evSentence = built.sentences[index] ?? built.sentences[0] ?? { index: 0, start: 0, end: 0 };
      ranges = [{ start: evSentence.start, end: evSentence.end }];
    }
    evidence = {
      sentenceIndex: evSentence.index,
      ranges,
      basis: spec.basis ?? (spec.m === 'ai-confirmed' ? 'ai' : 'semantic'),
      note: spec.evNote ?? null,
    };
    excerpt = buildExcerpt(built, evSentence);
  }

  const repostSeed = spec.repostOf ? seedById(spec.repostOf.src) : null;
  const views =
    spec.views !== undefined
      ? spec.views
      : seed.platform === 'ok'
        ? null
        : Math.round((seed.subscribers ?? 10_000) * 0.07);
  const reactions =
    spec.reactions !== undefined
      ? spec.reactions
      : Math.round((seed.subscribers ?? 10_000) * 0.004);

  const ownerKey = seed.platform === 'vk' ? `-${seed.ownerId}` : seed.ownerId;
  const id = `${seed.platform}:${ownerKey}_${spec.n}`;

  const publication: Publication = {
    id,
    key: { platform: seed.platform, ownerId: ownerKey, postId: spec.n },
    platform: seed.platform,
    source: toSourceRef(seed, seed.mine),
    url: postUrl(seed, spec.n),
    mergedUrls: spec.merged ? alternatePostUrls(seed, spec.n) : [],
    title: spec.title ?? null,
    headline: truncate(headlineSource, 120),
    headlineFrom: spec.title ? 'title' : 'text',
    text: built?.text ?? null,
    sentences: built?.sentences ?? [],
    publishedAt,
    timeReliability:
      publishedAt === null ? 'unknown' : seed.platform === 'max' ? 'approximate' : 'exact',
    edited: spec.edited ?? false,
    repostOf:
      repostSeed && spec.repostOf
        ? { sourceName: repostSeed.name, url: postUrl(repostSeed, spec.repostOf.n) }
        : null,
    hasMedia: spec.media ?? false,
    views,
    reactions,
    // Время получения проставляет поиск (НТ-19); здесь — заглушка.
    fetchedAt: publishedAt ?? at('2026-10-19 14:32'),
    linkCheck: { state: 'not-checked', checkedAt: null },
  };

  arrivalSeed += 1;
  const item: ResultItem = {
    id,
    publication,
    relevance: spec.rel,
    method: spec.m,
    methodNote: spec.methodNote ?? null,
    regionReason: { regionalSource: seed.regional, inMySources: false, places: spec.places ?? [] },
    excerpt,
    evidence,
    placementType: spec.placement ?? null,
    isOriginal: spec.original ?? false,
    citation: spec.citation ?? null,
    groupId: spec.group ?? null,
    excluded: false,
    isNew: false,
    arrival: arrivalSeed,
  };

  return {
    item,
    facets: spec.facets ?? [],
    publishedMs: publishedAt ? Date.parse(publishedAt) : null,
  };
}

/**
 * Проверка набора на правила контракта. Вызывается в режиме разработки;
 * возвращает список нарушений (пусто — всё в порядке).
 */
export function validateItems(items: readonly ResultItem[]): string[] {
  const problems: string[] = [];
  const ids = new Set<string>();
  for (const item of items) {
    const { publication: p } = item;
    if (ids.has(item.id)) problems.push(`${item.id}: повтор id (одна запись на пост, ТЗ-Ф30)`);
    ids.add(item.id);
    if (
      !item.regionReason.regionalSource &&
      !item.regionReason.inMySources &&
      item.regionReason.places.length === 0
    ) {
      problems.push(`${item.id}: нет причины региона (Р4)`);
    }
    if (p.text === null) {
      if (item.excerpt || item.evidence)
        problems.push(`${item.id}: у поста без текста есть выдержка`);
      continue;
    }
    if (!item.excerpt || p.text.slice(item.excerpt.start, item.excerpt.end) !== item.excerpt.text) {
      problems.push(`${item.id}: выдержка не подстрока текста`);
    }
    if (item.evidence) {
      const s = p.sentences[item.evidence.sentenceIndex];
      if (!s) problems.push(`${item.id}: доказательство указывает на несуществующее предложение`);
      for (const r of item.evidence.ranges) {
        if (r.start < 0 || r.end > p.text.length || r.start >= r.end) {
          problems.push(`${item.id}: отрезок подсветки вне текста`);
        }
      }
    }
    for (const place of item.regionReason.places) {
      // Сравниваем по основе первого слова: «Канский район» ↔ «в Канском районе».
      const word = place.split(' ')[0] ?? place;
      const stem = word.slice(0, Math.max(4, Math.min(6, word.length - 2))).toLowerCase();
      const hay = `${p.title ?? ''} ${p.text}`.toLowerCase();
      if (!hay.includes(stem)) problems.push(`${item.id}: место «${place}» не найдено в тексте`);
    }
  }
  return problems;
}
