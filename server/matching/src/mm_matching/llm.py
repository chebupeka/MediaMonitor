"""Клиент нейросети: Ollama (GigaChat 3.1 Lightning) или любой OpenAI-совместимый сервер.

Адрес — `OLLAMA_URL`, модель — `OLLAMA_MODEL`. Ответ всегда по JSON-схеме
(structured outputs). Любая ошибка — исключение `LlmError`; вызывающий код
превращает его в «не проверено ИИ», а не в «не относится».
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Protocol

import httpx

from mm_matching.config import LlmSettings


class LlmError(Exception):
    """Нейросеть не ответила по делу: недоступна, таймаут, ошибка, ответ не JSON."""


class LlmClient(Protocol):
    def available(self) -> bool:
        """Быстрая проверка: адрес отвечает и модель есть. Не бросает исключений."""
        ...

    def chat_json(self, system: str, user: str, schema: dict[str, Any]) -> str:
        """Возвращает текст ответа модели (должен быть JSON по схеме) или бросает LlmError."""
        ...

    @property
    def description(self) -> str: ...


class OllamaClient:
    """HTTP-клиент. `transport` подменяется в тестах (httpx.MockTransport)."""

    def __init__(
        self,
        settings: LlmSettings,
        *,
        transport: httpx.BaseTransport | None = None,
        api_key: str | None = None,
    ) -> None:
        if not settings.url:
            raise ValueError("OLLAMA_URL не задан")
        self._s = settings
        self._client = httpx.Client(
            base_url=settings.url,
            timeout=httpx.Timeout(settings.timeout_s, connect=5.0),
            transport=transport,
            headers={"Authorization": f"Bearer {api_key}"} if api_key else None,
        )
        self._available: tuple[float, bool] | None = None
        self._digest: str | None = None

    @property
    def description(self) -> str:
        return f"{self._s.model} @ {self._s.url} ({self._s.api})"

    @property
    def model_version(self) -> str:
        """Имя модели и её версия (digest из `/api/tags`): ключ кэша карточки темы."""
        return f"{self._s.model}@{self._digest[:12]}" if self._digest else self._s.model

    def available(self) -> bool:
        now = time.monotonic()
        if self._available and now - self._available[0] < 30:
            return self._available[1]
        ok = self._probe()
        self._available = (now, ok)
        return ok

    def mark_unavailable(self) -> None:
        self._available = (time.monotonic(), False)

    def _probe(self) -> bool:
        try:
            if self._s.api == "openai":
                r = self._client.get("/v1/models", timeout=5.0)
                return r.status_code == 200
            r = self._client.get("/api/tags", timeout=5.0)
            if r.status_code != 200:
                return False
            want = self._s.model
            for m in r.json().get("models", []):
                name = str(m.get("name", ""))
                if name in (want, f"{want}:latest") or name.startswith(want):
                    self._digest = str(m.get("digest") or "") or None
                    return True
            return False
        except (httpx.HTTPError, ValueError, AttributeError):
            return False

    def chat_json(self, system: str, user: str, schema: dict[str, Any]) -> str:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        try:
            if self._s.api == "openai":
                return self._chat_openai(messages, schema)
            return self._chat_ollama(messages, schema)
        except httpx.HTTPError as e:
            raise LlmError(f"нейросеть недоступна: {type(e).__name__}") from e
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise LlmError("ответ нейросети не разобран") from e

    def _chat_ollama(self, messages: list[dict[str, str]], schema: dict[str, Any]) -> str:
        body = {
            "model": self._s.model,
            "messages": messages,
            "stream": False,
            "format": schema,
            "options": {"temperature": 0, "seed": 0, "num_ctx": self._s.num_ctx},
            "keep_alive": keep_alive_value(self._s.keep_alive),
        }
        r = self._client.post("/api/chat", json=body)
        if r.status_code != 200:
            raise LlmError(f"нейросеть ответила кодом {r.status_code}")
        data = r.json()
        content = data["message"]["content"]
        if not isinstance(content, str):
            raise LlmError("в ответе нет текста")
        return content

    def _chat_openai(self, messages: list[dict[str, str]], schema: dict[str, Any]) -> str:
        body = {
            "model": self._s.model,
            "messages": messages,
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "answer", "schema": schema, "strict": True},
            },
        }
        r = self._client.post("/v1/chat/completions", json=body)
        if r.status_code != 200:
            raise LlmError(f"нейросеть ответила кодом {r.status_code}")
        content = r.json()["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise LlmError("в ответе нет текста")
        return content


_NUMBER_RE = re.compile(r"[+-]?\d+(?:\.\d+)?")


def keep_alive_value(raw: str) -> int | float | str:
    """`keep_alive` для Ollama: число — секунды («-1» — держать модель всегда), иначе
    длительность строкой («30m»). Строку «-1» Ollama не примет: у неё нет единицы."""
    value = raw.strip() or "-1"
    if _NUMBER_RE.fullmatch(value):
        number = float(value)
        return int(number) if number.is_integer() else number
    return value


def client_from_env(settings: LlmSettings | None = None) -> OllamaClient | None:
    """Клиент по переменным окружения; `None`, если `OLLAMA_URL` не задан."""
    import os

    s = settings or LlmSettings.from_env()
    if not s.url:
        return None
    return OllamaClient(s, api_key=os.environ.get("LLM_API_KEY") or None)


def loads_strict(raw: str) -> Any:
    """json.loads без NaN/Infinity и с запретом повторяющихся ключей."""

    def no_dupes(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in pairs:
            if k in out:
                raise ValueError(f"повтор ключа {k}")
            out[k] = v
        return out

    def no_const(name: str) -> Any:
        raise ValueError(f"недопустимое значение {name}")

    return json.loads(raw, object_pairs_hook=no_dupes, parse_constant=no_const)
