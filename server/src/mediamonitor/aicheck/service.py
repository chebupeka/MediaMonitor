"""Проверка текста на ИИ: один метод и общий кэш для всех мест (04-decisions.md).

Отдельная проверка (`POST /api/ai-check`), карточки подборки и «Распространение» идут
через этот сервис, поэтому один и тот же текст везде получает один результат:

- текст нормализуется одной функцией (`aicheck.text`), ключ — SHA-256 нормализованного
  текста плюс модель и её версия;
- меньше `AI_CHECK_MIN_WORDS` (40) слов — «мало текста», модель не вызывается;
- первый посчитанный результат пишется в `ai_checks` (вставка «если ещё нет» и чтение
  обратно — выигрывает первая запись) и дальше берётся оттуда; один и тот же текст,
  который проверяют одновременно из двух мест, считается один раз;
- уровень — по порогам из настроек от сохранённой оценки, одинаково везде;
- сервис недоступен — «проверка недоступна» (не кэшируется), предупреждение на стенде,
  через `AI_DETECT_RETRY_AFTER_SEC` пробуем снова.

Посты подборки проверяются фоном по мере сбора (services/runner.py): пока текст ждёт
проверки, у записи нет поля `aiCheck`; готовый результат приходит событием `items`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mediamonitor.aicheck.providers import (
    AiDetector,
    DetectorError,
    DetectorReply,
    FixtureDetector,
    GigaCheckDetector,
)
from mediamonitor.aicheck.text import PreparedText, prepare
from mediamonitor.contract import AiCheck, AiLevel
from mediamonitor.db.models import AiCheckRow, StandEventRow
from mediamonitor.db.session import SessionMaker
from mediamonitor.matcher.base import StandNote
from mediamonitor.settings import Settings
from mediamonitor.timeutil import iso, utcnow

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Identity:
    """Модель детектора и её версия — часть ключа кэша."""

    model: str
    version: str

    @property
    def label(self) -> str:
        return f"{self.model}@{self.version}"


def build_detector(settings: Settings) -> AiDetector | None:
    """Провайдер по настройкам (`Settings.ai_detect_kind`); None — проверка выключена."""
    kind = settings.ai_detect_kind
    if kind == "fixture":
        return FixtureDetector()
    if kind == "gigacheck" and settings.ai_detect_url:
        token = settings.embeddings_token.get_secret_value() if settings.embeddings_token else None
        return GigaCheckDetector(
            settings.ai_detect_url, token=token, timeout=settings.ai_detect_timeout_sec
        )
    return None


class AiCheckService:
    def __init__(
        self,
        settings: Settings,
        sessions: SessionMaker,
        detector: AiDetector | None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self.sessions = sessions
        self.detector = detector
        self.min_words = settings.ai_check_min_words
        self._clock = clock
        self._gate = asyncio.Semaphore(settings.ai_detect_concurrency)
        self._inflight: dict[str, asyncio.Future[AiCheck | None]] = {}
        self._pending: Counter[str] = Counter()
        self._down_until = 0.0
        self._journaled_down = False
        self.error: str | None = None
        self.computed = 0  # сколько текстов посчитала модель (не из кэша)
        self.identity: Identity | None = (
            Identity(detector.model, detector.version)
            if isinstance(detector, FixtureDetector)
            else None
        )

    # ------------------------------------------------------------ состояние

    @property
    def enabled(self) -> bool:
        return self.detector is not None

    def available_now(self) -> bool:
        """Можно ли сейчас звать детектор (подключён и не в паузе после сбоя)."""
        return self.detector is not None and self._clock() >= self._down_until

    def pending(self, text_hash: str) -> bool:
        return self._pending[text_hash] > 0 or text_hash in self._inflight

    def level_of(self, score: float) -> AiLevel:
        if score >= self.settings.ai_check_likely_threshold:
            return "likely-ai"
        if score >= self.settings.ai_check_signs_threshold:
            return "signs"
        return "unlikely"

    def _model_label(self) -> str:
        if self.identity is not None:
            return self.identity.label
        return self.settings.ai_detect_model

    # ------------------------------------------------------------ результаты без модели

    def _plain(self, text: PreparedText, level: AiLevel) -> AiCheck:
        return AiCheck(
            level=level,
            score=None,
            model=self._model_label(),
            text_hash=text.hash,
            words=text.words,
            checked_at=iso(utcnow()),
        )

    def _from_row(self, row: AiCheckRow, text: PreparedText) -> AiCheck:
        return AiCheck(
            level=self.level_of(row.score),
            score=row.score,
            model=Identity(row.model, row.model_version).label,
            text_hash=row.text_hash,
            words=text.words,
            checked_at=iso(row.checked_at),
        )

    # ------------------------------------------------------------ проверка

    async def check_text(self, text: str) -> AiCheck:
        """Отдельная проверка одного текста."""
        return (await self.check_many([text]))[0]

    async def check_many(self, texts: Sequence[str]) -> list[AiCheck]:
        """Проверить тексты: кэш → модель (только недостающие) → кэш. Порядок сохраняется."""
        prepared = [prepare(t) for t in texts]
        long = {p.hash: p for p in prepared if p.words >= self.min_words}
        found = await self._resolve(list(long.values())) if long else {}
        out: list[AiCheck] = []
        for p in prepared:
            if p.words < self.min_words:
                out.append(self._plain(p, "too-short"))
            else:
                out.append(found.get(p.hash) or self._plain(p, "unavailable"))
        return out

    async def _resolve(self, items: list[PreparedText]) -> dict[str, AiCheck]:
        """Кэш → модель. Текст, который уже проверяется (другим запросом или фоном), не
        считается второй раз: ждём тот же результат. Отметка «проверяется» ставится до чтения
        кэша, поэтому между чтением и записью второй расчёт не вклинится."""
        loop = asyncio.get_running_loop()
        waiting: dict[str, asyncio.Future[AiCheck | None]] = {}
        mine: list[PreparedText] = []
        for p in items:
            future = self._inflight.get(p.hash)
            if future is not None:
                waiting[p.hash] = future
            else:
                self._inflight[p.hash] = loop.create_future()
                mine.append(p)
        out: dict[str, AiCheck] = {}
        try:
            if mine:
                if self.identity is not None:
                    async with self.sessions() as session:
                        out.update(await self._read(session, self.identity, mine))
                missing = [p for p in mine if p.hash not in out]
                if missing:
                    out.update(await self._compute(missing))
        finally:
            for p in mine:
                future = self._inflight.pop(p.hash, None)
                if future is not None and not future.done():
                    future.set_result(out.get(p.hash))
        for key, future in waiting.items():
            result = await asyncio.shield(future)
            if result is not None:
                out[key] = result
        return out

    async def _compute(self, items: list[PreparedText]) -> dict[str, AiCheck]:
        out: dict[str, AiCheck] = {}
        size = self.settings.ai_detect_batch_size
        for start in range(0, len(items), size):
            if self.detector is None or not self.available_now():
                break
            batch = items[start : start + size]
            try:
                async with self._gate:
                    reply = await self.detector.score([p.text for p in batch])
                identity = self._accept(reply)
            except DetectorError as error:
                await self._mark_down(str(error))
                break
            except Exception as error:  # сбой клиента не должен ронять поиск
                log.exception("Проверка на ИИ: сбой детектора")
                await self._mark_down(type(error).__name__)
                break
            out.update(await self._store(identity, batch, reply.scores))
            self.computed += len(batch)
            await self._mark_up()
        for p in items:
            if p.hash not in out:
                out[p.hash] = self._plain(p, "unavailable")
        return out

    def _accept(self, reply: DetectorReply) -> Identity:
        detector = self.detector
        if (
            detector is not None
            and detector.kind == "gigacheck"
            and reply.model != self.settings.ai_detect_model
        ):
            raise DetectorError(f"на сервисе другая модель: {reply.model[:80]}")
        identity = Identity(reply.model, reply.version)
        if identity != self.identity:
            if self.identity is not None:
                log.warning(
                    "Проверка на ИИ: модель сменилась %s → %s — тексты считаются заново",
                    self.identity.label,
                    identity.label,
                )
            self.identity = identity
        return identity

    # ------------------------------------------------------------ кэш в базе

    async def _read(
        self, session: AsyncSession, identity: Identity, items: Iterable[PreparedText]
    ) -> dict[str, AiCheck]:
        by_hash = {p.hash: p for p in items}
        if not by_hash:
            return {}
        rows = await session.scalars(
            select(AiCheckRow).where(
                AiCheckRow.model == identity.model,
                AiCheckRow.model_version == identity.version,
                AiCheckRow.text_hash.in_(list(by_hash)),
            )
        )
        return {row.text_hash: self._from_row(row, by_hash[row.text_hash]) for row in rows}

    async def _store(
        self, identity: Identity, batch: Sequence[PreparedText], scores: Sequence[float]
    ) -> dict[str, AiCheck]:
        """Записать, если такого результата ещё нет, и прочитать: выигрывает первый."""
        now = utcnow()
        values = []
        for p, raw in zip(batch, scores, strict=True):
            score = round(float(raw), 4)
            values.append(
                {
                    "text_hash": p.hash,
                    "model": identity.model,
                    "model_version": identity.version,
                    "score": score,
                    "level": self.level_of(score),
                    "checked_at": now,
                }
            )
        async with self.sessions.begin() as session:
            dialect = session.get_bind().dialect.name
            insert = pg_insert if dialect == "postgresql" else sqlite_insert
            statement = insert(AiCheckRow).values(values)
            await session.execute(
                statement.on_conflict_do_nothing(
                    index_elements=["text_hash", "model", "model_version"]
                )
            )
            return await self._read(session, identity, batch)

    async def load_identity(self) -> None:
        """При старте: последняя версия ожидаемой модели в кэше — до первого ответа сервиса."""
        if self.identity is not None or self.detector is None:
            return
        async with self.sessions() as session:
            row = await session.scalar(
                select(AiCheckRow)
                .where(AiCheckRow.model == self.settings.ai_detect_model)
                .order_by(AiCheckRow.checked_at.desc())
                .limit(1)
            )
        if row is not None and self.identity is None:
            self.identity = Identity(row.model, row.model_version)

    async def probe(self) -> None:
        """Проверить сервис при старте пустым запросом: доступен ли и какая версия модели."""
        if self.detector is None or self.detector.kind == "fixture":
            return
        try:
            async with self._gate:
                reply = await self.detector.score([])
            self._accept(reply)
        except DetectorError as error:
            await self._mark_down(str(error))
            return
        except Exception as error:
            log.exception("Проверка на ИИ: сбой при проверке сервиса")
            await self._mark_down(type(error).__name__)
            return
        await self._mark_up()

    async def aclose(self) -> None:
        if self.detector is not None:
            await self.detector.aclose()

    # ------------------------------------------------------------ подборка

    async def lookup(
        self, session: AsyncSession, texts: Mapping[str, str | None]
    ) -> dict[str, AiCheck]:
        """Результаты для записей подборки по их текстам (ключ — id записи).

        Есть в кэше — результат; короче минимума — «мало текста»; ещё проверяется фоном —
        записи нет в ответе (поле `aiCheck` отсутствует); иначе — «проверка недоступна».
        """
        prepared = {key: prepare(text) for key, text in texts.items() if text is not None}
        long = [p for p in prepared.values() if p.words >= self.min_words]
        found = await self._read(session, self.identity, long) if self.identity and long else {}
        out: dict[str, AiCheck] = {}
        for key, p in prepared.items():
            if p.words < self.min_words:
                out[key] = self._plain(p, "too-short")
            elif p.hash in found:
                out[key] = found[p.hash]
            elif not self.pending(p.hash):
                out[key] = self._plain(p, "unavailable")
        return out

    def reserve(self, texts: Iterable[str]) -> list[str]:
        """Отметить тексты «ждут фоновой проверки»: пока так, у записей нет `aiCheck`."""
        if not self.available_now():
            return []
        keys = [p.hash for p in map(prepare, texts) if p.words >= self.min_words]
        self._pending.update(keys)
        return keys

    def release(self, keys: Iterable[str]) -> None:
        for key in keys:
            self._pending[key] -= 1
            if self._pending[key] <= 0:
                del self._pending[key]

    # ------------------------------------------------------------ стенд

    async def _mark_down(self, reason: str) -> None:
        self.error = reason
        self._down_until = self._clock() + self.settings.ai_detect_retry_after_sec
        log.warning("Проверка на ИИ недоступна (%s)", reason)
        if not self._journaled_down:
            self._journaled_down = True
            await self._journal(
                "warning",
                f"Проверка текста на ИИ недоступна ({reason}): тексты получают «проверка "
                "недоступна».",
            )

    async def _mark_up(self) -> None:
        self.error = None
        if self._journaled_down:
            self._journaled_down = False
            await self._journal("info", "Проверка текста на ИИ снова работает.")

    async def _journal(self, level: str, message: str) -> None:
        try:
            async with self.sessions.begin() as session:
                session.add(StandEventRow(at=utcnow(), level=level, message=message[:1000]))
        except Exception:  # журнал стенда не должен ронять проверку
            log.exception("Не удалось записать событие стенда")

    def stand_notes(self) -> list[StandNote]:
        if self.detector is None:
            return [
                StandNote(
                    "warning",
                    "Проверка текста на ИИ не подключена (не задан AI_DETECT_URL): отвечаем "
                    "«проверка недоступна».",
                )
            ]
        if self.detector.kind == "fixture":
            return [
                StandNote(
                    "info",
                    "Проверка текста на ИИ: демо-оценка без модели (записанные примеры). "
                    f"Проверено: {self.computed}.",
                )
            ]
        if self.error is not None:
            return [
                StandNote(
                    "warning",
                    f"Проверка текста на ИИ: сервис детектора недоступен ({self.error}) — "
                    "посты и отдельная проверка получают «проверка недоступна».",
                )
            ]
        waiting = sum(self._pending.values())
        return [
            StandNote(
                "info",
                f"Проверка текста на ИИ: {self._model_label()}. Проверено моделью: "
                f"{self.computed}, ждут проверки: {waiting}.",
            )
        ]
