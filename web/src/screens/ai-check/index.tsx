/**
 * Экран «Проверка на ИИ» — отдельная проверка текста (04-decisions.md, «Проверка текста на ИИ»,
 * уточнение; research/ai-text-detection.md §4.2, вариант А).
 *
 * Сюда приходит выделенный текст из пункта «Проверить текст на ИИ» в контекстном меню
 * расширения, сюда же можно вставить текст руками. Результат — крупное слово уровня узким
 * гротеском, число слов и одна строка «Оценка модели, не доказательство». Процентов нет.
 * Тот же текст даёт тот же результат, что и метка в подборке и в «Распространении»: одна
 * нормализация (src/lib/ai-normalize.ts) и общий кэш на сервере. Ниже — «Найти, где это
 * опубликовано» для того же текста.
 */
import { RotateCcw, Search } from 'lucide-react';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { IS_MOCKUP, api, demoAiTexts, errorMessage, isApiError } from '@/api';
import type { AiCheck } from '@/api/types';
import { useNavigation, type ScreenProps } from '@/app/navigation';
import { Button, Chip, ErrorState, Screen, TextArea, useAnnounce } from '@/components';
import { AI_DISCLAIMER, AI_LEVEL_TITLE } from '@/lib/ai-check';
import { AI_MIN_WORDS, countAiWords, normalizeAiText } from '@/lib/ai-normalize';
import { WORDS, formatCount } from '@/lib/format';
import { AiDots } from './AiMark';
import styles from './ai-check.module.css';

type Status =
  | { kind: 'idle' }
  | { kind: 'checking'; normalized: string }
  | { kind: 'done'; normalized: string; text: string; result: AiCheck }
  | { kind: 'failed'; normalized: string; text: string; message: string; offline: boolean };

/** «214 слов»; для короткого — «23 слова (нужно от 40 слов)». */
function wordsLine(result: AiCheck): string {
  const words = formatCount(result.words, WORDS.word);
  return result.level === 'too-short'
    ? `${words} (нужно от ${formatCount(AI_MIN_WORDS, WORDS.word)})`
    : words;
}

function announcement(result: AiCheck): string {
  const model =
    result.level === 'likely-ai' || result.level === 'signs' || result.level === 'unlikely'
      ? ` ${AI_DISCLAIMER}.`
      : '';
  return `Результат проверки: ${AI_LEVEL_TITLE[result.level]}. ${wordsLine(result)}.${model}`;
}

export default function AiCheckScreen({ params, navKey }: ScreenProps<'ai-check'>) {
  const { navigate } = useNavigation();
  const announce = useAnnounce();
  const [text, setText] = useState(params.text ?? '');
  const [status, setStatus] = useState<Status>({ kind: 'idle' });
  /** Номер последней проверки: ответ на прежнюю не перетирает новую. */
  const latest = useRef(0);

  const normalized = normalizeAiText(text);
  const words = countAiWords(normalized);
  // Результат относится к тексту, который проверяли. Другие пробелы и переносы его не меняют —
  // та же нормализация, что у проверки; другие слова — результат прячем.
  const current = status.kind !== 'idle' && status.normalized === normalized ? status : null;

  const run = (value: string) => {
    const key = normalizeAiText(value);
    if (!key) return;
    latest.current += 1;
    const id = latest.current;
    setStatus({ kind: 'checking', normalized: key });
    api.checkAiText(value).then(
      (result) => {
        if (id !== latest.current) return;
        setStatus({ kind: 'done', normalized: key, text: value, result });
        announce(announcement(result));
      },
      (error: unknown) => {
        if (id !== latest.current) return;
        // ErrorState сам объявляется скринридером (role="alert")
        setStatus({
          kind: 'failed',
          normalized: key,
          text: value,
          message: errorMessage(error),
          offline: isApiError(error) && error.code === 'offline',
        });
      },
    );
  };

  // Новый переход с текстом: из контекстного меню расширения или из другого экрана.
  useEffect(() => {
    if (params.text === undefined) return;
    setText(params.text);
    if (params.autoRun) run(params.text);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- реагируем только на новый переход
  }, [navKey]);

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    run(text);
  };

  const findPublished = (value: string) => navigate('search', { text: value, autoRun: true });

  return (
    <Screen
      index="03"
      title="Проверка *на ИИ*"
      eyebrow="Проверка на ИИ · похож ли текст на написанный нейросетью"
      width="narrow"
      className={styles.screen}
    >
      <form className={styles.form} onSubmit={onSubmit} aria-label="Текст для проверки">
        <TextArea
          label="Текст для проверки"
          hideLabel
          placeholder={`Вставьте текст поста или новости — от ${AI_MIN_WORDS} слов`}
          value={text}
          rows={6}
          onChange={(e) => setText(e.target.value)}
          hint={normalized ? formatCount(words, WORDS.word) : undefined}
        />
        {IS_MOCKUP && demoAiTexts.length > 0 && (
          <div className={styles.examples}>
            <span className={styles.examplesLabel}>Например:</span>
            {demoAiTexts.map((sample) => (
              <Chip
                key={sample.id}
                size="sm"
                onClick={() => {
                  setText(sample.text);
                  run(sample.text);
                }}
              >
                {sample.label}
              </Chip>
            ))}
          </div>
        )}
        <div className={styles.submit}>
          <Button
            type="submit"
            variant="primary"
            size="lg"
            disabled={!normalized || current?.kind === 'checking'}
          >
            Проверить
          </Button>
        </div>
      </form>

      {current?.kind === 'checking' && (
        <div className={styles.checking} role="status">
          <span className={styles.runner} aria-hidden="true">
            <span />
            <span />
            <span />
          </span>
          Проверяем…
        </div>
      )}

      {current?.kind === 'failed' && (
        <ErrorState
          title="Проверить не удалось"
          description={current.message}
          kind={current.offline ? 'offline' : 'error'}
          onRetry={() => run(current.text)}
        />
      )}

      {current?.kind === 'done' && (
        <section className={styles.result} aria-labelledby="ai-result-title">
          <div className={styles.verdict} data-level={current.result.level}>
            <AiDots level={current.result.level} size="lg" />
            <h2 id="ai-result-title" className={styles.level}>
              {AI_LEVEL_TITLE[current.result.level]}
            </h2>
          </div>
          {current.result.level === 'unavailable' ? (
            <div className={styles.unavailable}>
              <p className={styles.line}>Модель не ответила. Это не значит «не похоже на ИИ».</p>
              <Button
                variant="secondary"
                size="sm"
                iconStart={<RotateCcw />}
                onClick={() => run(current.text)}
              >
                Повторить
              </Button>
            </div>
          ) : (
            <p className={styles.words}>{wordsLine(current.result)}</p>
          )}
          {current.result.level !== 'too-short' && current.result.level !== 'unavailable' && (
            <p className={styles.line}>{AI_DISCLAIMER}.</p>
          )}
          <div className={styles.actions}>
            <Button
              variant="secondary"
              iconStart={<Search />}
              onClick={() => findPublished(current.text)}
            >
              Найти, где это опубликовано
            </Button>
          </div>
        </section>
      )}
    </Screen>
  );
}
