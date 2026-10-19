/**
 * TODO(Э-Поиск): экран «Поиск» — П1 (поле, период, режим, регион, «как система
 * поняла тему»), П2 (ход поиска), П3 (подборка, карточка, фильтры, режим копий,
 * предпросмотр XLSX), П7 (пусто, частичный сбой, ошибка, нет связи, нейросеть
 * недоступна, очередь, другой регион). Бриф: docs/09-mockup-brief.md.
 *
 * Ниже — временная демонстрация контракта (useSearchRun + StatusLine), чтобы было
 * видно, что имитация работает. Замените её целиком.
 */
import { useEffect, useState } from 'react';
import { demoQueries, useSearchRun } from '@/api';
import type { PeriodPreset, SearchMode } from '@/api/types';
import { ScreenStub } from '@/app/ScreenStub';
import { useNavigation, type ScreenProps } from '@/app/navigation';
import { Button, Chip, Screen, StatusLine, TextArea, ToggleGroup } from '@/components';
import { formatPublishedAt } from '@/lib/format';
import { PLATFORMS, RELEVANCE_SHORT } from '@/lib/labels';
import styles from './search.module.css';

const PERIODS: { value: PeriodPreset; label: string }[] = [
  { value: 'today', label: 'Сегодня' },
  { value: '7d', label: '7 дней' },
  { value: '30d', label: '30 дней' },
];

function periodFor(preset: PeriodPreset) {
  const to = '2026-10-19';
  const from = preset === 'today' ? to : preset === '7d' ? '2026-10-13' : '2026-09-20';
  return { preset, from, to };
}

export default function SearchScreen({ params, navKey }: ScreenProps<'search'>) {
  const { navigate } = useNavigation();
  const { state, start, stop, retryPlatform } = useSearchRun();
  const [text, setText] = useState(params.text ?? demoQueries[0]?.text ?? '');
  const [preset, setPreset] = useState<PeriodPreset>('30d');
  const [mode, setMode] = useState<SearchMode>('everywhere');

  // Новый переход на экран с параметрами: подставить текст или сразу искать.
  useEffect(() => {
    if (params.request) {
      setText(params.request.text);
      if (params.autoRun) start(params.request, { replace: true });
    } else if (params.text !== undefined) {
      setText(params.text);
      if (params.autoRun)
        start(
          { text: params.text, period: periodFor('30d'), mode: 'everywhere' },
          { replace: true },
        );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- реагируем только на новый переход
  }, [navKey]);

  const running = state.phase === 'running' || state.phase === 'queued';
  const releaseGroup = state.groups.find((g) => g.kind === 'release');

  return (
    <Screen title="Поиск" lead="Тема, событие, человек или текст новости — в одном поле.">
      <ScreenStub
        owner="Э-Поиск"
        folder="src/screens/search"
        refs="П1–П3, П7; НТ-1…НТ-6, НТ-11, НТ-13, НТ-19, НТ-21; Р4, Р5, Р9"
        items={[
          'Поле запроса с подсказками, период (кнопки и календарь), «Мои источники / Везде», значок региона',
          '«Как система поняла тему»: входит / не то, уточнение многозначного запроса',
          'Ход поиска: «VK: 18 из 40», «+5 новых — показать», «Остановить»',
          'Подборка: строка состояния, фильтры «Прямо / Косвенно / Спорно», режим копий, карточки',
          'Предпросмотр XLSX с листом «Сводка»; все состояния сценария 5',
        ]}
      >
        <TextArea
          label="Запрос (временная форма)"
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={2}
        />
        <div className={styles.row}>
          <ToggleGroup
            label="Период"
            items={PERIODS}
            value={preset}
            onValueChange={setPreset}
            size="sm"
          />
          <ToggleGroup
            label="Источники"
            items={[
              { value: 'everywhere', label: 'Везде' },
              { value: 'my-sources', label: 'Мои источники' },
            ]}
            value={mode}
            onValueChange={setMode}
            size="sm"
          />
          {running ? (
            <Button onClick={stop}>Остановить</Button>
          ) : (
            <Button
              variant="primary"
              onClick={() => start({ text, period: periodFor(preset), mode })}
            >
              Найти
            </Button>
          )}
        </div>
        {state.phase === 'queued' && state.queue && (
          <p>Вы в очереди: перед вами {state.queue.ahead}.</p>
        )}
        {state.connectionLost && <p role="status">{state.connectionLost}</p>}
        {state.error && <p role="alert">{state.error.message}</p>}
        {state.conditions && (
          <StatusLine
            conditions={state.conditions}
            statuses={state.statuses}
            total={state.counts?.total ?? 0}
            running={running}
            currentSource={state.currentSource}
            onRetry={retryPlatform}
            actions={
              releaseGroup && state.searchId ? (
                <Button
                  size="sm"
                  onClick={() =>
                    navigate('spread', {
                      searchId: state.searchId ?? undefined,
                      groupId: releaseGroup.id,
                    })
                  }
                >
                  Распространение
                </Button>
              ) : undefined
            }
          />
        )}
        {state.items.length > 0 && (
          <ul className={styles.list}>
            {state.items.slice(0, 8).map((item) => (
              <li key={item.id}>
                <Chip size="sm">{RELEVANCE_SHORT[item.relevance]}</Chip>{' '}
                {PLATFORMS[item.publication.platform].short} · {item.publication.source.name} ·{' '}
                {formatPublishedAt(item.publication)} — {item.publication.headline}
              </li>
            ))}
            {state.items.length > 8 && <li>…и ещё {state.items.length - 8}</li>}
          </ul>
        )}
      </ScreenStub>
    </Screen>
  );
}
