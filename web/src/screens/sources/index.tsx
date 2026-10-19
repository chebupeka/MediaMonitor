/**
 * TODO(Э-Источники): экран «Источники» (П5) — список с типом и районом (П13),
 * добавить по ссылке с проверкой (П9), правка, удаление с отменой, импорт из Excel
 * (ТЗ-Ф16), первый запуск: предложение готового каталога (НТ-14).
 * Данные: api.listSources / checkSource / addSource / updateSource / removeSource /
 * restoreSource / importSources / getCatalog / addFromCatalog.
 * Ссылки для проверки состояний: `demoLinks` из '@/api'.
 *
 * Ниже — временная демонстрация контракта. Замените её целиком.
 */
import { useCallback } from 'react';
import { api, useAsync } from '@/api';
import { ScreenStub } from '@/app/ScreenStub';
import type { ScreenProps } from '@/app/navigation';
import { Chip, Screen, Skeleton } from '@/components';
import { formatCount, WORDS } from '@/lib/format';
import { PLATFORMS, SOURCE_TYPE_LABEL } from '@/lib/labels';

export default function SourcesScreen(_props: ScreenProps<'sources'>) {
  const sources = useAsync(useCallback(() => api.listSources(), []));
  return (
    <Screen
      title="Источники"
      lead="Группы и каналы, по которым идёт поиск в режиме «Мои источники»."
    >
      <ScreenStub
        owner="Э-Источники"
        folder="src/screens/sources"
        refs="П5; П9, П13; ТЗ-Ф15, Ф16; НТ-7, НТ-14"
        items={[
          'Список с площадкой, типом и районом; поиск по списку',
          'Добавить по ссылке с проверкой: доступна, закрыта, не та площадка, уже есть, не краевой',
          'Правка, удаление с «Отменить», импорт из Excel с отчётом',
          'Первый запуск: предложение готового каталога краевых источников',
        ]}
      >
        {sources.status === 'loading' && <Skeleton height={18} width="40%" />}
        {sources.data && (
          <>
            <p>В списке {formatCount(sources.data.length, WORDS.source)}.</p>
            <p>
              {sources.data.slice(0, 6).map((s) => (
                <Chip key={s.id} size="sm">
                  {PLATFORMS[s.platform].short} · {s.name} · {SOURCE_TYPE_LABEL[s.type]}
                </Chip>
              ))}
            </p>
          </>
        )}
      </ScreenStub>
    </Screen>
  );
}
