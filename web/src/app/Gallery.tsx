/**
 * Витрина базовых компонентов — ТОЛЬКО В МОКАПЕ. Для исполнителей: как выглядят
 * и как вызываются общие компоненты, во всех состояниях и в обеих темах.
 */
import { Download, RotateCw, Trash2 } from 'lucide-react';
import { useState } from 'react';
import type { PlatformStatus, SearchConditions } from '@/api/types';
import {
  Button,
  Card,
  CardBody,
  CardFooter,
  CardHeader,
  CardMeta,
  Chip,
  Dialog,
  DialogClose,
  EmptyState,
  ErrorState,
  IconButton,
  PlatformLabel,
  Screen,
  Section,
  Skeleton,
  SkeletonText,
  StatusBadge,
  StatusBadgeFromView,
  StatusLine,
  TextField,
  ToggleGroup,
  useAnnounce,
  useToast,
} from '@/components';
import { platformStatusView } from '@/lib/labels';
import type { ScreenProps } from './navigation';
import styles from './Gallery.module.css';

const CONDITIONS: SearchConditions = {
  searchId: 'gallery',
  text: 'Безопасность дорожного движения',
  label: 'Безопасность дорожного движения',
  kind: 'topic',
  period: { preset: '30d', from: '2026-09-20', to: '2026-10-19' },
  region: { id: 'krasnoyarsk-krai', name: 'Красноярский край', timeZone: 'Asia/Krasnoyarsk' },
  mode: 'my-sources',
  sourceCount: 20,
  platforms: ['vk', 'ok', 'max'],
  meaningLabel: null,
  startedAt: '2026-10-19T14:30:00+07:00',
  finishedAt: '2026-10-19T14:32:00+07:00',
  repeatOf: null,
};

const base = { problem: null, freshness: null, cap: null, updatedAt: null, progress: null };

/** Все состояния площадки (НТ-3) для витрины. */
const ALL_STATES: PlatformStatus[] = [
  { ...base, platform: 'vk', state: 'waiting', found: 0 },
  {
    ...base,
    platform: 'vk',
    state: 'searching',
    found: 4,
    progress: { done: 18, total: 40, unit: 'sources' },
  },
  { ...base, platform: 'vk', state: 'found', found: 25 },
  { ...base, platform: 'ok', state: 'nothing', found: 0 },
  {
    ...base,
    platform: 'vk',
    state: 'partial',
    found: 21,
    progress: { done: 39, total: 40, unit: 'sources' },
    problem: { code: 'sources-closed', message: 'Одна группа закрыта', retryable: false },
  },
  {
    ...base,
    platform: 'max',
    state: 'error',
    found: 0,
    problem: { code: 'unavailable', message: 'MAX не отвечает', retryable: true },
  },
  {
    ...base,
    platform: 'max',
    state: 'error',
    found: 0,
    problem: { code: 'bad-response', message: 'Непонятный ответ', retryable: true },
  },
  {
    ...base,
    platform: 'max',
    state: 'no-access',
    found: 0,
    problem: { code: 'key-invalid', message: 'Ключ недействителен', retryable: false },
  },
  {
    ...base,
    platform: 'ok',
    state: 'stopped',
    found: 3,
    progress: { done: 7, total: 18, unit: 'sources' },
  },
];

const LINE_STATUSES: PlatformStatus[] = [
  { ...base, platform: 'vk', state: 'found', found: 25 },
  { ...base, platform: 'ok', state: 'found', found: 8 },
  {
    ...base,
    platform: 'max',
    state: 'error',
    found: 0,
    problem: {
      code: 'unavailable',
      message: 'MAX не отвечает. Найденное на других площадках сохранено.',
      retryable: true,
    },
    freshness: { delayHours: 24, note: 'Публикации последних ~24 часов могут ещё не найтись.' },
  },
];

export default function GalleryScreen(_props: ScreenProps<'gallery'>) {
  const toast = useToast();
  const announce = useAnnounce();
  const [mode, setMode] = useState<'all' | 'groups' | 'hide'>('groups');
  const [filters, setFilters] = useState({ direct: true, indirect: false, disputed: false });
  const [excluded, setExcluded] = useState(false);

  return (
    <Screen
      title="Базовые компоненты"
      eyebrow="Только в мокапе"
      lead="Витрина src/components: как выглядят и как вызываются. Переключите тему в меню «Вид»."
    >
      <Section title="Кнопки">
        <div className={styles.row}>
          <Button variant="primary">Найти</Button>
          <Button>Остановить</Button>
          <Button variant="ghost">Отмена</Button>
          <Button variant="danger" iconStart={<Trash2 />}>
            Удалить
          </Button>
          <Button variant="link">Подробнее</Button>
          <Button variant="primary" iconStart={<Download />}>
            Скачать XLSX — 35 записей
          </Button>
          <Button loading>Проверяем</Button>
          <Button size="sm" iconStart={<RotateCw />}>
            Повторить
          </Button>
          <Button size="lg" variant="primary">
            Начать поиск
          </Button>
          <IconButton label="Повторить" icon={<RotateCw />} />
          <IconButton label="Удалить" icon={<Trash2 />} variant="secondary" size="sm" />
        </div>
      </Section>

      <Section title="Чипы и переключатели">
        <div className={styles.row}>
          <Chip>
            Период: <strong>1–19 окт</strong>
          </Chip>
          <Chip tone="info">краевой источник</Chip>
          <Chip tone="warning">дата неизвестна</Chip>
          {(['direct', 'indirect', 'disputed'] as const).map((key) => (
            <Chip
              key={key}
              count={key === 'direct' ? 22 : key === 'indirect' ? 8 : 7}
              selected={filters[key]}
              onClick={() => setFilters((f) => ({ ...f, [key]: !f[key] }))}
            >
              {key === 'direct' ? 'Прямо' : key === 'indirect' ? 'Косвенно' : 'Спорно — проверьте'}
            </Chip>
          ))}
        </div>
        <div className={styles.row}>
          <ToggleGroup
            label="Режим копий"
            value={mode}
            onValueChange={setMode}
            items={[
              { value: 'all', label: 'Все' },
              { value: 'groups', label: 'Группы', count: 3 },
              { value: 'hide', label: 'Скрыть копии' },
            ]}
          />
          <ToggleGroup
            label="Сортировка"
            size="sm"
            value="time"
            onValueChange={() => undefined}
            items={[
              { value: 'time', label: 'По времени' },
              { value: 'pop', label: 'По популярности' },
            ]}
          />
        </div>
      </Section>

      <Section title="Статусы площадок — полный набор (НТ-3)">
        <div className={styles.row}>
          {ALL_STATES.map((s, i) => (
            <span key={i} className={styles.status}>
              <PlatformLabel platform={s.platform} />
              <StatusBadgeFromView view={platformStatusView(s)} size="sm" />
            </span>
          ))}
          <StatusBadge tone="info" icon="delay" size="sm">
            данные с задержкой до ~24 ч
          </StatusBadge>
          <StatusBadge tone="neutral" icon="queue" size="sm">
            в очереди: перед вами 2
          </StatusBadge>
          <StatusBadge tone="warning" icon="offline" size="sm">
            нет связи
          </StatusBadge>
        </div>
      </Section>

      <Section title="Строка условий и статусов">
        <StatusLine
          conditions={CONDITIONS}
          statuses={LINE_STATUSES}
          total={33}
          onRetry={() => toast.show({ title: 'Повторяем поиск по MAX' })}
          actions={
            <Button variant="primary" size="sm" iconStart={<Download />}>
              Скачать XLSX — 33 записи
            </Button>
          }
          onConditionsChangedRun={() => toast.show({ title: 'Ищем по новым условиям' })}
        />
      </Section>

      <Section title="Каркас карточки">
        <Card as="article" tone={excluded ? 'excluded' : 'default'}>
          <CardHeader aside={<Chip size="sm">Прямо</Chip>}>
            <CardMeta>
              <PlatformLabel platform="vk" /> · Телеканал края · 19 окт, 08:45
            </CardMeta>
          </CardHeader>
          <CardBody>
            <strong>Утром в Красноярске выпал первый снег — на дорогах гололёд.</strong>
            <span>
              С начала суток в городе зарегистрировано <mark>37 ДТП</mark>, в основном мелкие
              столкновения.
            </span>
          </CardBody>
          <CardFooter>
            <span>краевой источник · найдено по смыслу · получено в 14:32</span>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setExcluded(true);
                toast.undo('Исключено: 1 публикация', () => setExcluded(false));
              }}
            >
              Исключить
            </Button>
          </CardFooter>
        </Card>
      </Section>

      <Section title="Окно, уведомления, живая область">
        <div className={styles.row}>
          <Dialog
            trigger={<Button>Открыть окно</Button>}
            title="Предпросмотр файла"
            description="Так будет выглядеть XLSX. В мокапе файл не скачивается."
            footer={
              <DialogClose>
                <Button variant="primary">Готово</Button>
              </DialogClose>
            }
          >
            <SkeletonText lines={4} />
          </Dialog>
          <Button
            onClick={() =>
              toast.undo('Источник удалён: «Канск сегодня»', () =>
                toast.show({ title: 'Источник возвращён', tone: 'good' }),
              )
            }
          >
            Уведомление с «Отменить»
          </Button>
          <Button
            onClick={() =>
              toast.show({
                title: 'MAX не отвечает',
                description: 'Найденное сохранено',
                tone: 'critical',
              })
            }
          >
            Уведомление-ошибка
          </Button>
          <Button onClick={() => announce('Найдено 37 публикаций: ВКонтакте 25, Одноклассники 8')}>
            Объявить скринридеру
          </Button>
        </div>
      </Section>

      <Section title="Состояния: загрузка, пусто, ошибка">
        <div className={styles.grid}>
          <Card>
            <Skeleton height={18} width="60%" />
            <SkeletonText lines={3} />
          </Card>
          <Card>
            <EmptyState
              compact
              title="Ничего не нашли"
              description="Площадки ответили, подходящих публикаций нет. Это не ошибка."
              actions={<Button size="sm">Расширить период</Button>}
            />
          </Card>
          <Card>
            <ErrorState
              compact
              title="Поиск не выполнен"
              description="Сервер не ответил. Условия сохранены."
              onRetry={() => toast.show({ title: 'Повторяем' })}
            />
          </Card>
          <Card>
            <ErrorState
              compact
              kind="offline"
              title="Нет связи с интернетом"
              description="Поиск продолжается на сервере."
            />
          </Card>
        </div>
      </Section>

      <Section title="Поле ввода">
        <div className={styles.grid}>
          <TextField
            label="Ссылка на группу"
            placeholder="https://vk.com/…"
            hint="VK, OK или MAX"
          />
          <TextField
            label="Ссылка на группу"
            defaultValue="https://example.ru/news"
            error="Это не ссылка на группу ВКонтакте, Одноклассников или MAX."
          />
        </div>
      </Section>
    </Screen>
  );
}
