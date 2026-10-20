# Сервер Медиамонитора: Python 3.12 + зависимости из uv.lock (без dev).
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
COPY pyproject.toml uv.lock README.md ./
COPY matching/pyproject.toml matching/README.md ./matching/
RUN skip=""; if [ "$LOCAL_MODEL" = "false" ]; then \
        for p in $CPU_MODEL_PACKAGES; do skip="$skip --no-install-package $p"; done; fi; \
    uv sync --frozen --no-dev --no-install-project --no-install-package mm-matching $skip

# Код сервера, миграции и воронка «Э-Отбор» (server/matching, пакет mm_matching).
COPY . .
RUN skip=""; if [ "$LOCAL_MODEL" = "false" ]; then \
        for p in $CPU_MODEL_PACKAGES; do skip="$skip --no-install-package $p"; done; fi; \
    uv sync --frozen --no-dev $skip \
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
