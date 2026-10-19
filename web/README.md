# Медиамонитор — кликабельный мокап (web/)

Фиктивный сайт без бэкенда: точный визуал и имитация работы на демо-данных
(`docs/09-mockup-brief.md`). Потом этот же код станет интерфейсом продукта: имитацию
заменим настоящим API в одном файле (`src/api/instance.ts`), экраны не меняются.

## Запуск

Нужен Node.js 20.19+ (проверено на 24).

```bash
cd web
npm install
npm run dev            # http://localhost:5173
npm run typecheck      # TypeScript strict, без any
npm run lint           # ESLint: typescript-eslint, react-hooks, jsx-a11y; 0 предупреждений
npm run format         # Prettier
npm run build          # обычная сборка в dist/
npm run build:single   # всё в один файл dist/index.html (его публикуем для команды)
```

`dist/index.html` после `build:single` открывается двойным щелчком, без сервера.
Внешние запросы — только к Google Fonts; без сети сработают системные шрифты.

**Подсказки в адресе — только для скриншотов и ручной проверки** (навигация от адреса
не зависит): `index.html?screen=search&q=ДТП&theme=dark&layout=panel`.
`screen` — id экрана, `q` — сразу искать, `theme` — `light | dark | system`,
`layout` — `site | panel`.

## Расширение

Тот же интерфейс в боковой панели браузера (Manifest V3, WXT). Подробно — `extension/README.md`.

```bash
npm run ext:build      # → .output/chrome-mv3/: «Загрузить распакованное» в Chrome или Яндекс Браузере
npm run ext:zip        # → .output/*.zip
npm run ext:dev        # разработка с автообновлением
```

## Структура

```
web/
  index.html               шрифты Google Fonts, корень
  vite.config.ts           alias @ → src, режим single → vite-plugin-singlefile
  wxt.config.ts            сборка расширения: манифест, разрешения, srcDir = src
  eslint.config.js         правила, в т.ч. запрет dangerouslySetInnerHTML и импорта из api/fake
  extension/               расширение: фон, боковая панель, вкладка, значки (extension/README.md)
  src/
    main.tsx
    styles/tokens.css      ВСЕ дизайн-токены, светлая и тёмная тема
    styles/base.css        сброс, шрифт, видимый фокус, .sr-only
    api/
      types.ts             контракт предметной области (подробные комментарии)
      client.ts            интерфейс MonitorApi, MonitorApiError, isApiError
      hooks.ts             useSearchRun, useAsync, useConnection
      instance.ts          выбор реализации (сейчас имитация)
      index.ts             точка входа: import { api, useSearchRun } from '@/api'
      fake/                имитация — ТОЛЬКО МОКАП (сценарии, наборы, ход поиска)
    lib/
      format.ts            даты по Красноярску, числа, «15 размещений»
      labels.ts            подписи: площадки, метки, методы, статусы площадок (НТ-3)
      highlight.ts         подсветка доказательства в выдержке (П3)
    components/            базовые компоненты (Radix UI + токены)
    app/                   оболочка: навигация, шапка, панель «Демо-сценарий», витрина
    dots/                  слот «Точки»: DotsScene (сейчас статичная SVG-карта края)
    screens/
      landing/             Л. Лендинг (заготовка «Основы»)
      search/              П1–П3, П7        → Э-Поиск
      spread/              П4               → Э-Распространение
      sources/             П5               → Э-Источники
      recent/              П6               → Э-Источники
      how/                 П8               → Э-Источники
      status/              П9               → Э-Источники
      demo-page/           демо-страница СМИ, HostPage → Э-Расширение
  screenshots/             скриншоты проверки (в git не идут)
```

## Правила для исполнителей

**Чья папка.** Каждый работает только в своей папке:

| Исполнитель       | Папка                                                | Что                                                                     |
| ----------------- | ---------------------------------------------------- | ----------------------------------------------------------------------- |
| Э-Поиск           | `src/screens/search/`                                | П1, П2, П3, карточка, предпросмотр XLSX, П7                             |
| Э-Распространение | `src/screens/spread/`                                | П4                                                                      |
| Э-Источники       | `src/screens/sources/`, `recent/`, `how/`, `status/` | П5, П6, П8, П9                                                          |
| Э-Точки           | `src/dots/`                                          | Three.js-слой и запасные варианты; интерфейс `DotsSceneProps` не менять |
| Э-Расширение      | `src/screens/demo-page/`                             | демо-страница СМИ; экспорт `HostPage` обязателен                        |

**Не трогать** (меняет только «Основа» или лид — напишите лиду, что нужно):
`package.json`, конфиги, `src/api/**`, `src/components/**`, `src/styles/**`, `src/lib/**`,
`src/app/**`, `src/screens/landing/**`. Нужен новый общий компонент, поле контракта,
демо-набор или зависимость — запрос лиду.

**Экран.** `src/screens/<имя>/index.tsx` экспортирует компонент по умолчанию и получает
`ScreenProps<'имя'>`: `params` (параметры перехода), `navKey` (растёт при каждом переходе —
реагируйте на него, а не на монтирование), `active` (экран виден). Посещённые экраны
остаются в памяти скрытыми, поэтому поиск не теряется при переходе в «Источники» и обратно.
Плашку `ScreenStub` удалите, когда соберёте экран. Внутри — свои CSS-модули и подкомпоненты.

**Навигация** — `useNavigation().navigate('spread', { searchId, groupId })`. Адресной строки
нет. Параметры экранов описаны в `src/app/navigation.tsx` (`ScreenParamsMap`).

**Оболочка** — `useShell()` из `@/app/shell-state`: `layout` (`site` | `panel`),
`resolvedTheme`, `dotsEnabled`, `reducedMotion`, `setLayout`.

**Стили — только токены.** Никаких цветов, шрифтов, размеров, отступов, радиусов и
длительностей литералами: `var(--color-ink-2)`, `var(--space-4)`, `var(--radius-lg)`.
Визуал предварительный: палитру поменяем в одном файле. Нет нужного токена — попросите.

**Узкая раскладка (боковая панель 380 px, увеличение 200 %)** — контейнерные запросы,
не медиазапросы: `<main>` — контейнер `screen`.

```css
@container screen (max-width: 560px) {
  .table {
    display: none;
  }
  .cards {
    display: grid;
  }
}
```

**Доступность (НТ-16):** весь путь с клавиатуры; не убирайте фокус; цели ≥ 24×24 px;
статусы и метки — значок + текст (`StatusBadge`); ход и итог поиска — `useAnnounce()`;
анимации — только под `prefers-reduced-motion: no-preference`; у кнопки-значка — `label`.

**Безопасность текста (НТ-9):** тексты постов и названия групп выводим только как текст.
`dangerouslySetInnerHTML` запрещён линтером. Подсветка — через `excerptSegments()`.

**Даты и подписи** — только через `@/lib/format` и `@/lib/labels`: время везде красноярское,
с подписью «время красноярское» (НТ-12); «дата неизвестна» вместо пустоты (ТЗ-Ф36).

**Состояния.** У каждого экрана: загрузка (`Skeleton`), пусто (`EmptyState`), частично,
ошибка (`ErrorState`), успех. Все переключаются панелью «Демо-сценарий».

**Перед сдачей:** `npm run typecheck`, `npm run lint`, `npm run build:single` — без ошибок и
предупреждений; посмотреть экран в светлой и тёмной теме, на сайте и в боковой панели.

## Контракт API

Экраны работают только через `@/api` и типы `@/api/types`. Импорт из `@/api/fake` запрещён
линтером.

```ts
import { api, useSearchRun, useAsync, errorMessage } from '@/api';
import type { ResultItem, Selection } from '@/api/types';
```

`MonitorApi` (`src/api/client.ts`):

| Группа          | Методы                                                                                                                                                                                           |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| старт           | `getStartState()` — первый запуск, пример запроса, период по умолчанию (НТ-14)                                                                                                                   |
| запрос          | `analyzeQuery(text)` — подсказки и уточнение (НТ-21, П14, НТ-26); `understandTopic(text, {meaningId, correction})` — «как система поняла тему»                                                   |
| поиск           | `startSearch(request)` → `SearchRun` (поток событий); `stopSearch`; `retryPlatform(searchId, platform)`; `getSelection`; `setExcluded`; `excludeSource`; `addByUrl` (П8); `recheckLinks` (НТ-19) |
| распространение | `getSpread(searchId, groupId?)` (Р10, П1, П4–П6)                                                                                                                                                 |
| выгрузка        | `getExportPreview(searchId, {onlyRelevance?})` — лист «Сводка» и строки (НТ-11, НТ-20)                                                                                                           |
| источники       | `listSources`, `checkSource(url)`, `addSource`, `updateSource`, `removeSource`, `restoreSource`, `importSources(file)`, `getCatalog`, `addFromCatalog`                                           |
| недавние        | `listRecent()` — повтор: `startSearch({ ...r.request, repeatOf: r.searchId })`                                                                                                                   |
| стенд           | `getStandStatus()` (П9, НТ-18)                                                                                                                                                                   |
| связь           | `getConnection()`, `onConnectionChange()` (НТ-23)                                                                                                                                                |

Ошибки — `MonitorApiError` (`code`, `message`); сбои площадок — внутри статусов, не исключением.

**Ключевые сущности** (`src/api/types.ts`): `SearchRequest`, `SearchConditions` (условия
ВЫПОЛНЕННОГО поиска, НТ-1), `QueryAnalysis`, `TopicUnderstanding`, `PlatformStatus` (полный
набор состояний НТ-3 + `freshness` НТ-4 + `cap`), `Publication` (единица учёта НТ-13: ключ,
склеенные адреса, репост, «текст отсутствует», `fetchedAt` НТ-19), `ResultItem` (метка, метод
отбора, причина региона Р4, выдержка, доказательство-предложение Р5/П3, тип размещения П2,
полнота цитирования П1, исключение, «новое»), `ResultGroup`, `Selection`, `SelectionCounts`,
`SearchEvent` / `SearchRun`, `SpreadReport` (честные `ReachMetric` П5, волна П6, первоисточник
с надёжностью времени П4), `ExportPreview`, `Source` / `SourceCheck` / `CatalogSource`,
`RecentSearch`, `StandStatus`.

**Поток хода поиска.** `SearchRun` — и `AsyncIterable`, и подписка; поздний подписчик
получает всю историю. Обычно хватает хука:

```tsx
const { state, start, stop, retryPlatform, setExcluded } = useSearchRun();
start({ text, period, mode }); // второй поиск не запустится, пока идёт первый (НТ-2)
state.phase; // idle | queued | running | done | stopped | failed
state.items; // в порядке прихода; поле arrival — для «+5 новых — показать»
state.statuses; // для <StatusLine statuses=… />
state.conditions; // условия выполненного поиска
```

Загрузка простых данных: `const sources = useAsync(useCallback(() => api.listSources(), []));`
→ `sources.status`, `sources.data`, `sources.error`, `sources.reload()`.

## Имитация и демо-данные

Источники вымышленные, города края настоящие, «сейчас» = 19 октября 2026, 14:32 по
Красноярску (часы идут от этого момента). Выдержки — подстроки текста, номера
предложений-доказательств указывают на реальные предложения; в режиме разработки наборы
проверяются автоматически (`validateItems`, предупреждение в консоли).

| Запрос                               | Набор                                                                                                                                                                                                                                                                                         |
| ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| БДД, ДТП, пешеход, водитель, дорожн… | «Безопасность дорожного движения»: 40 записей (прямо 24 / косвенно 10 / спорно 6), группа копий, репост, пост без текста, без даты, найденный по двум адресам. Ловушка «пожарная безопасность» (6 постов) отсечена и видна в «как система поняла тему»; перенос грани в «входит» добавляет их |
| «школ» + «Норильск» (текст релиза)   | Релиз «Новая школа в Норильске»: 15 размещений (VK 9, OK 4, MAX 2), дословно / сокращено / пересказ / репост, полнота цитирования, фрагменты; + отклик и спорная запись                                                                                                                       |
| «Енисей»                             | Многозначный запрос: уточнение «река / клуб / всё»; 8 + 3 записи                                                                                                                                                                                                                              |
| Новосибирск, Иркутск… без мест края  | Пусто с пояснением «поиск ограничен Красноярским краем» (НТ-26)                                                                                                                                                                                                                               |
| всё остальное                        | Пусто                                                                                                                                                                                                                                                                                         |

Период и режим «Мои источники» реально фильтруют набор. Пост вне периода для «добавить по
ссылке»: `demoLinks.addByUrl`. Ссылки для проверки источника (ок, закрыт, не краевой,
не та площадка, дубль) — `demoLinks` из `@/api`. Примеры запросов — `demoQueries`.

**Панель «Демо-сценарий»** (слева внизу, «только в мокапе»): обычно / пусто / MAX недоступен
(+ вид сбоя: не отвечает, непонятный ответ, ограничение частоты, ключ, квота) / нейросеть
недоступна / медленно (~25 с) / очередь / нет связи (6 с) / первый запуск (пустой список
источников) / 500 результатов. При смене сценария экраны загружаются заново. Там же —
предпросмотр «Боковая панель», демо-страница СМИ, витрина компонентов и демо-запросы.

**Как добавить демо-набор** (делает «Основа» или лид):

1. `src/api/fake/datasets/<имя>.ts`: массив `PostSpec` (текст — массив предложений;
   `ev` — номер предложения-доказательства или `marks` — фразы для подсветки) и функция,
   возвращающая `Dataset`.
2. Правило выбора — в `pickDataset()` в `src/api/fake/query.ts`.
3. Новые источники — в `src/api/fake/sources.ts` (вымышленные названия, реальные города).
4. Открыть `npm run dev` и убедиться, что в консоли нет «нарушения контракта».

## Токены

`src/styles/tokens.css`: поверхности (`--color-bg`, `--color-surface`, `-2`, `-3`), текст в
три уровня (`--color-ink`, `-2`, `-3`), линии, управляющий цвет (`--color-control*`),
семантика (`--color-{good|warning|critical|info}-{ink|bg|solid}`), площадки
(`--color-vk|ok|max` и `-bg`), точки (`--color-dots-*`), пометка демо (`--color-note-*`),
подсветка (`--color-mark-*`); шрифты (`--font-ui` Golos Text, `--font-display` Unbounded —
только крупные цифры и заголовки бренда), шкала `--text-*`, `--leading-*`, `--weight-*`;
отступы `--space-*` (шаг 4 px); `--radius-*`; `--shadow-*`; `--duration-*` и `--ease-*`
(обнуляются при «уменьшить движение»); `--z-*`; размеры (`--target-min`, `--control-h-*`,
`--panel-width`). Тёмная тема — по системной настройке и переключателем (`data-theme` на
`<html>`); `data-scope="dark"` делает тёмным участок страницы.

## Компоненты (`src/components`)

`Button`, `IconButton`, `Chip` (метка или фильтр-переключатель со счётчиком), `ToggleGroup`,
`StatusBadge` / `StatusBadgeFromView` (значок + текст), `PlatformDot` / `PlatformLabel`,
`StatusLine` (условия, «Найдено N», статус каждой площадки, «Повторить», пояснения,
плашка «Условия изменены»), `Card` + `CardHeader` / `CardMeta` / `CardBody` / `CardFooter`,
`Dialog` / `DialogClose`, `useToast()` (`toast.undo(title, onUndo)` — «Отменить», 12 с;
любое уведомление ≥ 10 с), `Tooltip`, `EmptyState`, `ErrorState`, `Skeleton` /
`SkeletonText`, `LiveRegion` / `useAnnounce()`, `TextField` / `TextArea`, `DemoBadge`,
`Screen` / `Section` (каркас экрана). Живые примеры — экран «Компоненты» в панели
«Демо-сценарий».

Слот «Точки» (`@/dots`):

```tsx
<DotsScene form="krai" intensity="full" />
<DotsScene form="found" intensity="calm" cities={[{ city: 'Норильск', count: 4, platform: 'vk' }]} />
```

Формы: `krai | listening | searching | found | spread | empty | failure | export`.
