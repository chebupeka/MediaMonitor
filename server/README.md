# Сервер Медиамонитора

Поиск публикаций VK, Одноклассников и MAX по Красноярскому краю: ход поиска потоком SSE,
подборка с метками и доказательствами, «Распространение», выгрузка XLSX. Python 3.12,
FastAPI + Pydantic v2, SQLAlchemy 2 + Alembic, PostgreSQL 16 + pgvector.

Устройство, модель данных, таблица «метод интерфейса → HTTP», лимиты и безопасность —
`docs/12-tech-design.md`. Контракт — `web/src/api/types.ts`: ответы сервера совпадают с ним
поле в поле (это проверяют тесты).

## Что работает, что заглушка

| Часть | Состояние |
|---|---|
| API всех 30 серверных методов `MonitorApi`, поток SSE, остановка, повтор площадки, очередь, восстановление после перезапуска | работает |
| Рабочее место по ссылке-ключу, источники, каталог края, импорт из Excel/CSV, «Недавние», выгрузка XLSX, «Распространение», страница стенда | работает |
| Данные площадок | **записанные примеры** (`DATA_SOURCE=fixtures`, вымышленные источники из мокапа); адаптеры VK, OK, MAX — заготовки с TODO |
| Отбор | **воронка «Э-Отбор»** (`server/matching`, пакет `mm_matching`): фразы → смысл (BERTA) → признаки события → нейросеть; результаты идут в поток по мере отбора; векторы постов кэшируются в базе. Устройство и замеры — `docs/12-tech-design.md` §11 |
| Модель смысла | BERTA на CPU сервера или сервис на компьютере с видеокартой (`EMBEDDINGS_URL`, папка `gpu-node/`) с откатом на CPU |
| Нейросеть | GigaChat 3.1 Lightning в Ollama по `OLLAMA_URL`; не задан или не отвечает — спорные «не проверено ИИ» |

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
| `HF_HOME` | куда скачивается модель (~0,5 ГБ); в Docker — том `models` |
| `MAX_RUNNING_SEARCHES`, `RATE_LIMIT_PER_MINUTE`, … | лимиты открытого стенда (НТ-6) |

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
  очередь) и изоляция рабочих мест;
- `test_untrusted_text.py` — посты-ловушки: формулы в XLSX, `<script>`, чужие ссылки;
- `test_ai.py` — ответы нейросети (подменённой), ловушки, отказ во время поиска;
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
  services/   ход поиска, подборка, источники, импорт, выгрузка, распространение, стенд
  api/        маршруты HTTP, ограничения и заголовки безопасности
  db/         модель данных, подключение
  contract.py зеркало types.ts на Pydantic
migrations/   Alembic
fixtures/     (внутри пакета) записанные примеры площадок
scripts/      smoke.py — сквозная проверка живого сервера; bench_search.py — время поиска;
              compare_embeddings.py — сверка gpu-node и CPU; contract/ — выгрузка из web/
```
