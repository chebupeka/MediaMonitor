/**
 * TODO(Э-Источники): страница состояния стенда для дежурного (П9, НТ-18):
 * площадки и квоты, нейросеть (прогрета ли), очередь, память, последние события.
 * Данные: api.getStandStatus(). Состояния меняются демо-сценарием.
 *
 * Ниже — временная демонстрация контракта. Замените её целиком.
 */
import { useCallback } from 'react';
import { api, useAsync } from '@/api';
import { ScreenStub } from '@/app/ScreenStub';
import type { ScreenProps } from '@/app/navigation';
import { Button, Screen, Skeleton, StatusBadge } from '@/components';
import { PLATFORMS } from '@/lib/labels';

const TONE = { ok: 'good', degraded: 'warning', down: 'critical' } as const;
const TEXT = { ok: 'работает', degraded: 'с ограничениями', down: 'не работает' } as const;

export default function StatusScreen(_props: ScreenProps<'status'>) {
  const stand = useAsync(useCallback(() => api.getStandStatus(), []));
  return (
    <Screen
      title="Состояние стенда"
      lead="Служебная страница для дежурного: что работает прямо сейчас."
      actions={<Button onClick={stand.reload}>Обновить</Button>}
    >
      <ScreenStub
        owner="Э-Источники"
        folder="src/screens/status"
        refs="П9; НТ-18; SC-68, SC-46"
        items={[
          'Площадки: статус, способ доступа, квоты',
          'Нейросеть: прогрета, очередь, скорость',
          'Очередь поисков и память',
          'Журнал последних событий',
        ]}
      >
        {stand.status === 'loading' && !stand.data && <Skeleton height={18} width="40%" />}
        {stand.data && (
          <p>
            <StatusBadge tone={TONE[stand.data.overall]}>
              Стенд: {TEXT[stand.data.overall]}
            </StatusBadge>{' '}
            {stand.data.platforms.map((p) => (
              <StatusBadge key={p.platform} tone={TONE[p.state]}>
                {PLATFORMS[p.platform].short}: {TEXT[p.state]}
              </StatusBadge>
            ))}{' '}
            <StatusBadge tone={TONE[stand.data.ai.state]}>
              Нейросеть: {TEXT[stand.data.ai.state]}
            </StatusBadge>
          </p>
        )}
      </ScreenStub>
    </Screen>
  );
}
