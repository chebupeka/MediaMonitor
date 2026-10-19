"""Провайдеры оценки «похоже ли на текст нейросети»: интерфейс и две реализации.

- `FixtureDetector` — без модели: оценка выводится из хеша текста. Для тестов и разработки
  на записанных примерах; на живых данных не включается сам (ложная метка — обвинение).
- `GigaCheckDetector` — HTTP-клиент сервиса на компьютере с видеокартой (gpu-node):

      POST {AI_DETECT_URL}/ai-detect          Authorization: Bearer {EMBEDDINGS_TOKEN}
      {"texts": ["...", ...]}
      → 200 {"model": "iitolstykh/GigaCheck-Classifier-Multi", "version": "...",
             "scores": [0.97, ...]}

  `scores[i]` — вероятность класса «ai» для `texts[i]` (0…1), порядок сохраняется.
  Пустой список → пустой `scores` с `model` и `version` (так сервер узнаёт версию при старте).
  Сервис обязан считать каждый текст отдельно и одинаково при любом составе пакета
  (модель в eval, без случайности, без влияния выравнивания пакета): результат не должен
  зависеть от соседей по запросу. Ошибки — код не 200: 401 без токена, 422 неверное тело,
  503 модель не посчитала.

Провайдер получает уже нормализованные тексты (`aicheck.text`) и только тексты от 40 слов.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import httpx

from mediamonitor.aicheck.text import text_hash


class DetectorError(Exception):
    """Детектор не ответил по контракту: недоступен, ошибка, непонятный ответ."""


@dataclass(frozen=True)
class DetectorReply:
    """Ответ детектора: модель и её версия (часть ключа кэша) и оценки по порядку текстов."""

    model: str
    version: str
    scores: Sequence[float]


class AiDetector(Protocol):
    """Оценивает каждый текст отдельно: результат не зависит от состава пакета."""

    kind: str  # fixture | gigacheck

    async def score(self, texts: Sequence[str]) -> DetectorReply: ...

    async def aclose(self) -> None: ...


class FixtureDetector:
    """Детерминированная оценка без модели: первые 32 бита SHA-256 текста → 0…1."""

    kind = "fixture"

    def __init__(self, model: str = "fixture-demo", version: str = "1") -> None:
        self.model = model
        self.version = version
        self.calls = 0  # сколько раз вызывали — тесты проверяют, что кэш работает
        self.texts = 0

    async def score(self, texts: Sequence[str]) -> DetectorReply:
        self.calls += 1
        self.texts += len(texts)
        return DetectorReply(self.model, self.version, [fixture_score(t) for t in texts])

    async def aclose(self) -> None:
        return None


def fixture_score(normalized: str) -> float:
    """Оценка из хеша текста (тот же SHA-256, что ключ кэша) — формула имитации интерфейса
    (web/src/api/fake/ai.ts): u — первые 48 бит хеша в [0, 1), score = u³ до тысячных.
    Куб сдвигает оценки вниз: «похоже на ИИ» — около 5% текстов, «признаки» — около 10%."""
    u = int(text_hash(normalized)[:12], 16) / 2**48
    return math.floor(u**3 * 1000 + 0.5) / 1000


class GigaCheckDetector:
    """Клиент сервиса детектора на gpu-node (тот же токен, что у сервиса эмбеддингов)."""

    kind = "gigacheck"
    RETRIES = 2

    def __init__(
        self,
        url: str,
        *,
        token: str | None = None,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.url = url.rstrip("/")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=5.0),
            headers=headers,
            transport=transport,
            follow_redirects=False,
        )

    async def score(self, texts: Sequence[str]) -> DetectorReply:
        body = {"texts": list(texts)}
        last: Exception | None = None
        for attempt in range(self.RETRIES):
            try:
                response = await self._client.post(f"{self.url}/ai-detect", json=body)
            except httpx.HTTPError as error:
                last = error
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            if response.status_code >= 500:
                last = DetectorError(f"сервис ответил кодом {response.status_code}")
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            if response.status_code != 200:
                raise DetectorError(f"сервис ответил кодом {response.status_code}")
            return _validate(response, len(texts))
        if isinstance(last, DetectorError):
            raise last
        raise DetectorError(f"нет ответа ({type(last).__name__})") from last

    async def aclose(self) -> None:
        await self._client.aclose()


def _validate(response: httpx.Response, expected: int) -> DetectorReply:
    try:
        data = response.json()
    except ValueError as error:
        raise DetectorError("ответ не JSON") from error
    if not isinstance(data, dict):
        raise DetectorError("ответ не по контракту")
    model, version, scores = data.get("model"), data.get("version"), data.get("scores")
    if not isinstance(model, str) or not model.strip():
        raise DetectorError("в ответе нет модели")
    if isinstance(version, int) and not isinstance(version, bool):
        version = str(version)
    if not isinstance(version, str) or not version.strip():
        raise DetectorError("в ответе нет версии модели")
    if not isinstance(scores, list) or len(scores) != expected:
        raise DetectorError("число оценок не совпадает с числом текстов")
    out: list[float] = []
    for score in scores:
        if isinstance(score, bool) or not isinstance(score, int | float):
            raise DetectorError("оценка — не число")
        if not math.isfinite(score) or not 0.0 <= score <= 1.0:
            raise DetectorError("оценка вне 0…1")
        out.append(float(score))
    return DetectorReply(model.strip()[:200], version.strip()[:100], out)
