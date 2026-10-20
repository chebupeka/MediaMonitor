/**
 * Проверка одинаковости результата проверки на ИИ — запускается `npm run check:ai`
 * (scripts/check-ai.mjs грузит этот модуль через Vite в Node). В интерфейс не входит.
 *
 * Что проверяем:
 * 1. тест-векторы нормализации: нормальная форма, число слов, SHA-256 (и сверка нашего
 *    SHA-256 с crypto.subtle на всех демо-текстах);
 * 2. пороги уровней;
 * 3. тот же текст с другими пробелами, переносами, неразрывными пробелами, невидимыми
 *    символами и в разложенной форме Unicode даёт тот же textHash, число слов, оценку и уровень;
 * 4. сквозная проверка через имитацию API: метка записи в подборке = отдельная проверка того же
 *    текста (в искажённом виде) = метка размещения в «Распространении»; счётчики сходятся;
 * 5. в демо есть все уровни; сбой модели даёт `unavailable` и не попадает в кэш;
 * 6. фоновая проверка, как на сервере: запись приходит без `aiCheck`, потом тем же id с оценкой;
 *    слияние интерфейса (`mergeItems`) обновляет карточку на месте — без дублей, без сдвига,
 *    `arrival` прежний; к итогу у всех записей с текстом оценка есть.
 */
import type { MonitorApi } from '../client';
import { mergeItems } from '../hooks';
import type { AiCheck, ResultItem, SearchEvent, SearchRequest, Selection } from '../types';
import { AI_THRESHOLDS, aiLevelForScore, aiTextKey } from '@/lib/ai-check';
import {
  AI_MIN_WORDS,
  AI_NORMALIZE_VECTORS,
  countAiWords,
  normalizeAiText,
} from '@/lib/ai-normalize';
import { sha256Hex } from '@/lib/sha256';
import { demoAiCheck } from './ai';
import { buildBdd } from './datasets/bdd';
import { buildEvent } from './datasets/event';
import { buildLarge } from './datasets/large';
import { RELEASE_AI_SAMPLES, RELEASE_SOURCE_TEXT, buildRelease } from './datasets/release';
import { DEMO_AI_TEXTS, createFakeApi } from './index';
import { presetPeriod } from './query';

const ch = (code: number): string => String.fromCharCode(code);
const NBSP = ch(0x00a0);
const NNBSP = ch(0x202f);
const EM_SPACE = ch(0x2003);
const ZWSP = ch(0x200b);
const ZWNJ = ch(0x200c);
const ZWJ = ch(0x200d);
const BOM = ch(0xfeff);
const SHY = ch(0x00ad);

/** Искажения, которые не должны менять результат. */
const VARIANTS: { name: string; apply: (text: string) => string }[] = [
  { name: 'двойные пробелы', apply: (t) => t.replace(/ /gu, '  ') },
  { name: 'переносы строк вместо пробелов', apply: (t) => t.replace(/ /gu, '\n') },
  {
    name: 'Windows-переносы и табуляция',
    apply: (t) => `\r\n\t${t.replace(/ /gu, ' \r\n\t')}\t\r\n`,
  },
  { name: 'неразрывные пробелы', apply: (t) => t.replace(/ /gu, NBSP) },
  {
    name: 'смесь пробелов: узкий неразрывный, em-пробел',
    apply: (t) =>
      t
        .split(' ')
        .map((w, i) => (i === 0 ? w : (i % 3 === 0 ? NNBSP : i % 3 === 1 ? EM_SPACE : ' ') + w))
        .join(''),
  },
  {
    name: 'невидимые символы внутри слов и BOM по краям',
    apply: (t) =>
      BOM +
      t
        .split(' ')
        .map((w, i) =>
          w.length > 3 ? w.slice(0, 2) + [ZWSP, SHY, ZWJ, ZWNJ][i % 4] + w.slice(2) : w,
        )
        .join(' ') +
      ZWSP,
  },
  { name: 'разложенная форма Unicode (NFD)', apply: (t) => t.normalize('NFD') },
  { name: 'пробелы по краям', apply: (t) => `   ${t}  \n\n` },
];

function sameResult(a: AiCheck, b: AiCheck): boolean {
  return (
    a.textHash === b.textHash &&
    a.level === b.level &&
    a.score === b.score &&
    a.words === b.words &&
    a.model === b.model
  );
}

const describe = (c: AiCheck | undefined): string =>
  c
    ? `${c.level} score=${String(c.score)} words=${c.words} hash=${c.textHash.slice(0, 12)}`
    : 'нет';

function allDemoTexts(): string[] {
  const sets = [buildBdd(), buildRelease(), buildEvent('all'), buildLarge()];
  const texts = sets.flatMap((set) =>
    [...set.items, ...set.optional.flatMap((o) => o.items), ...set.spare]
      .map((d) => d.item.publication.text)
      .filter((t): t is string => t !== null),
  );
  return [...new Set([...texts, ...RELEASE_AI_SAMPLES.map((s) => s.text), RELEASE_SOURCE_TEXT])];
}

async function subtleHex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0')).join('');
}

async function finishedSelection(
  api: ReturnType<typeof createFakeApi>,
  request: SearchRequest,
): Promise<Selection> {
  for await (const event of api.startSearch(request)) {
    if (event.type === 'finished' || event.type === 'stopped') return event.selection;
    if (event.type === 'failed') throw new Error(`поиск не удался: ${event.error.message}`);
  }
  throw new Error('поток поиска закончился без итога');
}

/**
 * Поток поиска с фоновой проверкой на ИИ — как его видит интерфейс. Годится и для имитации,
 * и для настоящего сервера (HTTP-клиент): запись приходит без `aiCheck`, потом тем же id с
 * оценкой; `mergeItems` (hooks.ts) обновляет карточку на месте — без дублей и сдвигов,
 * `arrival` прежний, счётчик «Похоже на ИИ» совпадает с метками; к итогу оценки есть у всех.
 */
export async function verifyAiStream(
  api: Pick<MonitorApi, 'startSearch'>,
  request: SearchRequest,
): Promise<{ failures: string[]; checks: number; line: string }> {
  const failures: string[] = [];
  let checks = 0;
  const expect = (ok: boolean, message: string) => {
    checks += 1;
    if (!ok) failures.push(message);
  };
  const events: SearchEvent[] = [];
  for await (const event of api.startSearch(request)) {
    events.push(event);
    if (event.type === 'finished' || event.type === 'stopped' || event.type === 'failed') break;
  }
  const final = events.find((e) => e.type === 'finished');
  expect(final !== undefined, `поток: нет события finished (${events.at(-1)?.type ?? 'пусто'})`);
  let shown: ResultItem[] = [];
  const firstOrder: string[] = [];
  const firstArrival = new Map<string, number>();
  const firstWithout = new Set<string>();
  let updates = 0;
  let lateChecks = 0;
  for (const event of events) {
    if (event.type !== 'items') continue;
    for (const item of event.items) {
      if (!firstArrival.has(item.id)) {
        firstArrival.set(item.id, item.arrival);
        firstOrder.push(item.id);
        if (item.aiCheck === undefined && item.publication.text !== null) firstWithout.add(item.id);
      } else {
        updates += 1;
        if (firstWithout.has(item.id) && item.aiCheck !== undefined) lateChecks += 1;
      }
    }
    shown = mergeItems(shown, event.items);
    const ids = shown.map((i) => i.id);
    expect(new Set(ids).size === ids.length, 'поток: запись задвоилась после повторного items');
    expect(
      ids.join('|') === firstOrder.join('|'),
      'поток: повторный items сдвинул порядок карточек',
    );
    const likely = shown.filter((i) => !i.excluded && i.aiCheck?.level === 'likely-ai').length;
    const signs = shown.filter((i) => !i.excluded && i.aiCheck?.level === 'signs').length;
    expect(
      event.counts.aiLikely === likely && event.counts.aiSigns === signs,
      `поток: counts ${event.counts.aiLikely}/${event.counts.aiSigns} ≠ меткам на карточках ${likely}/${signs}`,
    );
  }
  expect(firstWithout.size > 0, 'поток: ни одна запись не пришла без оценки (фона нет)');
  expect(updates > 0 && lateChecks > 0, 'поток: оценки не пришли повторным событием items');
  for (const item of shown) {
    expect(
      item.arrival === firstArrival.get(item.id),
      `поток: у ${item.id} сменился arrival — карточка посчиталась бы новой`,
    );
  }
  if (final?.type === 'finished') {
    for (const item of final.selection.items) {
      expect(
        (item.publication.text === null) === (item.aiCheck === undefined),
        `итог: у ${item.id} нет оценки на ИИ`,
      );
    }
  }
  const levels = new Map<string, number>();
  for (const item of shown) {
    const level = item.aiCheck?.level ?? 'нет';
    levels.set(level, (levels.get(level) ?? 0) + 1);
  }
  return {
    failures,
    checks,
    line:
      `Поток «${request.text.slice(0, 30)}…»: записей ${shown.length}, без оценки пришло ` +
      `${firstWithout.size}, повторных записей ${updates}, оценок пришло позже ${lateChecks}; ` +
      `уровни: ${[...levels.entries()].map(([l, n]) => `${l} ${n}`).join(', ')}`,
  };
}

export interface SelfTestReport {
  failures: string[];
  lines: string[];
}

export async function runAiSelfTest(): Promise<SelfTestReport> {
  const failures: string[] = [];
  const lines: string[] = [];
  const fail = (message: string) => failures.push(message);
  let checks = 0;
  const expect = (ok: boolean, message: string) => {
    checks += 1;
    if (!ok) fail(message);
  };

  // 1. Тест-векторы нормализации
  for (const v of AI_NORMALIZE_VECTORS) {
    const normalized = normalizeAiText(v.input);
    expect(normalized === v.normalized, `вектор «${v.note}»: ${JSON.stringify(normalized)}`);
    expect(
      countAiWords(normalized) === v.words,
      `вектор «${v.note}»: слов ${countAiWords(normalized)}`,
    );
    expect(sha256Hex(normalized) === v.sha256, `вектор «${v.note}»: SHA-256 не совпал`);
    expect(
      (await subtleHex(normalized)) === v.sha256,
      `вектор «${v.note}»: crypto.subtle ≠ вектор`,
    );
  }
  lines.push(`Тест-векторы нормализации: ${AI_NORMALIZE_VECTORS.length}`);

  // 2. Пороги
  expect(aiLevelForScore(AI_THRESHOLDS.likelyAi) === 'likely-ai', 'порог likely-ai включительно');
  expect(aiLevelForScore(AI_THRESHOLDS.likelyAi - 0.0001) === 'signs', 'чуть ниже 0,85 — signs');
  expect(aiLevelForScore(AI_THRESHOLDS.signs) === 'signs', 'порог signs включительно');
  expect(aiLevelForScore(AI_THRESHOLDS.signs - 0.0001) === 'unlikely', 'чуть ниже 0,60 — unlikely');

  // 6. Фоновая проверка в потоке — до того, как остальные проверки наполнят кэш
  {
    const stream = await verifyAiStream(createFakeApi(), {
      text: RELEASE_SOURCE_TEXT,
      period: presetPeriod('7d'),
      mode: 'everywhere',
    });
    for (const failure of stream.failures) expect(false, failure);
    checks += stream.checks;
    lines.push(stream.line);
  }

  // 3. Искажения на всех демо-текстах
  const texts = allDemoTexts();
  const levels = new Map<string, number>();
  for (const text of texts) {
    const base = demoAiCheck(text);
    levels.set(base.level, (levels.get(base.level) ?? 0) + 1);
    const key = aiTextKey(text);
    expect(
      base.textHash === (await subtleHex(key.normalized)),
      `SHA-256 ≠ crypto.subtle: ${text.slice(0, 40)}`,
    );
    expect(
      (base.level === 'too-short') === key.words < AI_MIN_WORDS,
      `too-short не по порогу 40 слов: ${describe(base)}`,
    );
    for (const variant of VARIANTS) {
      const other = demoAiCheck(variant.apply(text));
      expect(
        sameResult(base, other) && other.checkedAt === base.checkedAt,
        `«${variant.name}» меняет результат: ${describe(base)} → ${describe(other)} (${text.slice(0, 40)}…)`,
      );
    }
  }
  lines.push(
    `Демо-текстов: ${texts.length}, искажений на текст: ${VARIANTS.length}. Уровни: ` +
      [...levels.entries()].map(([level, n]) => `${level} ${n}`).join(', '),
  );
  for (const level of ['likely-ai', 'signs', 'unlikely', 'too-short']) {
    expect((levels.get(level) ?? 0) > 0, `в демо нет уровня ${level}`);
  }

  // 5. Сбой модели: unavailable, не кэшируется, короткий текст остаётся too-short
  const fresh = 'Совершенно новый текст для проверки сбоя модели '.repeat(6);
  const down = demoAiCheck(fresh, { modelDown: true });
  expect(down.level === 'unavailable' && down.score === null, `сбой модели: ${describe(down)}`);
  const up = demoAiCheck(fresh);
  expect(
    up.level !== 'unavailable' && up.textHash === down.textHash,
    'после сбоя текст не проверился',
  );
  const shortDown = demoAiCheck('Короткий текст', { modelDown: true });
  expect(shortDown.level === 'too-short', `короткий текст при сбое: ${describe(shortDown)}`);
  const cachedDown = demoAiCheck(fresh, { modelDown: true });
  expect(sameResult(cachedDown, up), 'проверенный текст при сбое не взят из кэша');

  // 4. Сквозная проверка через имитацию API
  const api = createFakeApi();
  const searches: { name: string; request: SearchRequest }[] = [
    {
      name: 'текст релиза',
      request: { text: RELEASE_SOURCE_TEXT, period: presetPeriod('7d'), mode: 'everywhere' },
    },
    {
      name: 'БДД',
      request: {
        text: 'Безопасность дорожного движения',
        period: presetPeriod('30d'),
        mode: 'everywhere',
      },
    },
  ];
  for (const { name, request } of searches) {
    const selection = await finishedSelection(api, request);
    const withText = selection.items.filter(
      (i): i is ResultItem & { publication: { text: string } } => i.publication.text !== null,
    );
    for (const item of selection.items) {
      expect(
        (item.publication.text === null) === (item.aiCheck === undefined),
        `${name}: у ${item.id} проверка на ИИ ${item.aiCheck ? 'есть без текста' : 'отсутствует'}`,
      );
    }
    const separate = await Promise.all(
      withText.map((item, i) =>
        api.checkAiText(
          VARIANTS[i % VARIANTS.length]?.apply(item.publication.text) ?? item.publication.text,
        ),
      ),
    );
    withText.forEach((item, i) => {
      const own = item.aiCheck;
      const other = separate[i];
      expect(
        own !== undefined &&
          other !== undefined &&
          sameResult(own, other) &&
          own.checkedAt === other.checkedAt,
        `${name}: подборка ≠ отдельная проверка для ${item.id}: ${describe(own)} / ${describe(other)}`,
      );
    });
    const active = selection.items.filter((i) => !i.excluded);
    const likely = active.filter((i) => i.aiCheck?.level === 'likely-ai').length;
    const signs = active.filter((i) => i.aiCheck?.level === 'signs').length;
    expect(
      selection.counts.aiLikely === likely,
      `${name}: counts.aiLikely ${selection.counts.aiLikely} ≠ ${likely}`,
    );
    expect(
      selection.counts.aiSigns === signs,
      `${name}: counts.aiSigns ${selection.counts.aiSigns} ≠ ${signs}`,
    );
    lines.push(
      `Поиск «${name}»: записей ${selection.items.length}, похоже на ИИ ${likely}, признаки ИИ ${signs}`,
    );

    const release = selection.groups.find((g) => g.kind === 'release');
    if (release) {
      const spread = await api.getSpread(selection.searchId, release.id);
      for (const p of spread.placements) {
        const item = selection.items.find((i) => i.id === p.itemId);
        expect(
          item?.aiCheck !== undefined &&
            p.aiCheck !== undefined &&
            sameResult(item.aiCheck, p.aiCheck),
          `${name}: «Распространение» ≠ подборка для ${p.itemId}: ${describe(p.aiCheck)} / ${describe(item?.aiCheck)}`,
        );
      }
      const retold = spread.placements.filter((p) => !p.isOriginal && p.placementType === 'retold');
      const retoldLikely = retold.filter((p) => p.aiCheck?.level === 'likely-ai').length;
      expect(
        spread.aiRetold?.likelyAi === retoldLikely && spread.aiRetold.retold === retold.length,
        `${name}: сводка «Распространения» ${JSON.stringify(spread.aiRetold)} ≠ ${retoldLikely} из ${retold.length}`,
      );
      lines.push(
        `«Распространение»: похожи на ИИ ${retoldLikely} из ${retold.length} пересказов; уровни пересказов: ` +
          retold.map((p) => p.aiCheck?.level ?? 'нет').join(', '),
      );
    }
  }

  // Примеры экрана «Проверка на ИИ» дают все четыре уровня
  const sampleLevels = await Promise.all(DEMO_AI_TEXTS.map((s) => api.checkAiText(s.text)));
  lines.push(
    `Примеры экрана: ${DEMO_AI_TEXTS.map((s, i) => `${s.label} → ${sampleLevels[i]?.level ?? '?'}`).join('; ')}`,
  );
  for (const level of ['likely-ai', 'signs', 'unlikely', 'too-short']) {
    expect(
      sampleLevels.some((c) => c.level === level),
      `среди примеров экрана нет уровня ${level}`,
    );
  }

  lines.push(`Проверок: ${checks}, нарушений: ${failures.length}`);
  return { failures, lines };
}
