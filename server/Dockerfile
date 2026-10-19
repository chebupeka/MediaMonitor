# Сервер Медиамонитора: Python 3.12 + зависимости из uv.lock (без dev).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

COPY --from=ghcr.io/astral-sh/uv:0.11.22 /uv /usr/local/bin/uv

WORKDIR /app

# Сначала зависимости — слой кэшируется, пока не меняется uv.lock (torch — сборка для CPU).
COPY pyproject.toml uv.lock README.md ./
COPY matching/pyproject.toml matching/README.md ./matching/
RUN uv sync --frozen --no-dev --no-install-project --no-install-package mm-matching

# Код сервера, миграции и воронка «Э-Отбор» (server/matching, пакет mm_matching).
COPY . .
RUN uv sync --frozen --no-dev \
    && useradd --system --uid 10001 --home /app app \
    && mkdir -p /models \
    && chown -R app /app /models

USER app
# Модель смысла (BERTA, ~0,5 ГБ) скачивается при первом прогреве в том /models.
ENV PATH="/app/.venv/bin:${PATH}" \
    HOST=0.0.0.0 \
    PORT=8000 \
    HF_HOME=/models
EXPOSE 8000

CMD ["mediamonitor"]
