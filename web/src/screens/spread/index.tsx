/**
 * TODO(Э-Распространение): экран «Распространение» (П4, Р10) — первоисточник
 * с надёжностью времени, честные цифры охвата, волна по часам и дням, хронология
 * по площадкам, полнота цитирования и карта фрагментов релиза, таблица размещений
 * с сортировкой, точки (вспышка из источника, спокойная версия).
 * Набросок: docs/visuals/rasprostranenie.html. Данные: `api.getSpread(searchId, groupId)`.
 *
 * Ниже — временная демонстрация контракта. Замените её целиком.
 */
import { useCallback, useEffect, useState } from 'react';
import { api, demoQueries, errorMessage, useSearchRun } from '@/api';
import type { SpreadReport } from '@/api/types';
import { ScreenStub } from '@/app/ScreenStub';
import type { ScreenProps } from '@/app/navigation';
import { Button, Screen } from '@/components';
import { formatCompact, formatDateTime } from '@/lib/format';

export default function SpreadScreen({ params, navKey }: ScreenProps<'spread'>) {
  const { state, start } = useSearchRun();
  const [report, setReport] = useState<SpreadReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback((searchId: string, groupId?: string) => {
    setError(null);
    api.getSpread(searchId, groupId).then(setReport, (e: unknown) => setError(errorMessage(e)));
  }, []);

  const runText = useCallback(
    (text: string) => {
      setReport(null);
      start(
        {
          text,
          period: { preset: '7d', from: '2026-10-13', to: '2026-10-19' },
          mode: 'everywhere',
        },
        { replace: true },
      );
    },
    [start],
  );

  useEffect(() => {
    if (params.searchId) load(params.searchId, params.groupId);
    else if (params.text) runText(params.text);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- реагируем только на новый переход
  }, [navKey]);

  useEffect(() => {
    if (state.phase === 'done' && state.searchId) load(state.searchId);
  }, [state.phase, state.searchId, load]);

  const releaseText = demoQueries.find((q) => q.id === 'release')?.text ?? '';

  return (
    <Screen
      title="Распространение новости"
      lead="Куда и как широко разошлась новость: первоисточник, площадки, охват, хронология."
    >
      <ScreenStub
        owner="Э-Распространение"
        folder="src/screens/spread"
        refs="П4; Р10; П1, П2, П4, П5, П6; НТ-24"
        items={[
          'Первым опубликовал — с пометкой надёжности времени',
          'Размещений всего и по площадкам; подписчики и просмотры отдельно, «как посчитано»',
          'Волна по часам и дням, хронология по площадкам',
          'Полнота цитирования и карта фрагментов релиза',
          'Таблица размещений с сортировкой «по времени / по популярности»; точки-вспышка',
        ]}
      >
        {!report && state.phase !== 'running' && (
          <Button variant="primary" onClick={() => runText(releaseText)}>
            Показать демо: релиз «Новая школа в Норильске»
          </Button>
        )}
        {state.phase === 'running' && (
          <p role="status">Ищем размещения… найдено {state.counts?.total ?? 0}</p>
        )}
        {error && <p role="alert">{error}</p>}
        {report && (
          <ul>
            <li>
              «{report.title}»: {report.totals.placements} размещений · VK{' '}
              {report.totals.byPlatform.vk} · OK {report.totals.byPlatform.ok} · MAX{' '}
              {report.totals.byPlatform.max}
            </li>
            <li>
              Первым: {report.original.sourceName},{' '}
              {report.original.publishedAt
                ? formatDateTime(report.original.publishedAt)
                : 'дата неизвестна'}
            </li>
            <li>
              Аудитория источников: {formatCompact(report.audience.value)} · просмотры:{' '}
              {formatCompact(report.views.value)} (по {report.views.withData} из {report.views.of})
            </li>
          </ul>
        )}
      </ScreenStub>
    </Screen>
  );
}
