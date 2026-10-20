# Сервер Медиарадара: API (Python 3.12, зависимости из uv.lock без dev), сайт-витрина на «/»
# и веб-версия панели на «/app/» — один образ, один порт.
#
# Собирается из КОРНЯ репозитория: веб-версию собирает node из web/, сайт берётся из site/.
#   docker build -f server/Dockerfile .      (compose: context: .., dockerfile: server/Dockerfile)
# Что попадает в контекст — server/Dockerfile.dockerignore.

# ---------------------------------------------------------------- 1. сайт и веб-версия (node)
FROM node:22-slim AS web
WORKDIR /src/web
# Сборка Vite укладывается в 1,5 ГБ кучи: на VPS 4 ГБ, стенд занимает около 1 ГБ.
ENV NODE_OPTIONS=--max-old-space-size=1536 \
    npm_config_fund=false \
    npm_config_audit=false \
    npm_config_update_notifier=false
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
# Веб-версия работает с этим же сервером (VITE_API_URL=/ — тот адрес, откуда открыта
# страница) и без демо-панели (VITE_TARGET=web). Файл .env.web не нужен: те же значения
# по умолчанию задаёт web/vite.config.ts в режиме web; файлы web/.env* в образ не попадают.
ARG VITE_API_URL=/
ARG VITE_TARGET=web
# build:web — vite build --mode web → dist-web/ с base /app/; сервер раздаёт её на «/app/».
RUN VITE_API_URL="$VITE_API_URL" VITE_TARGET="$VITE_TARGET" npm run build:web \
    && test -f dist-web/index.html
# Расширение для установки из файла (сайт, раздел «Установить»): архивы на
# /download/mediaradar-chrome.zip (Chrome, Яндекс Браузер, Edge) и mediaradar-firefox.zip.
# Работает с сервером EXT_API_URL (по умолчанию — стенд, web/wxt.config.ts), а не с «/»:
# у страниц расширения свой адрес chrome-extension://…, адрес сервера нужен полный.
ARG EXT_API_URL=http://109.196.167.227:8000
# VITE_TARGET выше объявлен как ARG и виден всем RUN этапа: для расширения он не «web».
RUN VITE_TARGET=extension VITE_API_URL="$EXT_API_URL" npm run ext:zip \
    && VITE_TARGET=extension VITE_API_URL="$EXT_API_URL" npm run ext:zip:firefox \
    && mkdir -p /out/site/download \
    && cp .output/mediaradar-chrome.zip .output/mediaradar-firefox.zip /out/site/download/
COPY site/ /out/site/
COPY server/scripts/precompress.mjs /tmp/precompress.mjs
RUN mv dist-web /out/app && node /tmp/precompress.mjs /out/site /out/app

# ---------------------------------------------------------------- 2. сервер (Python)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

COPY --from=ghcr.io/astral-sh/uv:0.11.22 /uv /usr/local/bin/uv

WORKDIR /app

# LOCAL_MODEL=false — образ без модели смысла на CPU (без torch и sentence-transformers):
# для слабого сервера, где векторы считает только сервис gpu-node (EMBEDDINGS_URL). Сервис
# недоступен — отбор без смысловой близости и предупреждение на стенде (compose.server.yaml).
ARG LOCAL_MODEL=true
ARG CPU_MODEL_PACKAGES="torch sentence-transformers transformers tokenizers safetensors \
huggingface-hub hf-xet scikit-learn sympy mpmath networkx"

# Сначала зависимости — слой кэшируется, пока не меняется uv.lock (torch — сборка для CPU).
COPY server/pyproject.toml server/uv.lock server/README.md ./
COPY server/matching/pyproject.toml server/matching/README.md ./matching/
RUN skip=""; if [ "$LOCAL_MODEL" = "false" ]; then \
        for p in $CPU_MODEL_PACKAGES; do skip="$skip --no-install-package $p"; done; fi; \
    uv sync --frozen --no-dev --no-install-project --no-install-package mm-matching $skip

# Код сервера, миграции и воронка «Э-Отбор» (server/matching, пакет mm_matching).
COPY server/ ./
RUN skip=""; if [ "$LOCAL_MODEL" = "false" ]; then \
        for p in $CPU_MODEL_PACKAGES; do skip="$skip --no-install-package $p"; done; fi; \
    uv sync --frozen --no-dev $skip \
    && useradd --system --uid 10001 --home /app app \
    && mkdir -p /models \
    && chown -R app /app /models

# Сайт и веб-версия — последним слоем: их правка не пересобирает Python.
COPY --from=web /out/site /app/static/site
COPY --from=web /out/app /app/static/app

USER app
# Модель смысла (BERTA, ~0,5 ГБ) скачивается при первом прогреве в том /models.
ENV PATH="/app/.venv/bin:${PATH}" \
    HOST=0.0.0.0 \
    PORT=8000 \
    HF_HOME=/models \
    SITE_DIR=/app/static/site \
    WEB_APP_DIR=/app/static/app
EXPOSE 8000

CMD ["mediamonitor"]
