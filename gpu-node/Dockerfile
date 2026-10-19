# Сервис эмбеддингов MediaMonitor для Linux с видеокартой NVIDIA.
# CUDA в образ ставить не нужно: колёса torch cu128 приносят свои библиотеки CUDA, а драйвер
# пробрасывает NVIDIA Container Toolkit. Сборка: docker compose build (см. compose.yaml).
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.22 /uv /uvx /bin/

# cu128 — torch 2.11.0 + CUDA 12.8 (RTX 50xx, драйвер >= 570); cu130 — torch 2.14.1 (драйвер >= 580).
ARG TORCH_EXTRA=cu128
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    HF_HOME=/models \
    PYTHONUNBUFFERED=1 \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility

RUN useradd --create-home --uid 10001 app && mkdir -p /models && chown app:app /models
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --extra ${TORCH_EXTRA}
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra ${TORCH_EXTRA}

ENV PATH="/app/.venv/bin:$PATH"
USER app
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % (os.environ.get('EMBEDDINGS_PORT') or '8090'), timeout=4)"
CMD ["mm-embeddings"]
