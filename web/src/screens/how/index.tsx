/**
 * П8. «Как это работает» — простым языком для сотрудника и подробнее для эксперта, в стиле
 * сайта «Медиарадар»: нумерованные разделы, ключевые слова ярче остального текста, плитки и
 * строки через линию, «подробнее» раскрывается плюсом. Откуда данные (Р2–Р3: VK — по
 * сообществам края, MAX — через MaxStat), как определяется край (Р4), как идёт отбор (Р5),
 * что нейросеть не пишет текст и ссылки (Р5–Р6, НТ-8), что никуда не передаётся (НТ-7),
 * честные рамки (НТ-3, НТ-4, НТ-13, НТ-24). Параметр `section` — к какому разделу прокрутить.
 */
import { MapPin, Newspaper } from 'lucide-react';
import { useCallback, useEffect, type CSSProperties, type ReactNode } from 'react';
import type { PlatformId, SelectionMethod } from '@/api/types';
import type { ScreenParamsMap, ScreenProps } from '@/app/navigation';
import { useServerPlatforms } from '@/app/platforms';
import { useShell } from '@/app/shell-state';
import { Chip, cx, PlatformDot, Screen } from '@/components';
import { DotsStage } from '@/dots';
import {
  METHOD_HINT,
  METHOD_LABEL,
  MODE_HINT,
  MODE_LABEL,
  PLATFORMS,
  REGION_PRINCIPLE,
  platformsWhere,
  RELEVANCE_HINT,
  RELEVANCE_LABEL,
  RELEVANCE_ORDER,
} from '@/lib/labels';
import { FUNNEL, LIMITS, PLATFORM_SOURCES, REGION_EXAMPLES, type PlatformSource } from './content';
import styles from './how.module.css';

/** Что получаем с дополнительных площадок (их «как ищем» и оговорки приходят с сервера) */
const EXTRA_GETS: Partial<Record<PlatformId, string>> = {
  site: 'Заголовок и начало статьи, дата, прямая ссылка, название издания.',
  dzen: 'Текст публикации, дата, прямая ссылка, название канала редакции.',
};

type SectionKey = NonNullable<ScreenParamsMap['how']['section']> | 'ai';

const SECTIONS: readonly { key: SectionKey; title: string }[] = [
  { key: 'data', title: 'Откуда данные' },
  { key: 'region', title: 'Как определяется край' },
  { key: 'selection', title: 'Как идёт отбор' },
  { key: 'ai', title: 'Нейросеть не пишет текст и ссылки' },
  { key: 'privacy', title: 'Что никуда не передаётся' },
  { key: 'limits', title: 'Честные рамки' },
];

const METHODS: readonly SelectionMethod[] = [
  'copy',
  'semantic',
  'ai-confirmed',
  'ai-unchecked',
  'manual',
];

const sectionId = (key: SectionKey): string => `how-${key}`;
const num = (i: number): string => String(i + 1).padStart(2, '0');

/** «Только группы…» → «только группы…» */
const lowerFirst = (text: string): string => text.charAt(0).toLowerCase() + text.slice(1);

export default function HowScreen({ params, navKey }: ScreenProps<'how'>) {
  // Площадки — от сервера: обязательные описаны здесь, дополнительные (сайты СМИ, Дзен) —
  // его же словами: откуда данные (via) и оговорка о покрытии и правилах (note)
  const { ids, info } = useServerPlatforms();
  const sources: PlatformSource[] = [
    ...PLATFORM_SOURCES.filter((p) => ids.includes(p.platform)),
    ...info
      .filter((p) => !PLATFORM_SOURCES.some((s) => s.platform === p.id))
      .map((p) => ({
        platform: p.id,
        how: p.via.charAt(0).toUpperCase() + p.via.slice(1),
        gets: EXTRA_GETS[p.id] ?? 'Текст публикации, дата и прямая ссылка.',
        limits: p.note ? [p.note] : [],
      })),
  ];
  const { reducedMotion } = useShell();

  const goTo = useCallback(
    (key: SectionKey) => {
      const heading = document.getElementById(`${sectionId(key)}-title`);
      if (!heading) return;
      heading.scrollIntoView({ block: 'start', behavior: reducedMotion ? 'auto' : 'smooth' });
      heading.focus({ preventScroll: true });
    },
    [reducedMotion],
  );

  // Переход с параметром: прокрутить к разделу после того, как оболочка
  // переведёт фокус и прокрутит страницу наверх.
  useEffect(() => {
    if (!params.section) return;
    const key = params.section;
    const timer = window.setTimeout(() => goTo(key), 60);
    return () => window.clearTimeout(timer);
  }, [navKey, params.section, goTo]);

  // «Коротко» — рядом с картой края, как первый экран сайта
  const short = (
    <section className={cx(styles.short, styles.reveal)} aria-labelledby="how-short">
      <h2 id="how-short" className={styles.kicker}>
        Коротко
      </h2>
      <ul className={styles.shortList}>
        <li>
          Ищем <b>публичные посты</b> {platformsWhere(ids)} — <b>только про Красноярский край</b>.
        </li>
        <li>
          Каждая запись в подборке — <b>настоящий пост</b>: ссылку, дату, заголовок и выдержку берём
          из самого поста.
        </li>
        <li>
          Нейросеть только помогает разобрать спорные случаи. <b>Текст и ссылки она не пишет.</b>
        </li>
        <li>
          Нейросеть работает <b>на нашем сервере</b>: тексты не уходят в облачные сервисы. Ключи
          доступа к площадкам — <b>тоже только на сервере</b>.
        </li>
        <li>
          Если площадка не ответила или данные неполные, это <b>видно над подборкой</b>, а не
          выдаётся за «ничего не найдено».
        </li>
      </ul>
    </section>
  );

  return (
    <Screen
      index="06"
      title="Как это *работает*"
      eyebrow="Как это работает · простыми словами, с честными рамками"
      lead="Откуда берутся публикации, как сервис решает, что подходит, и чего он не делает. Сверху — коротко, ниже — подробно."
      width="narrow"
      className={styles.screen}
      sceneMode="hero"
      scene={
        <DotsStage
          form="krai"
          intensity="calm"
          caption="Красноярский край — от Саян до Таймыра. По карте течёт Енисей"
        />
      }
      intro={short}
    >
      <nav aria-label="Разделы страницы">
        <ol className={styles.toc}>
          {SECTIONS.map((s, i) => (
            <li key={s.key}>
              <button type="button" className={styles.tocItem} onClick={() => goTo(s.key)}>
                <span className={styles.num} aria-hidden="true">
                  {num(i)}
                </span>
                <span>{s.title}</span>
              </button>
            </li>
          ))}
        </ol>
      </nav>

      {/* 01. Откуда данные */}
      <HowSection k="data">
        <p className={styles.p}>
          Ищем только то, что опубликовано <b>открыто</b> и видно любому посетителю. Поиск идёт{' '}
          <b>на нашем сервере</b>: входить в свои аккаунты не нужно, ваш вход в соцсети не
          используется. Расширение ничего не собирает с площадок — оно только передаёт в поиск
          текст, который вы сами выделили.
        </p>
        <ul className={styles.platforms}>
          {sources.map((p, i) => (
            <li
              key={p.platform}
              className={cx(styles.tile, styles.reveal)}
              style={{ '--i': i } as CSSProperties}
            >
              <h3 className={styles.tileTitle}>
                <PlatformDot platform={p.platform} size="lg" />
                {PLATFORMS[p.platform].name}
              </h3>
              <dl className={styles.facts}>
                <div>
                  <dt>Как ищем</dt>
                  <dd>{p.how}</dd>
                </div>
                <div>
                  <dt>Что получаем</dt>
                  <dd>{p.gets}</dd>
                </div>
                <div>
                  <dt>Ограничения</dt>
                  <dd>
                    <ul className={styles.bullets}>
                      {p.limits.map((l) => (
                        <li key={l}>{l}</li>
                      ))}
                    </ul>
                  </dd>
                </div>
              </dl>
            </li>
          ))}
        </ul>
        <p className={styles.p}>
          Перед тем как показать ссылку, проверяем, что пост <b>существует и открывается</b>.
          Выдуманных или «примерных» ссылок в подборке нет.
        </p>
        <Expert>
          <ul className={styles.bullets}>
            <li>
              ВКонтакте — VK API с сервисным ключом нашего приложения: стены сообществ (wall.get,
              wall.search). Метод поиска по всем постам (newsfeed.search) для нашего приложения
              закрыт — площадка отвечает ошибкой 1051.
            </li>
            <li>Одноклассники — анонимный веб-поиск ok.ru и страницы постов.</li>
            <li>
              MAX — поиск MaxStat по публичным каналам; каждая ссылка проверяется на max.ru, дата
              вычисляется из номера поста.
            </li>
            <li>
              Ключи доступа лежат только на сервере команды. В расширение, на страницу и в
              репозиторий они не попадают.
            </li>
            <li>
              Полученные посты сервер хранит только как кэш: он ускоряет повторы и проверку ссылок,
              но не заменяет поиск в момент запроса.
            </li>
          </ul>
        </Expert>
      </HowSection>

      {/* 02. Регион */}
      <HowSection k="region">
        <p className={styles.p}>{REGION_PRINCIPLE} Достаточно одного из двух признаков.</p>
        <div className={styles.signs}>
          <div className={cx(styles.tile, styles.reveal)}>
            <Newspaper aria-hidden="true" className={styles.signIcon} />
            <h3 className={styles.tileTitle}>Краевой источник</h3>
            <p className={styles.small}>
              Группа или канал из нашего каталога краевых источников или из вашего списка.
            </p>
          </div>
          <span className={styles.or} aria-hidden="true">
            или
          </span>
          <div className={cx(styles.tile, styles.reveal)} style={{ '--i': 1 } as CSSProperties}>
            <MapPin aria-hidden="true" className={styles.signIcon} />
            <h3 className={styles.tileTitle}>Упоминается место края</h3>
            <p className={styles.small}>
              В тексте есть город, район или посёлок края: Красноярск, Норильск, Ачинск, Канск,
              Минусинск…
            </p>
          </div>
        </div>
        <div className={styles.example}>
          <p className={styles.small}>Причину видно в каждой карточке подборки:</p>
          <ul className={styles.chips}>
            {REGION_EXAMPLES.map((r) => (
              <li key={r}>
                <Chip size="sm" icon={<MapPin />}>
                  {r}
                </Chip>
              </li>
            ))}
          </ul>
        </div>
        <ul className={styles.bullets}>
          <li>Ложные совпадения вроде «Красноярская улица в Москве» отсекает проверка смысла.</li>
          <li>
            <b>{MODE_LABEL['my-sources']}:</b> {lowerFirst(MODE_HINT['my-sources'])}. Вы сами
            выбрали источники, поэтому регион почти не фильтрует.
          </li>
          <li>
            <b>{MODE_LABEL.everywhere}:</b> {lowerFirst(MODE_HINT.everywhere)}. Здесь регион —
            главный фильтр.
          </li>
          <li>
            Регион один и всегда указан в условиях над подборкой. На запрос про другой регион
            ответим: «Поиск ограничен Красноярским краем», а не просто «ничего не найдено».
          </li>
        </ul>
      </HowSection>

      {/* 03. Отбор */}
      <HowSection k="selection">
        <p className={styles.p}>
          Перед поиском сервис показывает, <b>как он понял тему</b>: что входит, а что «не то». Это
          можно поправить — например, убрать пожарную безопасность из темы про безопасность
          дорожного движения.
        </p>
        <p className={styles.p}>
          Дальше найденные посты проходят <b>четыре проверки</b> — от простых к сложным. Каждая
          следующая смотрит только то, что не решила предыдущая.
        </p>
        <ol className={styles.funnel} aria-label="Четыре проверки отбора">
          {FUNNEL.map((step, i) => (
            <li
              key={step.title}
              className={cx(styles.funnelStep, styles.reveal)}
              style={{ '--i': i } as CSSProperties}
            >
              <span className={styles.funnelNum} aria-hidden="true">
                {num(i)}
              </span>
              <span className={styles.funnelText}>
                <span className={styles.funnelTitle}>{step.title}</span>
                <span>{step.does}</span>
                <span className={styles.small}>{step.catches}</span>
              </span>
            </li>
          ))}
        </ol>
        <p className={styles.small}>
          Итог — подборка с метками «прямо», «косвенно» и «спорно — проверьте».
        </p>
        <h3 className={styles.h3}>Метки в подборке</h3>
        <dl className={styles.facts}>
          {RELEVANCE_ORDER.map((r) => (
            <div key={r}>
              <dt className={styles.term}>{RELEVANCE_LABEL[r]}</dt>
              <dd>{RELEVANCE_HINT[r]}</dd>
            </div>
          ))}
        </dl>
        <h3 className={styles.h3}>Как запись попала в подборку</h3>
        <dl className={styles.facts}>
          {METHODS.map((m) => (
            <div key={m}>
              <dt className={styles.term}>{METHOD_LABEL[m]}</dt>
              <dd>{METHOD_HINT[m]}</dd>
            </div>
          ))}
        </dl>
        <ul className={styles.bullets}>
          <li>
            Один пост, найденный по разным адресам, — одна запись. А каждая перепечатка в другой
            группе — отдельная запись со своей ссылкой.
          </li>
          <li>Репост помечен «репост», пост без текста — «текст отсутствует».</li>
        </ul>
        <Expert>
          <ol className={styles.bullets}>
            <li>
              Совпадение фраз — хеши, шинглы и MinHash. Отсюда же доля дословного текста релиза.
            </li>
            <li>
              Близость по смыслу — открытая модель sergeyzh/BERTA (лицензия MIT) на нашем сервере.
              Векторы считаются по мере сбора, результаты приходят в подборку по мере готовности.
            </li>
            <li>Признаки события — извлечение имён, мест, дат и чисел (Natasha) и правила.</li>
            <li>Нейросеть — около 10 % кандидатов, где первые шаги не уверены.</li>
          </ol>
        </Expert>
      </HowSection>

      {/* 04. Нейросеть */}
      <HowSection k="ai">
        <div className={styles.aiGrid}>
          <div className={cx(styles.tile, styles.reveal)}>
            <h3 className={styles.tileTitle}>Что получает</h3>
            <p className={styles.small}>Только тексты постов и их внутренние номера.</p>
          </div>
          <div className={cx(styles.tile, styles.reveal)} style={{ '--i': 1 } as CSSProperties}>
            <h3 className={styles.tileTitle}>Что отвечает</h3>
            <p className={styles.small}>
              Только оценку из заранее заданного списка — относится ли пост к запросу — и номер
              предложения, на котором основано решение. Это предложение подсвечено в выдержке.
            </p>
          </div>
          <div className={cx(styles.tile, styles.reveal)} style={{ '--i': 2 } as CSSProperties}>
            <h3 className={styles.tileTitle}>Чего не делает</h3>
            <p className={styles.small}>
              Не пишет выдержки, заголовки, даты и ссылки. Всё это берём из самого поста.
            </p>
          </div>
        </div>
        <ul className={styles.bullets}>
          <li>
            Если нейросеть ответила не по форме, отказалась или не успела — запись получает «
            {METHOD_LABEL['ai-unchecked']}», а не «не относится». Решение остаётся за вами.
          </li>
          <li>
            Если нейросеть недоступна, первые три проверки работают как обычно, а спорные записи
            помечаются «{METHOD_LABEL['ai-unchecked']}».
          </li>
          <li>
            Текст поста для нейросети — только материал для оценки. Даже если в посте написаны
            команды для неё, ответ не по форме «метка + номер предложения» отбрасывается.
          </li>
        </ul>
        <Expert>
          <ul className={styles.bullets}>
            <li>
              Модель — GigaChat 3.1 Lightning: открытая, лицензия MIT, работает локально на нашем
              сервере через Ollama.
            </li>
            <li>
              Формат ответа задан схемой; номер предложения проверяется на существование в тексте.
            </li>
            <li>Она же один раз на запрос составляет карточку «как система поняла тему».</li>
          </ul>
        </Expert>
      </HowSection>

      {/* 05. Приватность */}
      <HowSection k="privacy">
        <div className={styles.privacy}>
          <div className={cx(styles.tile, styles.reveal)}>
            <h3 className={styles.tileTitle}>Уходит наружу</h3>
            <ul className={styles.bullets}>
              <li>
                Слова и фразы для поиска — во ВКонтакте, Одноклассники, сервис поиска по MAX
                (MaxStat), а также на сайты СМИ края и Дзен, когда ищем по их страницам. Без этого
                искать нельзя.
              </li>
              <li>Запросы на проверку ссылок — чтобы убедиться, что пост открывается.</li>
            </ul>
          </div>
          <div className={cx(styles.tile, styles.reveal)} style={{ '--i': 1 } as CSSProperties}>
            <h3 className={styles.tileTitle}>Не уходит</h3>
            <ul className={styles.bullets}>
              <li>
                Тексты постов и ваших запросов — в облачные нейросети: нейросеть у нас на сервере.
              </li>
              <li>
                Ключи доступа к площадкам — они только на сервере, их нет в расширении и на
                странице.
              </li>
              <li>Ваши поиски и список источников — другие пользователи их не видят.</li>
              <li>
                Ключ рабочего места — он хранится в этом браузере. Ссылку на рабочее место (меню ☰
                → «Рабочее место») не публикуйте: кто её знает, видит и меняет ваши поиски и
                источники.
              </li>
              <li>Ваши аккаунты в соцсетях — сервис ими не пользуется.</li>
            </ul>
          </div>
        </div>
      </HowSection>

      {/* 06. Рамки */}
      <HowSection k="limits">
        <ul className={styles.limits}>
          {LIMITS.map((l, i) => (
            <li
              key={l.title}
              className={cx(styles.limit, styles.reveal)}
              style={{ '--i': Math.min(i, 8) } as CSSProperties}
            >
              <h3 className={styles.limitTitle}>{l.title}</h3>
              <p className={styles.small}>{l.text}</p>
            </li>
          ))}
        </ul>
      </HowSection>
    </Screen>
  );
}

function HowSection({ k, children }: { k: SectionKey; children: ReactNode }) {
  const index = SECTIONS.findIndex((s) => s.key === k);
  const meta = SECTIONS[index];
  const id = sectionId(k);
  return (
    <section id={id} className={styles.section} aria-labelledby={`${id}-title`}>
      <h2 id={`${id}-title`} className={styles.h2} tabIndex={-1}>
        <span className={styles.num} aria-hidden="true">
          {num(index)}
        </span>
        {meta?.title}
      </h2>
      {children}
    </section>
  );
}

/** «Подробнее для специалиста» — раскрывается плюсом, как вопросы на сайте; доступно с клавиатуры. */
function Expert({ children }: { children: ReactNode }) {
  return (
    <details className={styles.expert}>
      <summary className={styles.expertSummary}>Подробнее для специалиста</summary>
      <div className={styles.expertBody}>{children}</div>
    </details>
  );
}
