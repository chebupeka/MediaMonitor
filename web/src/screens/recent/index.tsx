/**
 * TODO(Э-Источники): экран «Недавние поиски» (П6, П12) — список с условиями,
 * временем и итогом; «Повторить» запускает новый поиск и помечает «новое».
 * Повтор: navigate('search', { request: { ...r.request, repeatOf: r.searchId }, autoRun: true }).
 *
 * Ниже — временная демонстрация контракта. Замените её целиком.
 */
import { useCallback } from 'react';
import { api, useAsync } from '@/api';
import { ScreenStub } from '@/app/ScreenStub';
import { useNavigation, type ScreenProps } from '@/app/navigation';
import { Button, Screen, Skeleton } from '@/components';
import { formatDateTime, formatPeriod } from '@/lib/format';

export default function RecentScreen(_props: ScreenProps<'recent'>) {
  const { navigate } = useNavigation();
  const recent = useAsync(useCallback(() => api.listRecent(), []));
  return (
    <Screen
      title="Недавние поиски"
      lead="Повторите вчерашний поиск одной кнопкой — новое будет помечено."
    >
      <ScreenStub
        owner="Э-Источники"
        folder="src/screens/recent"
        refs="П6; П12; SC-20"
        items={[
          'Список недавних поисков с условиями и итогом по площадкам',
          '«Повторить» — новый поиск с пометкой «новое»',
        ]}
      >
        {recent.status === 'loading' && <Skeleton height={18} width="50%" />}
        {recent.data?.map((r) => (
          <p key={r.searchId}>
            «{r.conditions.label}» · {formatPeriod(r.conditions.period)} ·{' '}
            {formatDateTime(r.conditions.startedAt)} · найдено {r.total}{' '}
            <Button
              size="sm"
              onClick={() =>
                navigate('search', {
                  request: { ...r.request, repeatOf: r.searchId },
                  autoRun: true,
                })
              }
            >
              Повторить
            </Button>
          </p>
        ))}
      </ScreenStub>
    </Screen>
  );
}
