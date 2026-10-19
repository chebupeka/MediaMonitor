/**
 * Панель «Демо-сценарий» — ТОЛЬКО В МОКАПЕ. Переключает состояния имитации,
 * предпросмотр боковой панели и даёт готовые демо-запросы. В продукте её нет.
 */
import { ChevronDown, FlaskConical, LayoutGrid, Newspaper } from 'lucide-react';
import { Collapsible, RadioGroup } from 'radix-ui';
import { useEffect, useId, useState, useSyncExternalStore } from 'react';
import { demoQueries } from '@/api';
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
            <span className={styles.triggerValue}>{current?.label ?? 'Обычно'}</span>
          </span>
          <span className={styles.mockOnly}>только в мокапе</span>
          <ChevronDown aria-hidden="true" className={styles.chevron} />
        </Collapsible.Trigger>

        <Collapsible.Content className={styles.content}>
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
