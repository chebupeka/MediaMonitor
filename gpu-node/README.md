# gpu-node — компьютер с видеокартой для MediaMonitor

На отдельном компьютере с **NVIDIA RTX 5080 (16 ГБ, Blackwell)** работают две службы. Сервер
MediaMonitor обращается к ним по сети.

| Служба | Порт | Что делает | Доступ |
|---|---|---|---|
| Сервис эмбеддингов (`sergeyzh/BERTA`) | 8090 | считает векторы смысла текстов (шаг 2 воронки отбора) | токен `EMBEDDINGS_TOKEN` + брандмауэр |
| ↳ детектор ИИ-текста (GigaCheck) | 8090 | `/ai-detect`: похож ли текст на написанный нейросетью (тот же процесс) | тот же токен |
| Ollama + GigaChat 3.1 Lightning | 11434 | разбирает спорные посты (шаг 5 воронки) | **своей авторизации нет** → брандмауэр по адресу сервера или прокси с токеном |

Если компьютер недоступен, сервер работает и без него: векторы считает на своём CPU (медленнее),
а спорные посты получают метку «не проверено ИИ» (Р5–Р6 в `docs/04-decisions.md`), проверка текста
на ИИ отвечает «недоступна».

## Версии (проверено 19.10.2026)

| Что | Версия | Почему |
|---|---|---|
| Драйвер NVIDIA | **570 или новее** (для `cu130` — 580+) | RTX 50xx появились с ветки 570. На Linux — только «open» модули ядра (`nvidia-driver-5xx-open`): закрытые не поддерживают Blackwell |
| PyTorch | **2.11.0 + CUDA 12.8** (`cu128`, по умолчанию) | Blackwell (sm_120) поддерживают сборки CUDA 12.8 и новее. 2.11.0 — последняя версия torch, которую собирали под CUDA 12.8 |
| PyTorch, запасной вариант | 2.14.1 + CUDA 13.0 (`cu130`) | самый свежий torch; под CUDA 12.8 его уже не собирают |
| Ollama | **0.40.6 или новее** | RTX 5080 в списке поддерживаемых (compute capability 12.0). Встроенный llama.cpp b11669, а GGUF GigaChat 3.1 требует b8495 или новее |
| Python / uv | 3.12 / 0.11 | как в `server/matching` |
| sentence-transformers / transformers | 6.1.0 / 5.20.1 | те же, что в `server/matching`: векторы совпадают |

Версии torch закреплены в `pyproject.toml` (группы `cu128`, `cu130`, `cpu`), всё остальное — в `uv.lock`.

## Какую квантизацию GigaChat взять: **Q6_K**

Размеры файлов с Hugging Face (`ai-sage/GigaChat3.1-10B-A1.8B-GGUF`):

| Квантизация | Файл | Сколько займёт в видеопамяти вместе с BERTA* | Запас из 16 ГБ |
|---|---|---|---|
| Q4_K_M | 6,47 ГБ (6,0 ГиБ) | ≈ 9–10 ГиБ | ~6 ГиБ |
| **Q6_K** | 8,78 ГБ (8,2 ГиБ) | ≈ 11–12 ГиБ | **~4 ГиБ** |
| Q8_0 | 11,35 ГБ (10,6 ГиБ) | ≈ 13,5–14,5 ГиБ | ~1,5 ГиБ |

\* Из чего складывается (оценка, проверить на месте через `ollama ps` и `nvidia-smi`):
- веса модели;
- KV-кеш на 8192 токена — небольшой: у модели сжатое внимание (MLA, 26 слоёв), около 30 КБ на
  токен, то есть ~0,25 ГиБ на один одновременный запрос;
- рабочие буферы Ollama — 0,5–1 ГиБ;
- BERTA в fp16 с CUDA-контекстом и пакетом из 64 текстов — 1–1,5 ГиБ;
- рабочий стол Windows, если монитор подключён к этой видеокарте, — 0,5–1 ГиБ.

**Почему Q6_K.** У модели всего 1,8 млрд активных параметров, а маленькие модели теряют от сжатия
заметнее больших. Q6_K по качеству почти не отличается от Q8_0, и при этом остаётся запас около 4 ГиБ.
Q8_0 тоже помещается, но впритык: если вырастет контекст или число параллельных запросов, Ollama
молча унесёт часть слоёв на CPU, и ответы станут в разы медленнее. Q4_K_M имеет смысл брать, только
если памяти не хватает. Скорость для нашей задачи (короткий JSON-ответ) у всех трёх вариантов
высокая.

> На сервере по умолчанию стоит `...:Q4_K_M`. Для Q6_K пропишите на сервере `OLLAMA_MODEL` и
> `LLM_MODEL` (см. «Что прописать на сервере»).

---

## Установка: Windows

Понадобятся права администратора (для брандмауэра) и около 30 ГБ на диске: torch с CUDA ~3 ГБ,
модель GigaChat 8,8 ГБ, BERTA 0,5 ГБ, детектор GigaCheck 14,3 ГБ.

1. **Драйвер NVIDIA.** Поставьте свежий драйвер (https://www.nvidia.com/drivers) и проверьте:
   ```powershell
   nvidia-smi        # видна NVIDIA GeForce RTX 5080, Driver Version 570 или выше
   ```
2. **Папка.** Скопируйте папку `gpu-node` из репозитория, например в `C:\MediaMonitor\gpu-node`.
   Дальше все команды выполняются из неё.
3. **Ollama.** Скачайте и поставьте https://ollama.com/download (`OllamaSetup.exe`) или
   `winget install --id Ollama.Ollama`. Затем:
   ```powershell
   powershell -ExecutionPolicy Bypass -File windows\setup-ollama.ps1          # Q6_K; другая: -Quant Q8_0
   ```
   Скрипт задаёт переменные `OLLAMA_HOST=0.0.0.0:11434`, `OLLAMA_CONTEXT_LENGTH=8192`,
   `OLLAMA_KEEP_ALIVE=-1`, перезапускает Ollama, скачивает модель (`ollama pull
   hf.co/ai-sage/GigaChat3.1-10B-A1.8B-GGUF:Q6_K`) и проверяет ответ по JSON-схеме.
   Ollama на Windows — приложение в трее: оно стартует, когда пользователь входит в систему.
4. **Сервис эмбеддингов.**
   ```powershell
   powershell -ExecutionPolicy Bypass -File windows\start.ps1                 # поставить и запустить
   powershell -ExecutionPolicy Bypass -File windows\start.ps1 -Autostart      # + автозапуск при входе
   ```
   Скрипт ставит uv, создаёт `.env` со случайным токеном, ставит torch 2.11.0 + CUDA 12.8,
   проверяет видеокарту и запускает сервис на порту 8090. При первом запуске скачиваются BERTA и
   (фоном, уже после открытия порта) детектор ИИ-текста GigaCheck, 14,3 ГБ.
   Другие режимы: `-Torch cu130` (torch 2.14.1, драйвер 580+), `-NoRun` (только поставить),
   `-RemoveAutostart`. С `-Autostart` журнал пишется в `logs\service.log`.
   Чтобы всё поднималось само после перезагрузки, включите автовход пользователя в Windows: и
   Ollama, и автозапуск сервиса стартуют при входе.
5. **Брандмауэр** (PowerShell от имени администратора):
   ```powershell
   powershell -ExecutionPolicy Bypass -File windows\firewall.ps1 -ServerIp 192.168.1.20   # адрес сервера
   ```
   Порты 8090 и 11434 открываются только для адреса сервера (`-ServerIp LocalSubnet` — для всей
   локальной сети). Если Windows спросит «Разрешить доступ?» для `ollama.exe` или `python.exe`,
   ответ не важен: скрипт выключает такие правила по программе, иначе они открыли бы порт всем
   или, наоборот, закрыли бы его серверу.
6. **Проверка** на этом компьютере:
   ```powershell
   uv run --frozen --no-dev --extra cu128 python -m mm_embeddings.check --embeddings http://127.0.0.1:8090 --ollama http://127.0.0.1:11434
   ```
   Должно быть: `sm_120` поддержана, `/health` с `"device": "cuda"`, без токена 401, детектор ИИ-текста
   `ready` с оценками четырёх текстов, ответ Ollama по схеме, «на видеокарте 100%». В конце — «Итог: всё
   в порядке». Пока детектор грузится, проверка пишет «ещё загружается» — повторите позже.

## Установка: Linux (Ubuntu 22.04 / 24.04)

1. **Драйвер NVIDIA** — open-модули ядра, ветка 570 или новее:
   ```bash
   sudo ubuntu-drivers install            # или: sudo apt install nvidia-driver-580-open
   sudo reboot
   nvidia-smi                             # видна RTX 5080
   ```
2. **Ollama** — официальный установщик (ставит службу systemd):
   ```bash
   curl -fsSL https://ollama.com/install.sh | sh
   ollama --version                       # 0.40.6 или новее
   sudo mkdir -p /etc/systemd/system/ollama.service.d
   sudo cp linux/ollama.override.conf /etc/systemd/system/ollama.service.d/override.conf
   sudo systemctl daemon-reload && sudo systemctl restart ollama
   ollama pull hf.co/ai-sage/GigaChat3.1-10B-A1.8B-GGUF:Q6_K
   ```
   Можно и в Docker: `docker compose --profile ollama up -d` (образ `ollama/ollama:0.40.6`,
   модель тогда скачивается через `docker compose exec ollama ollama pull ...`).
3. **Сервис эмбеддингов — Docker** (основной вариант). Нужны Docker и NVIDIA Container Toolkit:
   ```bash
   # NVIDIA Container Toolkit: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html
   sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker
   docker run --rm --gpus all ubuntu nvidia-smi          # видеокарта видна из контейнера

   cd gpu-node
   cp .env.example .env
   sed -i "s|^EMBEDDINGS_TOKEN=.*|EMBEDDINGS_TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')|" .env
   docker compose up -d --build                           # TORCH_EXTRA=cu130 docker compose ... — torch 2.14.1
   docker compose logs -f embeddings                      # «модель ... загружена ...: cuda, NVIDIA GeForce RTX 5080, float16»
   ```
   Контейнеры работают в сети хоста (`network_mode: host`), поэтому порты закрывает брандмауэр
   системы. Опубликованные через `ports:` порты Docker открыл бы в обход ufw.

   **Без Docker — служба systemd** (`linux/mm-embeddings.service`):
   ```bash
   sudo useradd --system --create-home mediamonitor
   sudo mkdir -p /opt/mediamonitor && sudo cp -r gpu-node /opt/mediamonitor/
   sudo chown -R mediamonitor: /opt/mediamonitor/gpu-node
   curl -LsSf https://astral.sh/uv/install.sh | sudo env UV_INSTALL_DIR=/usr/local/bin sh
   cd /opt/mediamonitor/gpu-node
   sudo -u mediamonitor cp .env.example .env              # и задать EMBEDDINGS_TOKEN, как выше
   sudo -u mediamonitor /usr/local/bin/uv sync --frozen --no-dev --extra cu128
   sudo cp linux/mm-embeddings.service /etc/systemd/system/
   sudo systemctl daemon-reload && sudo systemctl enable --now mm-embeddings
   journalctl -u mm-embeddings -f
   ```
4. **Брандмауэр** — порты только для сервера (`SERVER_IP` — адрес сервера MediaMonitor):
   ```bash
   sudo ufw allow OpenSSH                 # сначала SSH, чтобы не потерять доступ
   sudo ufw allow from SERVER_IP to any port 8090 proto tcp
   sudo ufw allow from SERVER_IP to any port 11434 proto tcp
   sudo ufw default deny incoming && sudo ufw enable
   ```
   Для firewalld: `sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source
   address="SERVER_IP" port port="11434" protocol="tcp" accept'` (и то же для 8090), затем
   `sudo firewall-cmd --reload`.
5. **Проверка:**
   ```bash
   docker compose exec embeddings python -m mm_embeddings.check \
       --embeddings http://127.0.0.1:8090 --ollama http://127.0.0.1:11434
   # без Docker: uv run --frozen --no-dev --extra cu128 python -m mm_embeddings.check --embeddings ... --ollama ...
   ```

## Детектор ИИ-текста (GigaCheck)

Тот же сервис (порт 8090, токен `EMBEDDINGS_TOKEN`) проверяет, похож ли текст на написанный
нейросетью: модель `iitolstykh/GigaCheck-Classifier-Multi` (Apache-2.0, Mistral-7B + голова
классификации «ai / human»). Сервер MediaMonitor обращается к нему, если задан `AI_DETECT_URL`
(`docs/12-tech-design.md` §13). **Как включить на работающем компьютере — `UPDATE-DETECTOR.md`.**

- **Загрузка фоном.** Сервис открывает порт, как только готова BERTA; GigaCheck грузится следом.
  Пока он грузится, не загрузился или выключен, `/ai-detect` отвечает 503 с объяснением, а
  эмбеддинги работают. Состояние — в `/health` (`ai_detect.state`: `loading` / `ready` / `failed` /
  `disabled`, при `failed` — `error`).
- **Размер.** Скачивание 14,3 ГБ (один раз; кэш Hugging Face, `HF_HOME`). На видеокарте — 4 бита
  (nf4, расчёт в bf16, голова — bf16): ~4–4,5 ГБ весов + до ~0,5 ГБ на расчёт текста в 1024 токена
  [оценка]. Вместе с GigaChat Q6_K и BERTA — ~15–16 из 16 ГБ, на грани (`docs/research/ai-text-detection.md`
  §2.6); если GigaChat вытесняется — GigaChat `Q4_K_M`. Загрузка с диска на видеокарту — 1–3 минуты.
- **Оценка.** `score` — вероятность класса `ai` (softmax двух классов, `config.id2label`); сводить
  ничего не нужно: «смешанного» класса у этой модели нет. Пороги — на сервере: `likely-ai` ≥ 0,85,
  `signs` ≥ 0,60, тексты короче 40 слов сервер модели не шлёт.
- **Детерминизм.** Модель в `eval`, без случайности; каждый текст считается отдельно, без
  выравнивания пакета — оценка не зависит от соседей по запросу. Повтор того же текста — из памяти
  процесса (4096 последних). Оценка округляется до 4 знаков. Текст нормализуется так же, как на
  сервере (NFC, невидимые символы, пробелы — `aicheck/text.py`); сервер шлёт уже нормализованный.
- **Без чужого кода.** Код модели на Hugging Face (`trust_remote_code`) требует пакет `gigacheck` и
  Python 3.11. Здесь свой класс (`detector.py`) с тем же расчётом: Mistral → токен `</s>` → `dense`
  → `tanh` → `out_proj`; вход — `<s>` + до 1022 токенов + `</s>`, как у авторов. Веса и токенизатор —
  с зафиксированной ревизии `1b885318d031` (21.04.2026). `version` в ответе — `<ревизия>-<сжатие>`,
  например `1b885318d031-nf4`: сменились веса или сжатие — сервер пересчитает тексты.

Настройки (`.env`): `AI_DETECT_ENABLED` (true), `AI_DETECT_MODEL` (`iitolstykh/GigaCheck-Classifier-Multi`
или папка с моделью на диске), `AI_DETECT_REVISION` (зафиксированная), `AI_DETECT_QUANT` (`auto`:
nf4 на видеокарте, bf16 на CPU; ещё `int8`, `bf16`). Устройство — как у эмбеддингов (`EMBEDDINGS_DEVICE`).
На CPU модели нужно ~15 ГБ памяти — только для проверки, не для работы.

## Что прописать на сервере

В `server/.env` (адрес `192.168.1.30` — пример, подставьте адрес компьютера с видеокартой):

```ini
EMBEDDINGS_URL=http://192.168.1.30:8090
EMBEDDINGS_TOKEN=                      # значение EMBEDDINGS_TOKEN из gpu-node/.env
OLLAMA_URL=http://192.168.1.30:11434
OLLAMA_MODEL=hf.co/ai-sage/GigaChat3.1-10B-A1.8B-GGUF:Q6_K   # воронка отбора (mm_matching)
LLM_MODEL=hf.co/ai-sage/GigaChat3.1-10B-A1.8B-GGUF:Q6_K      # сервер (ai/judge.py) — та же модель
# LLM_NUM_CTX=8192 — по умолчанию; совпадает с OLLAMA_CONTEXT_LENGTH на этом компьютере
# Только если перед Ollama стоит прокси с токеном (см. ниже):
# OLLAMA_URL=http://192.168.1.30:11435
# LLM_API_KEY=                         # значение OLLAMA_PROXY_TOKEN
AI_DETECT_URL=http://192.168.1.30:8090    # детектор ИИ-текста — тот же сервис; через туннель — http://127.0.0.1:8090
```

**Проверка с сервера** (Linux; на Windows — `curl.exe`, тело запроса — из файла через `--data-binary @файл`,
иначе кириллица в командной строке портится):

```bash
curl http://192.168.1.30:8090/health
# {"status":"ok","model":"sergeyzh/BERTA","device":"cuda"}

curl -s -o /dev/null -w '%{http_code}\n' -X POST http://192.168.1.30:8090/embed -d '{}'
# 401

curl -s http://192.168.1.30:8090/embed -H "Authorization: Bearer $EMBEDDINGS_TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"texts":["Мост через Енисей открыли"],"model":"sergeyzh/BERTA","prefix":"paraphrase: ","normalize":true}' \
  | head -c 120
# {"model":"sergeyzh/BERTA","dim":768,"vectors":[[...

curl -s http://192.168.1.30:11434/api/version
curl -s http://192.168.1.30:11434/api/chat -d @checks/ollama-chat.json
# "message":{"role":"assistant","content":"{\"label\": \"same-event\", \"evidence\": 1}"} — ответ по JSON-схеме
```

`checks/ollama-chat.json` — запрос со structured output: схема ответа передаётся в поле `format`,
Ollama отвечает строго по ней. Если взяли не Q6_K, поправьте в файле поле `model`.

## Как ограничить доступ к Ollama

У Ollama нет логина и токенов: любой, кто достучался до порта 11434, может пользоваться моделью
(и скачивать или удалять модели через API). Варианты:

1. **Брандмауэр по адресу сервера** — основной вариант для локальной сети (шаги выше). Ничего не
   меняется на сервере.
2. **Прокси с токеном** — если адрес сервера заранее неизвестен или меняется. Ollama слушает только
   `127.0.0.1:11434` (`OLLAMA_HOST=127.0.0.1:11434`), наружу открыт порт 11435 прокси Caddy
   (`proxy/Caddyfile`), который пропускает только запросы с `Authorization: Bearer <OLLAMA_PROXY_TOKEN>`.
   На сервере: `OLLAMA_URL=http://<адрес>:11435` и `LLM_API_KEY=<тот же токен>` — оба клиента сервера
   уже отправляют этот заголовок. Запуск: `caddy run --config proxy/Caddyfile` с заданной
   переменной `OLLAMA_PROXY_TOKEN`. Порт 11435 тоже стоит закрыть брандмауэром от всех, кроме сервера.

Порт 11434 нельзя открывать в интернет ни в каком варианте.

## Контракт сервиса эмбеддингов

Под него написан клиент сервера; менять только вместе с ним.

```
POST /embed
Authorization: Bearer <EMBEDDINGS_TOKEN>
{"texts": ["...", "..."], "model": "sergeyzh/BERTA", "prefix": "paraphrase: ", "normalize": true}
→ 200 {"model": "sergeyzh/BERTA", "dim": 768, "vectors": [[...], [...]]}

GET /health        (без токена)
→ 200 {"status": "ok", "model": "sergeyzh/BERTA", "device": "cuda"}
```

- Один вектор на текст, порядок сохраняется. В пакете до 256 текстов. Пустой список — пустой ответ.
- `prefix` — префикс задачи BERTA, его передают явно: `paraphrase: ` (поиск по тексту новости) или
  `categorize_topic: ` (поиск по теме). Пустая строка — без префикса. Это **не** префикс модели по
  умолчанию (`categorize_entailment: `). `model` — для сверки: другая модель даёт 400.
- Векторы float32; у BERTA они нормированы всегда (последний слой модели — нормировка).
- Ошибки — JSON `{"detail", "code"}`: 401 — нет токена или он чужой (на любой адрес, кроме
  `/health`, и до разбора тела); 400 `model-mismatch`; 413 — тело больше 32 МБ; 422 — больше 256
  текстов или неверное тело; 503 `encode-failed` — модель не смогла посчитать (подробности в журнале).
- **Длинные тексты.** Сервис считает каждый присланный текст целиком, а BERTA читает только первые
  512 токенов (~2,5–3,5 тыс. знаков). `mm_matching` режет длинный пост на куски по абзацам (до 1500
  знаков, не больше 4) и усредняет векторы кусков. Чтобы векторы с видеокарты совпадали с векторами
  на CPU сервера, клиент присылает **куски** (`mm_matching.embeddings.chunk_text`) и усредняет сам,
  как `scripts/compare_with_mm_matching.py`. Без нарезки для текста в 2,3 тыс. знаков косинус с
  `mm_matching` — 0,976 вместо 1,000.
- Если видеокарте не хватило памяти, пакет пересчитывается мелкими порциями (по 8 текстов).

### Контракт детектора

```
POST /ai-detect
Authorization: Bearer <EMBEDDINGS_TOKEN>
{"texts": ["нормализованный текст", "..."]}
→ 200 {"model": "iitolstykh/GigaCheck-Classifier-Multi", "version": "1b885318d031-nf4", "scores": [0.97, 0.03]}
```

- `scores[i]` — вероятность «написано нейросетью» для `texts[i]` (0…1), порядок сохраняется. В пакете
  до 64 текстов (сервер шлёт по 16). Пустой список — пустой `scores` с `model` и `version`.
- Ошибки — JSON `{"detail", "code"}`: 401 — нет токена; 422 — неверное тело или больше 64 текстов;
  503 `ai-detect-loading` (с `Retry-After: 60`), `ai-detect-failed`, `ai-detect-disabled` — детектор
  не готов; 503 `detect-error` — модель не смогла посчитать (подробности в журнале).
- Клиент сервера — `server/src/mediamonitor/aicheck/providers.py` (`GigaCheckDetector`).


Настройки — переменные окружения или `.env` (`.env.example`): `EMBEDDINGS_TOKEN` (обязательно, не
короче 16 знаков), `EMBEDDINGS_PORT` (8090), `EMBEDDINGS_HOST` (0.0.0.0), `EMBEDDINGS_DEVICE`
(`auto` / `cuda` / `cpu`), `EMBEDDINGS_BATCH_SIZE` (64), `EMBEDDINGS_FP16` (true), `HF_HOME`.
После первого скачивания модели можно задать `HF_HUB_OFFLINE=1`, чтобы сервис не обращался к
Hugging Face при старте.

## Разработка и проверка без видеокарты

```bash
uv sync --extra cpu
uv run --extra cpu pytest                      # 61 тест: контракт и детектор на заглушке, BERTA на CPU
uv run --extra cpu ruff check . && uv run --extra cpu ruff format --check . && uv run --extra cpu mypy
```

`--extra` указывайте всегда: без него `uv run` пересоберёт окружение без выбранной сборки torch.

Сверка с пакетом воронки (сервис запущен, токен в `EMBEDDINGS_TOKEN`):

```bash
EMBEDDINGS_TOKEN=... EMBEDDINGS_HOST=127.0.0.1 uv run --extra cpu mm-embeddings &
EMBEDDINGS_TOKEN=... ../server/matching/.venv/Scripts/python scripts/compare_with_mm_matching.py
```

**Проверено 19.10.2026 на ноутбуке без видеокарты** (Ryzen 5 7535HS, torch 2.11.0+cpu): pytest —
34 теста; ruff, mypy `--strict` — без замечаний; сервис на CPU: 401 без токена, 256 текстов по
~1200 знаков — 73 с; сверка с `mm_matching` — косинус 1,000000 для коротких, пустых и длинных
текстов с префиксами `paraphrase:` и `categorize_topic:`. `windows\start.ps1 -Torch cpu` —
установка и запуск в фоне работают; остальные `.ps1` проверены разбором синтаксиса.
`docker compose config` корректен.

**Не проверено (нет видеокарты и Docker-демона здесь):** сборка cu128 на RTX 5080, fp16, скорость на
видеокарте, сборка образа, Ollama с GigaChat 3.1. Всё это проверяет `mm_embeddings.check` на месте.
Если GigaChat 3.1 не запустится в Ollama, запасной путь из карточки модели — `llama-server` из
llama.cpp (b8495+) с OpenAI-совместимым API; на сервере тогда `LLM_API=openai`.

**Детектор ИИ-текста — проверено 20.10.2026 на том же ноутбуке** (без настоящих весов: 14,3 ГБ по
каналу ~0,5–1 МБ/с не скачать за день, а 15 ГБ памяти ноутбука на bf16 не хватает):
- pytest — 61 тест (детектор на заглушке: контракт, токен, 503 в трёх состояниях, загрузка фоном,
  детерминизм обёртки, нормализация по общим тест-векторам сервера; маленькая случайная Mistral —
  наш расчёт по одному тексту совпадает с расчётом GigaCheck пакетом с выравниванием);
- сверка с настоящей моделью без весов: конфиг (2 класса, `0: ai`, `max_length` 1024), имена и формы
  всех 294 тензоров по заголовкам safetensors (HTTP Range) — совпали, 7,13 млрд параметров, BF16;
  токенизатор transformers 5.20 даёт те же токены, что `tokenizer.json` и sentencepiece (`tokenizer.model`);
- сервис целиком с маленькой случайной моделью того же формата: загрузка фоном, `/health`, `check.py`
  (`/ai-detect`: 401, пустой список, 4 текста, повтор), клиент сервера `aicheck/providers.py` принимает
  ответ без правок.
**Не проверено:** настоящие оценки GigaCheck, 4 бита bitsandbytes на RTX 5080 под Windows, видеопамять
рядом с GigaChat, время на видеокарте — это покажет `check.py` на месте (`UPDATE-DETECTOR.md`).

## Файлы

| Файл | Что |
|---|---|
| `src/mm_embeddings/app.py` | HTTP-сервис: `/embed`, `/ai-detect`, `/health`, проверка токена |
| `src/mm_embeddings/detector.py` | детектор ИИ-текста GigaCheck: свой класс модели, 4 бита, загрузка фоном, нормализация |
| `UPDATE-DETECTOR.md` | как включить детектор на работающем компьютере (Windows) и команда для сервера |
| `src/mm_embeddings/encoder.py` | загрузка BERTA, выбор устройства и проверка поддержки sm_120, fp16, пакеты |
| `src/mm_embeddings/settings.py` | настройки из окружения |
| `src/mm_embeddings/check.py` | проверка на месте: torch и CUDA, сервис, детектор (4 текста), Ollama (схема, «100% GPU») |
| `scripts/compare_with_mm_matching.py` | сверка векторов с пакетом воронки |
| `windows/start.ps1`, `firewall.ps1`, `setup-ollama.ps1` | Windows: установка и запуск, брандмауэр, Ollama |
| `Dockerfile`, `compose.yaml` | Linux: сервис (и Ollama по желанию) в Docker с видеокартой |
| `linux/mm-embeddings.service`, `linux/ollama.override.conf` | Linux без Docker: служба systemd; настройки Ollama |
| `proxy/Caddyfile` | прокси с токеном перед Ollama (по желанию) |
| `checks/ollama-chat.json` | запрос к Ollama со structured output для curl |
