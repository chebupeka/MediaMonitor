/**
 * Демо-сценарий — ТОЛЬКО В МОКАПЕ. Переключается панелью «Демо-сценарий»
 * (src/app/DemoPanel.tsx); имитация читает его при каждом вызове.
 * В продукте этого файла нет (Р11 п. 3: никакой имитации в продукте).
 */

export type DemoScenario =
  | 'normal'
  | 'empty'
  | 'max-down'
  | 'ai-down'
  | 'slow'
  | 'queue'
  | 'offline'
  | 'first-run'
  | 'large'
  | 'demo-platforms';

/** Вид сбоя MAX в сценарии «MAX недоступен» — чтобы показать полный набор статусов (НТ-3). */
export type MaxFailure =
  'unavailable' | 'bad-response' | 'rate-limited' | 'key-invalid' | 'quota-exhausted';

export interface DemoState {
  scenario: DemoScenario;
  maxFailure: MaxFailure;
}

export const DEMO_SCENARIOS: readonly { id: DemoScenario; label: string; hint: string }[] = [
  { id: 'normal', label: 'Обычно', hint: 'Все площадки отвечают, данные MAX с задержкой' },
  { id: 'empty', label: 'Пусто', hint: 'Ничего не найдено ни на одной площадке' },
  {
    id: 'max-down',
    label: 'MAX недоступен',
    hint: 'Частичный сбой: MAX с ошибкой, VK — одна группа закрыта',
  },
  {
    id: 'ai-down',
    label: 'Нейросеть недоступна',
    hint: 'Спорные получают «не проверено ИИ»; проверка текста на ИИ недоступна',
  },
  { id: 'slow', label: 'Медленно', hint: 'Поиск идёт ~25 секунд: видно ход и «Остановить»' },
  { id: 'queue', label: 'Очередь', hint: 'Перед вами 2 поиска' },
  { id: 'offline', label: 'Нет связи', hint: 'Связь пропадает на 6 секунд, поиск продолжается' },
  { id: 'first-run', label: 'Первый запуск', hint: 'Список источников пуст' },
  { id: 'large', label: '500 результатов', hint: 'Большая подборка на любой запрос' },
  {
    id: 'demo-platforms',
    label: 'Демо-площадки',
    hint: 'Как на стенде: ВКонтакте живой, OK и MAX — записанные примеры без ссылок',
  },
];

export const MAX_FAILURES: readonly { id: MaxFailure; label: string }[] = [
  { id: 'unavailable', label: 'не отвечает' },
  { id: 'bad-response', label: 'непонятный ответ' },
  { id: 'rate-limited', label: 'ограничение частоты' },
  { id: 'key-invalid', label: 'ключ недействителен' },
  { id: 'quota-exhausted', label: 'квота исчерпана' },
];

const STORAGE_KEY = 'mm-mockup-demo';
const DEFAULT_STATE: DemoState = { scenario: 'normal', maxFailure: 'unavailable' };

function isScenario(value: unknown): value is DemoScenario {
  return DEMO_SCENARIOS.some((s) => s.id === value);
}

function isMaxFailure(value: unknown): value is MaxFailure {
  return MAX_FAILURES.some((f) => f.id === value);
}

function load(): DemoState {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_STATE;
    const parsed = JSON.parse(raw) as Partial<Record<keyof DemoState, unknown>>;
    return {
      scenario: isScenario(parsed.scenario) ? parsed.scenario : DEFAULT_STATE.scenario,
      maxFailure: isMaxFailure(parsed.maxFailure) ? parsed.maxFailure : DEFAULT_STATE.maxFailure,
    };
  } catch {
    return DEFAULT_STATE;
  }
}

let state: DemoState = load();
const listeners = new Set<(next: DemoState, prev: DemoState) => void>();

export function getDemoState(): DemoState {
  return state;
}

export function setDemoState(patch: Partial<DemoState>): void {
  const prev = state;
  state = { ...state, ...patch };
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // хранилище недоступно (приватный режим) — работаем без запоминания
  }
  listeners.forEach((listener) => listener(state, prev));
}

export function subscribeDemo(listener: (next: DemoState, prev: DemoState) => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
