/**
 * Панель «Демо-сценарий» — ТОЛЬКО В МОКАПЕ. Откуда данные (имитация или сервер),
 * состояния имитации, предпросмотр боковой панели и готовые демо-запросы. В продукте её нет.
 */
import { ChevronDown, FlaskConical, LayoutGrid, Newspaper, Server } from 'lucide-react';
import { Collapsible, RadioGroup } from 'radix-ui';
import { useEffect, useId, useState, useSyncExternalStore } from 'react';
import { dataSource, demoQueries } from '@/api';
import {
  BUILD_API_URL,
  IN_EXTENSION,
  chooseDataSource,
  normalizeApiUrl,
  suggestedApiUrl,
  type DataSource,
} from '@/api/source';
import {
  DEMO_SCENARIOS,
  MAX_FAILURES,
  getDemoState,
  setDemoState,
  subscribeDemo,
  type DemoScenario,
  type MaxFailure,
} from '@/api/fake/scenario';
import { Button, ToggleGroup, cx } from '@/components';
import { useNavigation } from './navigation';
import { useShell, type Layout } from './shell-state';
import styles from './DemoPanel.module.css';

const OPEN_KEY = 'mm-mockup-demo-panel-open';

function useDemoState() {
  return useSyncExternalStore(subscribeDemo, getDemoState);
}

function loadOpen(): boolean {
  try {
    return window.localStorage.getItem(OPEN_KEY) === '1';
  } catch {
    return false;
  }
}

/** Демо-запросы, которые сразу запускают поиск. Подсказки и ссылку — только подставляют. */
const AUTO_RUN = new Set(['bdd', 'release', 'event', 'region']);

/**
 * «Данные: имитация / сервер (адрес)». Выбор хранится в браузере; применение
 * перезагружает страницу (src/api/source.ts). В расширении адрес задаёт сборка
 * (VITE_API_URL): политика безопасности пускает только к нему.
 */
function DataSourcePicker() {
  const baseId = useId();
  const [kind, setKind] = useState<DataSource['kind']>(dataSource.kind);
  const [address, setAddress] = useState(
    dataSource.kind === 'server' ? dataSource.url : suggestedApiUrl(),
  );
  const serverUnavailable = IN_EXTENSION && !BUILD_API_URL;
  const url = normalizeApiUrl(address);
  const next: DataSource | null =
    kind === 'fake' ? { kind: 'fake' } : url ? { kind: 'server', url } : null;
  const changed =
    next !== null &&
    (next.kind !== dataSource.kind ||
      (next.kind === 'server' && dataSource.kind === 'server' && next.url !== dataSource.url));
  const addressError =
    kind === 'server' && !url ? 'Нужен адрес вида http://127.0.0.1:8000' : undefined;

  return (
    <fieldset className={styles.group}>
      <legend className={styles.legend}>Данные</legend>
      <RadioGroup.Root
        className={styles.radios}
        value={kind}
        onValueChange={(value) => setKind(value as DataSource['kind'])}
        aria-label="Откуда данные"
      >
        <div className={styles.radio}>
          <RadioGroup.Item
            value="fake"
            id={`${baseId}-fake`}
            className={styles.radioItem}
            aria-describedby={`${baseId}-fake-hint`}
          >
            <RadioGroup.Indicator className={styles.radioDot} />
          </RadioGroup.Item>
          <span className={styles.radioText}>
            <label htmlFor={`${baseId}-fake`} className={styles.radioLabel}>
              Имитация
            </label>
            <span id={`${baseId}-fake-hint`} className={styles.radioHint}>
              Демо-данные мокапа и сценарии ниже
            </span>
          </span>
        </div>
        <div className={styles.radio}>
          <RadioGroup.Item
            value="server"
            id={`${baseId}-server`}
            className={styles.radioItem}
            disabled={serverUnavailable}
            aria-describedby={`${baseId}-server-hint`}
          >
            <RadioGroup.Indicator className={styles.radioDot} />
          </RadioGroup.Item>
          <span className={styles.radioText}>
            <label htmlFor={`${baseId}-server`} className={styles.radioLabel}>
              Сервер
            </label>
            <span id={`${baseId}-server-hint`} className={styles.radioHint}>
              {serverUnavailable
                ? 'Расширение собрано без адреса сервера (VITE_API_URL)'
                : 'Настоящий API: рабочее место, поиск, выгрузка XLSX'}
            </span>
          </span>
        </div>
      </RadioGroup.Root>
      {kind === 'server' && !serverUnavailable && (
        <div className={styles.failure}>
          <label htmlFor={`${baseId}-url`} className={styles.smallLabel}>
            Адрес сервера
          </label>
          <input
            id={`${baseId}-url`}
            className={styles.select}
            type="url"
            inputMode="url"
            spellCheck={false}
            autoComplete="off"
            value={address}
            readOnly={IN_EXTENSION}
            aria-invalid={addressError ? true : undefined}
            aria-describedby={addressError ? `${baseId}-url-error` : undefined}
            onChange={(e) => setAddress(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && changed && next) chooseDataSource(next);
            }}
          />
          {addressError && (
            <span id={`${baseId}-url-error`} className={styles.smallLabel}>
              {addressError}
            </span>
          )}
        </div>
      )}
      {changed && next && (
        <Button
          size="sm"
          variant="secondary"
          iconStart={<Server />}
          onClick={() => chooseDataSource(next)}
        >
          Применить
        </Button>
      )}
      <p className={styles.note}>
        Сейчас: {dataSource.kind === 'server' ? `сервер ${dataSource.url}` : 'имитация'}. Смена
        источника перезагружает страницу.
      </p>
    </fieldset>
  );
}

export function DemoPanel() {
  const demo = useDemoState();
  const { layout, setLayout } = useShell();
  const { navigate } = useNavigation();
  const [open, setOpen] = useState(loadOpen);
  const failureId = useId();
  const current = DEMO_SCENARIOS.find((s) => s.id === demo.scenario);

  useEffect(() => {
    try {
      window.localStorage.setItem(OPEN_KEY, open ? '1' : '0');
    } catch {
      // без запоминания
    }
  }, [open]);

  return (
    <Collapsible.Root open={open} onOpenChange={setOpen} asChild>
      <aside
        className={cx(styles.panel, open && styles.open)}
        aria-label="Демо-сценарий — только в мокапе"
      >
        <Collapsible.Trigger className={styles.trigger}>
          <FlaskConical aria-hidden="true" className={styles.triggerIcon} />
          <span className={styles.triggerText}>
            <span className={styles.triggerTitle}>Демо-сценарий</span>
            <span className={styles.triggerValue}>
              {dataSource.kind === 'server' ? 'Сервер' : (current?.label ?? 'Обычно')}
            </span>
          </span>
          <span className={styles.mockOnly}>только в мокапе</span>
          <ChevronDown aria-hidden="true" className={styles.chevron} />
        </Collapsible.Trigger>

        <Collapsible.Content className={styles.content}>
          <DataSourcePicker />

          {dataSource.kind === 'server' ? (
            <div className={styles.group}>
              <span className={styles.legend}>Состояние имитации</span>
              <p className={styles.note}>
                Сценарии работают только на имитации. Сбои площадок на сервере задаёт его настройка
                FIXTURE_FAILURES (server/README.md).
              </p>
            </div>
          ) : (
            <fieldset className={styles.group}>
              <legend className={styles.legend}>Состояние имитации</legend>
              <RadioGroup.Root
                className={styles.radios}
                value={demo.scenario}
                onValueChange={(value) => setDemoState({ scenario: value as DemoScenario })}
                aria-label="Демо-сценарий"
              >
                {DEMO_SCENARIOS.map((s) => (
                  <div key={s.id} className={styles.radio}>
                    <RadioGroup.Item
                      value={s.id}
                      id={`${failureId}-${s.id}`}
                      className={styles.radioItem}
                      aria-describedby={`${failureId}-${s.id}-hint`}
                    >
                      <RadioGroup.Indicator className={styles.radioDot} />
                    </RadioGroup.Item>
                    <span className={styles.radioText}>
                      <label htmlFor={`${failureId}-${s.id}`} className={styles.radioLabel}>
                        {s.label}
                      </label>
                      <span id={`${failureId}-${s.id}-hint`} className={styles.radioHint}>
                        {s.hint}
                      </span>
                    </span>
                  </div>
                ))}
              </RadioGroup.Root>
              {demo.scenario === 'max-down' && (
                <div className={styles.failure}>
                  <label htmlFor={failureId} className={styles.smallLabel}>
                    Что случилось с MAX
                  </label>
                  <select
                    id={failureId}
                    className={styles.select}
                    value={demo.maxFailure}
                    onChange={(e) => setDemoState({ maxFailure: e.target.value as MaxFailure })}
                  >
                    {MAX_FAILURES.map((f) => (
                      <option key={f.id} value={f.id}>
                        {f.label}
                      </option>
                    ))}
                  </select>
                </div>
              )}
              <p className={styles.note}>При смене сценария экраны загружаются заново.</p>
            </fieldset>
          )}

          <div className={styles.group}>
            <span className={styles.legend}>Предпросмотр</span>
            <ToggleGroup<Layout>
              label="Предпросмотр"
              size="sm"
              fullWidth
              items={[
                { value: 'site', label: 'Сайт' },
                { value: 'panel', label: 'Боковая панель' },
              ]}
              value={layout}
              onValueChange={setLayout}
            />
            <div className={styles.links}>
              <Button
                size="sm"
                variant="ghost"
                iconStart={<Newspaper />}
                onClick={() => navigate('demo-page')}
              >
                Демо-страница СМИ
              </Button>
              <Button
                size="sm"
                variant="ghost"
                iconStart={<LayoutGrid />}
                onClick={() => navigate('gallery')}
              >
                Компоненты
              </Button>
            </div>
          </div>

          <div className={styles.group}>
            <span className={styles.legend}>Демо-запросы</span>
            <ul className={styles.queries}>
              {demoQueries.map((q) => (
                <li key={q.id}>
                  <button
                    type="button"
                    className={styles.query}
                    onClick={() => {
                      setOpen(false);
                      navigate('search', { text: q.text, autoRun: AUTO_RUN.has(q.id) });
                    }}
                  >
                    {q.label}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </Collapsible.Content>
      </aside>
    </Collapsible.Root>
  );
}
