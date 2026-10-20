# Сервер Медиамонитора

Поиск публикаций VK, Одноклассников и MAX по Красноярскому краю: ход поиска потоком SSE,
подборка с метками и доказательствами, «Распространение», выгрузка XLSX. Python 3.12,
FastAPI + Pydantic v2, SQLAlchemy 2 + Alembic, PostgreSQL 16 + pgvector.

Тот же сервер и порт раздают сайт-витрину на `/` (папка `site/`) и веб-версию панели на
`/app/` (сборка `web`): `/api/…` и `/health` — API, остальное — статика (`api/static.py`).

Устройство, модель данных, таблица «метод интерфейса → HTTP», лимиты и безопасность —
`docs/12-tech-design.md`. Контракт — `web/src/api/types.ts`: ответы сервера совпадают с ним
поле в поле (это проверяют тесты).

## Что работает, что заглушка

| Часть | Состояние |
|---|---|
| API всех 31 серверного метода `MonitorApi`, поток SSE, остановка, повтор площадки, очередь, восстановление после перезапуска | работает |
| Рабочее место по ссылке-ключу, источники, каталог края, импорт из Excel/CSV, «Недавние», выгрузка XLSX, «Распространение», страница стенда | работает |
| Данные площадок | **записанные примеры** (`DATA_SOURCE=fixtures`, вымышленные источники из мокапа); адаптеры VK, OK, MAX — заготовки с TODO |
| Отбор | **воронка «Э-Отбор»** (`server/matching`, пакет `mm_matching`): фразы → смысл (BERTA) → признаки события → нейросеть; результаты идут в поток по мере отбора; векторы постов кэшируются в базе. Устройство и замеры — `docs/12-tech-design.md` §11 |
| Модель смысла | BERTA на CPU сервера или сервис на компьютере с видеокартой (`EMBEDDINGS_URL`, папка `gpu-node/`) с откатом на CPU |
| Нейросеть | GigaChat 3.1 Lightning в Ollama по `OLLAMA_URL`; не задан или не отвечает — спорные «не проверено ИИ» |
| Сайт и веб-версия | `/` — `site/`, `/app/` — сборка `web` (`npm run build:web` → `dist-web/`, base `/app/`, `VITE_TARGET=web`, `VITE_API_URL=/`). Собирает Dockerfile (этап node), файлы — в памяти, `.br`/`.gz` заранее; хеш в имени — кэш на год, остальное — `no-cache` + ETag; CSP только на свой адрес, встроенные скрипты — по SHA-256; адрес без файла в `/app/` → `index.html` | работает |
| Проверка текста на ИИ | `POST /api/ai-check`, `aiCheck` у записей подборки (фоном) и размещений «Распространения», общий кэш `ai_checks`; клиент сервиса GigaCheck на gpu-node готов, сам сервис — после пробы. Без `AI_DETECT_URL` — «проверка недоступна» (при разработке на примерах — демо-оценка из хеша). `docs/12-tech-design.md` §13 |

## Запуск в Docker

```bash
cd server
cp .env.example .env          # задать POSTGRES_PASSWORD; OLLAMA_URL — адрес Ollama, если есть
docker compose up -d --build  # db → migrate (alembic upgrade head) → api
curl http://127.0.0.1:8000/health
docker compose --profile https up -d   # HTTPS через Caddy для DOMAIN из .env
docker compose down           # остановить (данные базы остаются в томе pgdata)
```

Порты базы (5432) и API (8000) открыты только на этом компьютере. API работает одним
процессом: поиски идут задачами внутри него, состояние — в базе.

Образ собирается **из корня репозитория** (`compose.yaml`: `context: ..`,
`dockerfile: server/Dockerfile`; что попадает в контекст — `Dockerfile.dockerignore`):
1. этап node: `npm ci` в `web/`, сборка веб-версии с `VITE_API_URL=/` (сервер на том же
   адресе) и `VITE_TARGET=web`, копия `site/`, сжатие `scripts/precompress.mjs` (brotli и gzip);
2. этап Python: как раньше, плюс `/app/static/site` и `/app/static/app`
   (`SITE_DIR`, `WEB_APP_DIR`).

Сборка Vite занимает ~1 с и ~0,4 ГБ памяти — на сервере команды (4 ГБ) собирается сама.
Без Docker: `SITE_DIR=../site WEB_APP_DIR=../web/dist-web uv run mediamonitor` после
`npm run build:web` в `web/` — сайт на http://127.0.0.1:8000/, веб-версия — на `/app/`.

## Запуск без Docker (разработка)

```bash
cd server
uv sync                                   # Python 3.12 и зависимости из uv.lock
docker compose up -d db                   # или свой PostgreSQL 16 с pgvector
# в .env: DATABASE_URL=postgresql+psycopg://mediamonitor:<пароль>@localhost:5432/mediamonitor
uv run alembic upgrade head               # миграции
uv run mediamonitor                       # http://127.0.0.1:8000, документация API — /docs
uv run python scripts/smoke.py            # сквозная проверка: поиск → поток → подборка → XLSX
```

### Сервер команды (2 vCPU / 4 ГБ, модели — на компьютере с видеокартой)

```bash
cd /opt/mediamonitor/app/server
docker compose -f compose.yaml -f compose.server.yaml up -d --build   # первый запуск
scripts/update-server.sh            # обновление: git pull --ff-only → сборка → миграции → /health
```

`compose.server.yaml` дополняет `compose.yaml`:
- образ без torch (`LOCAL_MODEL=false`), `EMBEDDINGS_CPU_FALLBACK=false`: векторы считает только
  сервис gpu-node; недоступен — отбор по словам и признакам события, спорные проверяет
  нейросеть, на странице стенда предупреждение;
- api в сети хоста (туннель слушает `127.0.0.1:8090` и `:11434`), база — через `127.0.0.1:5432`;
- API, сайт и веб-версия на `0.0.0.0:8000` (`API_HOST=127.0.0.1` — только локально), лимиты
  памяти; в `server/.env` — `PUBLIC_APP_URL=http://<адрес>:8000/app/`, чтобы ссылка-ключ
  рабочего места открывала веб-версию;
- настройки — `server/.env`, ключи площадок — `/opt/mediamonitor/.env` команды (только чтение).

Сверка векторов сервиса с эталоном, посчитанным на CPU (модели на сервере нет):
`docker compose -f compose.yaml -f compose.server.yaml run --rm --no-deps -v "$PWD/scripts:/app/scripts:ro" --entrypoint python api scripts/compare_embeddings.py --reference scripts/berta-reference.json`.

`/docs` и `/openapi.json` выключены при `ENVIRONMENT=production`. На Windows сервер сам
берёт селекторный цикл событий (асинхронный psycopg не работает с Proactor).

## Переменные окружения

Полный список с пояснениями — `.env.example`. Главное:

| Переменная | Что |
|---|---|
| `DATABASE_URL` | `postgresql+psycopg://…`; в compose собирается из `POSTGRES_*` |
| `PUBLIC_APP_URL` | адрес интерфейса — из него строится ссылка-ключ рабочего места |
| `CORS_ORIGINS` | сайт и `chrome-extension://<id>` через запятую |
| `DATA_SOURCE` | `fixtures` — записанные примеры; `live` — настоящие площадки |
| `FIXTURE_FAILURES` | сбои примеров: `max:unavailable,ok:slow` (`unavailable`, `bad-response`, `rate-limited`, `slow`, `timeout`, `quota`, `key-invalid`) |
| `FIXTURE_SHIFT_TO_NOW` | сдвинуть даты примеров к «сейчас» (их «сегодня» — 19.10.2026) |
| `VK_SERVICE_TOKEN`, `MAXSTAT_TOKEN` | ключи площадок — только здесь, на сервере |
| `OLLAMA_URL`, `LLM_MODEL`, `LLM_API`, `LLM_NUM_CTX` | нейросеть: адрес Ollama, модель (по умолчанию `…GGUF:Q6_K`), API (`ollama` / `openai`), контекст 8192 = `OLLAMA_CONTEXT_LENGTH` на gpu-node; не задан адрес — без нейросети |
| `LLM_MAX_GRAY`, `LLM_DEADLINE_SEC` | бюджет нейросети на один поиск: спорных постов и секунд |
| `MATCHER` | воронка `модуль:функция`; по умолчанию «Э-Отбор» (`mediamonitor.matcher.funnel:create_matcher`), без моделей — `mediamonitor.matcher.simple:create_matcher` |
| `MATCH_BATCH_SIZE`, `MATCHER_WARMUP` | постов за шаг отбора (результаты уходят в поток после шага); прогрев моделей при старте |
| `EMBEDDING_MODEL`, `EMBEDDING_VERSION` | модель смысла (BERTA) и версия векторов в кэше базы |
| `EMBEDDINGS_URL`, `EMBEDDINGS_TOKEN` | сервис эмбеддингов gpu-node; пусто — модель на CPU сервера. Проверка, что векторы совпадают: `uv run python scripts/compare_embeddings.py` |
| `EMBEDDINGS_CPU_FALLBACK` | `false` — без отката на CPU, когда сервис недоступен (слабый сервер, образ без torch) |
| `HF_HOME` | куда скачивается модель (~0,5 ГБ); в Docker — том `models` |
| `AI_DETECT_PROVIDER`, `AI_DETECT_URL`, `AI_DETECT_MODEL` | детектор ИИ-текста: `auto` / `gigacheck` / `fixture` / `off`; адрес сервиса на gpu-node (токен — `EMBEDDINGS_TOKEN`); ожидаемая модель |
| `AI_CHECK_LIKELY_THRESHOLD`, `AI_CHECK_SIGNS_THRESHOLD`, `AI_CHECK_MIN_WORDS` | пороги уровней (0,85 / 0,60) и минимум слов (40) — одни для всех мест |
| `SITE_DIR`, `WEB_APP_DIR` | папки сайта (`/`) и веб-версии (`/app/`); пусто — только API. В образе заданы |
| `MAX_RUNNING_SEARCHES`, `RATE_LIMIT_PER_MINUTE`, … | лимиты открытого стенда (НТ-6) |
| `VK_DAILY_CALLS`, `VK_MONTHLY_QUOTA`, `MAXSTAT_DAILY_CREDITS`, `MAXSTAT_CREDITS` | бюджет вызовов площадок на сутки и месяц (по Красноярску; 0 — без предела). Исчерпан — «нет доступа», сообщение «лимит на сегодня исчерпан»; 80% — предупреждение в журнале стенда (`services/budget.py`). Адаптер списывает вызов до обращения: `await self._spend()` |
| `WORKSPACES_PER_IP_PER_DAY` | новых рабочих мест с одного IP за сутки (60); сверх — `429` до полуночи; в базе только хеш IP |

Пустое значение в `.env` означает «не задано». Ключи в логи и ответы не попадают.

## Проверки

```bash
uv run ruff check src tests migrations && uv run ruff format --check src tests migrations
uv run mypy                    # strict: src и tests
uv run pytest                  # временная база SQLite (только для тестов), лёгкая модель вместо BERTA
uv run pytest -m slow          # медленный тест с настоящей BERTA (~1 мин, модель ~0,5 ГБ)
TEST_DATABASE_URL=postgresql+psycopg://… uv run pytest   # то же на PostgreSQL (после alembic upgrade head)
```

Что проверяют тесты (`tests/`):
- `contract/` — каждый ответ сервера и все образцы ответов имитации мокапа проходят JSON
  Schema, собранную из `types.ts` (лишнее или недостающее поле — ошибка);
- `test_search_flow.py` — сквозной сценарий: поиск → поток SSE → подборка → предпросмотр →
  XLSX; сбой площадки и повтор, «нет доступа», «тихий ноль», таймаут, остановка,
  переподключение, «Недавние», исключения и правила выгрузки, добавление по ссылке;
- `test_limits_and_isolation.py` — лимиты (длина, период, один поиск, частота по IP, тело,
  очередь, новые рабочие места с IP за сутки) и изоляция рабочих мест;
- `test_budget.py` — бюджет вызовов площадок: сутки и месяц по Красноярску, 80%, исчерпание,
  вызов, который не помещается, статус площадки в поиске и на странице стенда;
- `test_static.py` — сайт и веб-версия: MIME, CSP без внешних источников и хеши встроенных
  скриптов (в том числе с окончаниями строк Windows), кэш, brotli/gzip, 304, HEAD, SPA,
  служебные файлы и пути за пределами папки не раздаются, API и `/health` не задеты;
- `test_untrusted_text.py` — посты-ловушки: формулы в XLSX, `<script>`, чужие ссылки;
- `test_ai.py` — ответы нейросети (подменённой), ловушки, отказ во время поиска;
- `test_ai_check.py` — проверка текста на ИИ: общие с интерфейсом тест-векторы нормализации,
  один текст в разных записях — один результат, отдельная проверка = подборка =
  «Распространение», кэш и смена модели, «недоступно», «мало текста», фоновая проверка;
- `test_funnel.py` — воронка «Э-Отбор» с лёгкой моделью: предложения и доказательства как у
  воронки, числа совпадают, кэш векторов в базе, потоковая выдача, бюджет нейросети, сервис
  эмбеддингов по контракту gpu-node и откат на CPU; `test_funnel_berta.py` — то же с BERTA;
- `test_sources.py`, `test_normalize.py`, `test_platform_and_stand.py`,
  `test_migrations_and_secrets.py` — источники и импорт, ключ повторов и время, стенд и
  квоты, 500 результатов и потолок OK, перезапуск, своя воронка, миграции, отсутствие ключей.

## Контракт и записанные примеры

JSON Schema, образцы ответов имитации и фикстуры площадок выгружаются из `web/` скриптами
(только чтение `web/`, нужен `npm install` в `web/`):

```bash
cd scripts/contract && npm install
npm run schema           # tests/contract/contract.schema.json из web/src/api/types.ts
npm run export           # tests/contract/samples/*.json — ответы имитации web/src/api/fake
                         # и ai-normalize-vectors.json — тест-векторы нормализации для проверки на ИИ
npm run export:fixtures  # src/mediamonitor/fixtures/*.json — перезаписать фикстуры площадок
```

После изменения `types.ts` — перегенерировать схему и поправить `src/mediamonitor/contract.py`;
тесты покажут расхождения.

- **Контракт — ветка интерфейса** (`docs/04-decisions.md`, «Основа фронтенда — ветка
  команды») плюс дополнения п. 60 бэклога: предпросмотр импорта, перепроверка списка,
  `ImportReport.duplicates`, `post-link`, `freshness` на странице стенда,
  `RegionReason.inMySources`, рабочее место Р8. Типы источников — как в ветке
  (`media`, `authority`, `municipal`, `institution`, `community`, `blogger`); прежние
  значения в базе переводит `contract.source_type()`.
- **Сверх контракта** сервер кое-что считает для себя, но в JSON не отдаёт (`server_only()` в
  `contract.py`): записи без даты в счётчиках, «из скольких» у абзацев релиза, условия,
  статусы и поля размещений в «Распространении», аномалии охвата, лимиты в `StartState`.
  Вернуть поле в ответ — добавить его в `types.ts` и убрать `server_only`.
- **Файл XLSX** (`getExportFile`) — `GET …/export.xlsx`: имя в `Content-Disposition`,
  число строк в `X-Export-Rows` (оба заголовка открыты для браузера в CORS).
- **Фикстуры** записаны из прежней имитации: в них больше постов, чем в наборах ветки
  (посты «только из списка», расширенный релиз), и на них опираются тесты. Поэтому
  `npm run export` их не трогает, а `export:fixtures` перезапишет их наборами текущей имитации.

## Структура

```
src/mediamonitor/
  adapters/   площадки: интерфейс, записанные примеры, заготовки VK / OK / MAX
  normalize/  ключ поста и ссылки, текст, места края, разбор запроса
  matcher/    интерфейс воронки, адаптер «Э-Отбора», модель смысла (CPU / gpu-node), заглушка
  ai/         клиент нейросети (Ollama), проверка ответов
  aicheck/    проверка текста на ИИ: нормализация, детекторы (fixture, gigacheck), общий кэш
  services/   ход поиска, подборка, источники, импорт, выгрузка, распространение, стенд
  api/        маршруты HTTP, ограничения и заголовки безопасности, раздача сайта и веб-версии
  db/         модель данных, подключение
  contract.py зеркало types.ts на Pydantic
migrations/   Alembic
fixtures/     (внутри пакета) записанные примеры площадок
scripts/      smoke.py — сквозная проверка живого сервера; bench_search.py — время поиска;
              precompress.mjs — сжатие сайта и веб-версии при сборке образа;
              compare_embeddings.py — сверка gpu-node и CPU; contract/ — выгрузка из web/
```
