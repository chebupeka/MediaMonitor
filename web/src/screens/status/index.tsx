/**
 * П9. Состояние стенда (НТ-18, SC-68, SC-46) — служебная страница для дежурного, в стиле
 * «Распространения»: заголовок-итог узким гротеском, плитки с крупными цифрами, карточки
 * площадок с квотами, нейросеть, очередь, память и последние события.
 * Статусы — значок + текст. Данные: `api.getStandStatus()`; состояния меняет демо-сценарий.
 */
import { Info, RotateCw } from 'lucide-react';
import { useCallback, useEffect, useRef, type CSSProperties, type ReactNode } from 'react';
import { api, useAsync } from '@/api';
import type { HealthState, Quota, StandStatus } from '@/api/types';
import type { ScreenProps } from '@/app/navigation';
import {
  Button,
  cx,
  ErrorState,
  PlatformDot,
  Screen,
  Section,
  Skeleton,
  StatusBadge,
  useAnnounce,
} from '@/components';
import { formatDate, formatNumber, formatTime, TIME_ZONE_LABEL } from '@/lib/format';
import { PLATFORMS, type StatusIcon, type StatusTone } from '@/lib/labels';
import styles from './status.module.css';

const REFRESH_MS = 30_000;

interface View {
  tone: StatusTone;
  icon: StatusIcon;
  text: string;
}

const PLATFORM_VIEW: Record<HealthState, View> = {
  ok: { tone: 'good', icon: 'check', text: 'работает' },
  degraded: { tone: 'warning', icon: 'warning', text: 'с ограничениями' },
  down: { tone: 'critical', icon: 'error', text: 'не работает' },
};

const OVERALL: Record<HealthState, View & { title: string; lead: string }> = {
  ok: {
    tone: 'good',
    icon: 'check',
    text: 'всё в порядке',
    title: 'Стенд работает',
    lead: 'Все площадки и нейросеть отвечают. Эксперты могут проверять.',
  },
  degraded: {
    tone: 'warning',
    icon: 'warning',
    text: 'есть ограничения',
    title: 'Работает с ограничениями',
    lead: 'Поиск идёт, но часть данных может не прийти. Пользователи видят это в строке состояния над подборкой.',
  },
  down: {
    tone: 'critical',
    icon: 'error',
    text: 'не работает',
    title: 'Стенд не работает',
    lead: 'Поиск сейчас невозможен. Нужна помощь дежурного.',
  },
};

function aiView(ai: StandStatus['ai']): View & { detail: string } {
  if (ai.state === 'down') {
    return {
      tone: 'critical',
      icon: 'error',
      text: 'недоступна',
      detail:
        'Поиск работает без смысловой проверки: спорные публикации получают пометку «не проверено ИИ».',
    };
  }
  if (!ai.warm) {
    return {
      tone: 'progress',
      icon: 'progress',
      text: 'загружается',
      detail: 'Модель загружается в память. Первый поиск подождёт, пока она не будет готова.',
    };
  }
  return {
    tone: ai.state === 'degraded' ? 'warning' : 'good',
    icon: ai.state === 'degraded' ? 'warning' : 'check',
    text: ai.state === 'degraded' ? 'прогрета, отвечает медленно' : 'прогрета',
    detail: 'Модель загружена и отвечает: первый поиск эксперта не будет ждать загрузки.',
  };
}

const LEVEL_VIEW: Record<StandStatus['events'][number]['level'], View> = {
  info: { tone: 'neutral', icon: 'info', text: 'сведения' },
  warning: { tone: 'warning', icon: 'warning', text: 'внимание' },
  error: { tone: 'critical', icon: 'error', text: 'ошибка' },
};

const oneDecimal = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 });

/** «1 мин назад», «27 мин назад», «2 ч назад» относительно момента проверки. */
function ago(at: string, now: string): string {
  const min = Math.max(0, Math.round((Date.parse(now) - Date.parse(at)) / 60_000));
  if (min < 1) return 'только что';
  if (min < 60) return `${min} мин назад`;
  return `${Math.round(min / 60)} ч назад`;
}

type MeterTone = 'good' | 'warning' | 'critical';

const METER_CLASS: Record<MeterTone, string | undefined> = {
  good: styles.meterGood,
  warning: styles.meterWarning,
  critical: styles.meterCritical,
};

function shareTone(share: number, warnAt = 0.8, critAt = 1): MeterTone {
  if (share >= critAt) return 'critical';
  if (share >= warnAt) return 'warning';
  return 'good';
}

function quotaShare(q: Quota): number {
  return q.limit > 0 ? q.used / q.limit : 1;
}

export default function StatusScreen({ active }: ScreenProps<'status'>) {
  const stand = useAsync(useCallback(() => api.getStandStatus(), []));
  const announce = useAnnounce();
  const { reload } = stand;
  const manual = useRef(false);

  // Пока страница открыта — обновляем сами каждые 30 секунд.
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(reload, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [active, reload]);

  // О ручном обновлении сообщаем скринридеру, об автоматическом — нет.
  useEffect(() => {
    if (stand.status === 'success' && stand.data && manual.current) {
      manual.current = false;
      announce(`Состояние обновлено: ${OVERALL[stand.data.overall].title.toLowerCase()}`);
    }
  }, [stand.status, stand.data, announce]);

  const refresh = (): void => {
    manual.current = true;
    reload();
  };

  const data = stand.data;
  let content: ReactNode;
  if (!data && stand.status === 'error') {
    content = (
      <ErrorState
        title="Не удалось получить состояние стенда"
        description={
          stand.error?.code === 'offline'
            ? stand.error.message
            : `${stand.error?.message ?? ''} Если ошибка повторяется — сервер не отвечает: проверьте, запущен ли он.`
        }
        kind={stand.error?.code === 'offline' ? 'offline' : 'error'}
        onRetry={refresh}
      />
    );
  } else if (!data) {
    content = <Loading />;
  } else {
    content = <StandView data={data} />;
  }

  return (
    <Screen
      title="Состояние стенда"
      eyebrow="Служебная страница · для дежурного"
      className={styles.screen}
      actions={
        <Button
          variant="secondary"
          size="sm"
          iconStart={<RotateCw />}
          onClick={refresh}
          loading={stand.status === 'loading' && Boolean(data)}
        >
          Обновить
        </Button>
      }
    >
      {data && stand.status === 'error' && (
        <p className={styles.notice} role="alert">
          Не удалось обновить: {stand.error?.message} Ниже — данные на {formatTime(data.checkedAt)}.
        </p>
      )}
      {content}
    </Screen>
  );
}

function Loading() {
  return (
    <div className={styles.loading} role="status">
      <span className="sr-only">Проверяем состояние стенда</span>
      <Skeleton height={40} width="60%" radius="md" />
      <div className={styles.tiles}>
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} height={112} radius="lg" />
        ))}
      </div>
      <div className={styles.platforms}>
        {Array.from({ length: 3 }, (_, i) => (
          <Skeleton key={i} height={200} radius="lg" />
        ))}
      </div>
    </div>
  );
}

function StandView({ data }: { data: StandStatus }) {
  const overall = OVERALL[data.overall];
  const ai = aiView(data.ai);
  const problems: string[] = [
    ...data.platforms
      .filter((p) => p.state !== 'ok')
      .map((p) => `${PLATFORMS[p.platform].name}: ${p.message}`),
    // Предупреждение дежурному при 80 % квоты площадки (НТ-6).
    ...data.platforms
      .filter((p) => p.quota && shareTone(quotaShare(p.quota)) !== 'good')
      .map(
        (p) =>
          `${PLATFORMS[p.platform].name}: израсходовано ${Math.round(
            quotaShare(p.quota as Quota) * 100,
          )}% квоты`,
      ),
    ...(data.ai.state !== 'ok' || !data.ai.warm ? [`Нейросеть: ${ai.text}`] : []),
  ];
  const working = data.platforms.filter((p) => p.state === 'ok').length;
  const memShare = data.memory.totalMb > 0 ? data.memory.usedMb / data.memory.totalMb : 0;
  const memTone = shareTone(memShare, 0.8, 0.9);

  return (
    <>
      <header className={styles.overall}>
        <h2 className={styles.overallTitle}>{overall.title}</h2>
        <p className={styles.overallLine}>
          <StatusBadge tone={overall.tone} icon={overall.icon}>
            {overall.text}
          </StatusBadge>
          <span className={styles.checked}>
            проверено в {formatTime(data.checkedAt)}, {TIME_ZONE_LABEL} · обновляется само раз в 30
            секунд
          </span>
        </p>
        <p className={styles.overallLead}>{overall.lead}</p>
        {problems.length > 0 && (
          <ul className={styles.notes} aria-label="Что требует внимания">
            {problems.map((p) => (
              <li key={p}>
                <Info aria-hidden="true" />
                {p}
              </li>
            ))}
          </ul>
        )}
      </header>

      <div className={styles.tiles}>
        <Tile i={0} label="Площадки" num={`${working}/${data.platforms.length}`}>
          {working === data.platforms.length
            ? 'работают без ограничений'
            : `работают без ограничений; остальные — ниже`}
        </Tile>
        <Tile i={1} label="Поиски сейчас" num={formatNumber(data.queue.running)}>
          {data.queue.waiting === 0 ? 'очереди нет' : `ждут в очереди: ${data.queue.waiting}`} · не
          больше {data.queue.perClientLimit} одновременно с одного адреса
        </Tile>
        <Tile
          i={2}
          label="Нейросеть"
          num={
            data.ai.avgSecondsPerPost === null
              ? '—'
              : `${oneDecimal.format(data.ai.avgSecondsPerPost)} с`
          }
        >
          {data.ai.avgSecondsPerPost === null ? 'скорость: нет данных' : 'на один пост'} · {ai.text}
        </Tile>
        <Tile i={3} label="Память сервера" num={`${Math.round(memShare * 100)}%`}>
          <Meter share={memShare} tone={memTone} />
          занято {oneDecimal.format(data.memory.usedMb / 1024)} из{' '}
          {oneDecimal.format(data.memory.totalMb / 1024)} ГБ
        </Tile>
      </div>

      <Section title="Площадки" aside="как ищем, квота, последний ответ">
        <ul className={styles.platforms}>
          {data.platforms.map((p, i) => {
            const view = PLATFORM_VIEW[p.state];
            return (
              <li
                key={p.platform}
                className={cx(styles.card, styles.reveal)}
                style={{ '--i': i + 4 } as CSSProperties}
              >
                <article aria-labelledby={`stand-${p.platform}`} className={styles.cardInner}>
                  <div className={styles.cardHead}>
                    <h3 id={`stand-${p.platform}`} className={styles.cardTitle}>
                      <PlatformDot platform={p.platform} size="lg" />
                      {PLATFORMS[p.platform].name}
                    </h3>
                    <StatusBadge tone={view.tone} icon={view.icon} size="sm">
                      {view.text}
                    </StatusBadge>
                  </div>
                  <p className={styles.message}>{p.message}</p>
                  <dl className={styles.facts}>
                    <div>
                      <dt>Как ищем</dt>
                      <dd>{p.via}</dd>
                    </div>
                    <div>
                      <dt>Последний ответ</dt>
                      <dd>
                        {p.lastSuccessAt
                          ? `${formatTime(p.lastSuccessAt)} · ${ago(p.lastSuccessAt, data.checkedAt)}`
                          : 'ещё не было'}
                      </dd>
                    </div>
                    <div>
                      <dt>Свежесть данных</dt>
                      <dd>
                        {p.freshness
                          ? `отставание ~${p.freshness.delayHours} ч · ${p.freshness.note}`
                          : 'без задержки'}
                      </dd>
                    </div>
                    <div>
                      <dt>Квота</dt>
                      <dd>{p.quota ? <QuotaView quota={p.quota} /> : 'квоты нет'}</dd>
                    </div>
                  </dl>
                </article>
              </li>
            );
          })}
        </ul>
      </Section>

      <div className={styles.twoCols}>
        <Section title="Нейросеть">
          <div className={styles.card}>
            <div className={styles.cardHead}>
              <p className={styles.cardTitle}>Смысловая проверка</p>
              <StatusBadge tone={ai.tone} icon={ai.icon} size="sm">
                {ai.text}
              </StatusBadge>
            </div>
            <p className={styles.message}>{ai.detail}</p>
            <dl className={styles.facts}>
              <div>
                <dt>Модель</dt>
                <dd>{data.ai.model}</dd>
              </div>
              <div>
                <dt>Ждут проверки</dt>
                <dd>
                  {data.ai.queueLength === 0
                    ? 'очереди нет'
                    : `поисков в очереди: ${formatNumber(data.ai.queueLength)}`}
                </dd>
              </div>
              <div>
                <dt>Скорость</dt>
                <dd>
                  {data.ai.avgSecondsPerPost === null
                    ? 'нет данных'
                    : `${oneDecimal.format(data.ai.avgSecondsPerPost)} с на один пост`}
                </dd>
              </div>
            </dl>
          </div>
        </Section>

        <Section title="Нагрузка">
          <div className={styles.card}>
            <dl className={styles.facts}>
              <div>
                <dt>Поиски идут сейчас</dt>
                <dd>{formatNumber(data.queue.running)}</dd>
              </div>
              <div>
                <dt>Ждут в очереди</dt>
                <dd>{data.queue.waiting === 0 ? 'никто' : formatNumber(data.queue.waiting)}</dd>
              </div>
              <div>
                <dt>Одновременно с одного адреса</dt>
                <dd>не больше {formatNumber(data.queue.perClientLimit)}</dd>
              </div>
              <div>
                <dt>Память сервера</dt>
                <dd>
                  <span className={styles.meterRow}>
                    <span>
                      {oneDecimal.format(data.memory.usedMb / 1024)} из{' '}
                      {oneDecimal.format(data.memory.totalMb / 1024)} ГБ (
                      {Math.round(memShare * 100)}%)
                    </span>
                    <Meter share={memShare} tone={memTone} />
                    {memTone !== 'good' && (
                      <StatusBadge tone={memTone} icon="warning" size="sm">
                        памяти мало
                      </StatusBadge>
                    )}
                  </span>
                </dd>
              </div>
            </dl>
          </div>
        </Section>
      </div>

      <Section title="Последние события" aside={TIME_ZONE_LABEL}>
        {data.events.length === 0 ? (
          <p className={styles.message}>Событий нет.</p>
        ) : (
          <ol className={styles.events}>
            {data.events.map((e, i) => {
              const view = LEVEL_VIEW[e.level];
              return (
                <li key={`${e.at}-${i}`} className={styles.event}>
                  <time dateTime={e.at} className={styles.eventTime}>
                    {formatDate(e.at)}, {formatTime(e.at)}
                  </time>
                  <StatusBadge tone={view.tone} icon={view.icon} size="sm">
                    {view.text}
                  </StatusBadge>
                  <span className={styles.eventText}>{e.message}</span>
                </li>
              );
            })}
          </ol>
        )}
      </Section>

      <p className={styles.legend}>
        Версия сервера {data.version}. Ключи доступа к площадкам хранятся только на сервере — на
        этой странице и в расширении их нет.
      </p>
    </>
  );
}

function Tile({
  i,
  label,
  num,
  children,
}: {
  i: number;
  label: string;
  num: string;
  children: ReactNode;
}) {
  return (
    <div className={cx(styles.tile, styles.reveal)} style={{ '--i': i } as CSSProperties}>
      <span className={styles.tileLabel}>{label}</span>
      <span className={styles.tileNum}>{num}</span>
      <span className={styles.tileNote}>{children}</span>
    </div>
  );
}

/** Полоса заполнения (квота, память). Декоративная: цифры всегда рядом текстом. */
function Meter({ share, tone }: { share: number; tone: MeterTone }) {
  const pct = Math.max(0, Math.min(1, share)) * 100;
  return (
    <span className={styles.meter} aria-hidden="true">
      <span className={METER_CLASS[tone]} style={{ width: `${pct}%` }} />
    </span>
  );
}

function QuotaView({ quota }: { quota: Quota }) {
  const share = quotaShare(quota);
  const tone = shareTone(share);
  const left = Math.max(0, quota.limit - quota.used);
  return (
    <span className={styles.meterRow}>
      <span>
        {formatNumber(quota.used)} из {formatNumber(quota.limit)} {quota.unit} · осталось{' '}
        {formatNumber(left)}
      </span>
      <Meter share={share} tone={tone} />
      <span className={styles.quotaFoot}>
        {tone === 'critical' && (
          <StatusBadge tone="critical" icon="lock" size="sm">
            квота исчерпана
          </StatusBadge>
        )}
        {tone === 'warning' && (
          <StatusBadge tone="warning" icon="warning" size="sm">
            квота на исходе
          </StatusBadge>
        )}
        {quota.resetsAt && (
          <span>
            сброс {formatDate(quota.resetsAt)}, {formatTime(quota.resetsAt)}
          </span>
        )}
      </span>
    </span>
  );
}
