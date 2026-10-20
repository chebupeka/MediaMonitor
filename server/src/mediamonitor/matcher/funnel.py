"""Адаптер воронки «Э-Отбор» (пакет `mm_matching`, server/matching) к интерфейсу `Matcher`.

Что делает сервер вокруг воронки:
- предложения публикаций строит той же функцией, что воронка (`split_sentences`), —
  номер предложения-доказательства указывает на то же предложение в интерфейсе;
- абзацы релиза (`p0`, `p1`…) берёт у воронки — на них ссылается цитирование (П1);
- карточку темы просит у воронки (нейросеть или правила), правки пользователя
  применяет сам (`TopicCorrection`), а для отбора передаёт уже поправленную карточку;
- отбирает порциями по мере сбора (НТ-2): векторы постов берёт из кэша в базе, новые
  туда же записывает (Р7) — пост, встречавшийся раньше, повторно не считается;
- нейросеть — по OLLAMA_URL; бюджет спорных и времени — на весь поиск, а не на порцию;
- модели смысла нет (сервис эмбеддингов недоступен, отката на CPU нет) — шаг идёт без
  смысловой близости: фразы и признаки события, спорные — нейросети;
- повторы одного поста в одном источнике (ТЗ-Ф30) отсекает, копии в разных
  источниках склеивает в группы (Р9).

Все вызовы воронки синхронные (CPU, сеть до Ollama) — идут через `run_in_threadpool`.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import replace

import mm_matching as mm
from mm_matching.config import LlmSettings, MatcherConfig
from mm_matching.embeddings import EmbedKind
from mm_matching.events import EventExtractor
from mm_matching.llm import LlmClient, OllamaClient
from mm_matching.text import split_paragraphs
from mm_matching.text import split_sentences as mm_split_sentences
from starlette.concurrency import run_in_threadpool

from mediamonitor.ai.judge import AiJudge
from mediamonitor.contract import EventSigns, QueryKind, TopicFacet, TopicUnderstanding
from mediamonitor.labels import truncate_text
from mediamonitor.matcher.base import (
    Candidate,
    Decision,
    EvidenceDraft,
    QueryContext,
    StandNote,
    VectorStore,
)
from mediamonitor.matcher.embeddings import (
    CachingEmbedder,
    EmbeddingsUnavailableError,
    build_embedder,
    text_key,
)
from mediamonitor.normalize.query import ReleaseFragmentText
from mediamonitor.normalize.text import Span
from mediamonitor.settings import Settings

log = logging.getLogger(__name__)

REPEAT_REASON = "Повтор: тот же текст уже опубликован этим источником (ТЗ-Ф30)"


# ---------------------------------------------------------------- карточка темы ↔ контракт


def card_to_contract(card: mm.TopicCard) -> TopicUnderstanding:
    signs = None
    if card.signs is not None:
        signs = EventSigns(
            who=list(card.signs.who),
            where=list(card.signs.where),
            when=list(card.signs.when),
            numbers=list(card.signs.numbers),
        )
    return TopicUnderstanding(
        summary=card.summary,
        includes=[TopicFacet(id=f.id, label=f.label, origin=f.origin) for f in card.includes],
        excludes=[TopicFacet(id=f.id, label=f.label, origin=f.origin) for f in card.excludes],
        signs=signs,
        made_by=card.made_by,
        note=card.note,
        cut_examples=[],
    )


def contract_to_card(topic: TopicUnderstanding, query: str) -> mm.TopicCard:
    signs = None
    if topic.signs is not None:
        signs = mm.EventSigns(
            who=tuple(topic.signs.who),
            where=tuple(topic.signs.where),
            when=tuple(topic.signs.when),
            numbers=tuple(topic.signs.numbers),
        )
    return mm.TopicCard(
        query=query,
        summary=topic.summary,
        includes=tuple(mm.TopicFacet(f.id, f.label, f.origin) for f in topic.includes),
        excludes=tuple(mm.TopicFacet(f.id, f.label, f.origin) for f in topic.excludes),
        made_by=topic.made_by,
        note=topic.note,
        signs=signs,
    )


# ---------------------------------------------------------------- воронка


class FunnelMatcher:
    """`Matcher` поверх `mm_matching.FunnelMatcher`. Один на процесс: модели общие."""

    name = "funnel"

    def __init__(
        self,
        settings: Settings,
        *,
        embedder: CachingEmbedder | None = None,
        llm: LlmClient | None = None,
        events: EventExtractor | None = None,
        config: MatcherConfig | None = None,
    ) -> None:
        self.settings = settings
        self.config = config or MatcherConfig(embedding_model=settings.embedding_model)
        self.embedder = embedder or build_embedder(settings)
        self.model_key = f"{settings.embedding_model}#{settings.embedding_version}"
        self.llm_settings = LlmSettings(
            url=settings.ollama_url,
            model=settings.llm_model,
            api=settings.llm_api,
            timeout_s=settings.llm_timeout_sec,
            max_gray=settings.llm_max_gray,
            deadline_s=settings.llm_deadline_sec,
            num_ctx=settings.llm_num_ctx,
            concurrency=settings.llm_concurrency,
            keep_alive=settings.ollama_keep_alive,
        )
        if llm is None and settings.ollama_url:
            key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else None
            llm = OllamaClient(self.llm_settings, api_key=key)
        self.llm = llm
        self.events = events or EventExtractor()
        self.core = self.make_core(self.llm_settings)
        self.warmup_seconds: float | None = None

    def make_core(self, llm_settings: LlmSettings, *, semantic: bool = True) -> mm.FunnelMatcher:
        """Воронка с общими моделями и своим бюджетом нейросети (на один шаг поиска).

        `semantic=False` — без модели смысла: только фразы, признаки события и нейросеть.
        """
        return mm.FunnelMatcher(
            self.config,
            embedder=self.embedder if semantic else None,
            llm=self.llm,
            events=self.events,
            llm_settings=llm_settings,
        )

    # ------------------------------------------------------------ Matcher

    def split_sentences(self, text: str) -> list[Span]:
        return [Span(s.start, s.end) for s in mm_split_sentences(text)]

    def release_fragments(self, text: str) -> tuple[ReleaseFragmentText, ...]:
        return tuple(
            ReleaseFragmentText(id=f"p{i}", index=i, text=text[r.start : r.end])
            for i, r in enumerate(split_paragraphs(text))
        )

    async def topic_card(
        self, text: str, kind: QueryKind, meaning: str | None
    ) -> TopicUnderstanding | None:
        query = f"{text} ({meaning})" if meaning else text
        # Пункты «не то» от нейросети сверяются с темой по эмбеддингу. Модели смысла нет
        # (сервис недоступен, отката на CPU нет) — сверка только по словам, поиск не падает.
        semantic = self.embedder.available
        core = self.core if semantic else self.make_core(self.llm_settings, semantic=False)
        try:
            card = await run_in_threadpool(core.topic_card, query, kind)
        except EmbeddingsUnavailableError:
            # Сервис упал на этой сверке. Ответ нейросети уже в кэше карточки — не спрашиваем снова.
            core = self.make_core(self.llm_settings, semantic=False)
            card = await run_in_threadpool(core.topic_card, query, kind)
        return card_to_contract(card)

    async def warmup(self) -> None:
        started = time.monotonic()
        await run_in_threadpool(self.embedder.check_remote)
        if self.embedder.available:
            try:
                await run_in_threadpool(self.core.warmup)
                await run_in_threadpool(self.embedder.encode, ["Красноярск"], "topic")
                self.embedder.warm = True
            except EmbeddingsUnavailableError:
                pass  # модели смысла нет — состояние на странице стенда
        if not self.embedder.warm:
            await run_in_threadpool(self.events.signs, "Красноярск")  # признаки события
        self.warmup_seconds = round(time.monotonic() - started, 1)
        log.info("Воронка прогрета за %s с (%s)", self.warmup_seconds, self.embedder.provider)

    def stand_notes(self) -> list[StandNote]:
        notes = self.embedder.notes()
        if self.warmup_seconds is not None:
            notes.append(StandNote("info", f"Воронка отбора прогрета за {self.warmup_seconds} с."))
        return notes

    def start(
        self, query: QueryContext, judge: AiJudge, ai_available: bool, vectors: VectorStore
    ) -> FunnelSession:
        del judge, ai_available  # нейросеть у воронки своя (тот же OLLAMA_URL)
        return FunnelSession(self, query, vectors)


class FunnelSession:
    """Отбор одного поиска порциями: кластеры копий и бюджет нейросети — на весь поиск."""

    def __init__(self, matcher: FunnelMatcher, query: QueryContext, vectors: VectorStore) -> None:
        self.matcher = matcher
        self.query = query
        self.vectors = vectors
        self.news = query.kind == "news-text"
        self.embed_kind: EmbedKind = "paraphrase" if self.news else "topic"
        self.release_text = query.release.text if self.news and query.release else query.text
        self.release_title = query.release.title if query.release else query.label
        self.card = (
            contract_to_card(query.topic, query.text)
            if query.topic is not None and not self.news
            else None
        )
        self._ai_failed = False
        self.llm_used = 0
        self.started = time.monotonic()
        self.seen_texts: set[tuple[str, str]] = set()
        self.cluster_of: dict[str, str] = {}
        self.cluster_title: dict[str, str] = {}
        self.included: list[tuple[str, str]] = []
        self.timings: dict[str, float] = {}

    @property
    def ai_failed(self) -> bool:
        return self._ai_failed

    def _core_for_step(self, *, semantic: bool) -> mm.FunnelMatcher:
        base = self.matcher.llm_settings
        remaining = max(0, base.max_gray - self.llm_used)
        left = max(1.0, base.deadline_s - (time.monotonic() - self.started))
        return self.matcher.make_core(
            replace(base, max_gray=remaining, deadline_s=left), semantic=semantic
        )

    async def classify(self, candidates: Sequence[Candidate]) -> list[Decision]:
        decisions: dict[str, Decision] = {}
        batch: list[mm.Candidate] = []
        for c in candidates:
            if c.text:
                repeat = (c.source_id, self.matcher.core.text_hash(c.text))
                if repeat in self.seen_texts:
                    decisions[c.id] = Decision(c.id, keep=False, cut_reason=REPEAT_REASON)
                    continue
                self.seen_texts.add(repeat)
            batch.append(
                mm.Candidate(
                    id=c.id,
                    text=c.text,
                    source_id=c.source_id,
                    title=c.title,
                    published_at=c.published_at,
                    is_repost=c.is_repost,
                )
            )
        if batch:
            for result in await self._match(batch):
                decisions[result.candidate_id] = self._decision(result)
            if not self.news:
                await run_in_threadpool(self._cluster_copies, decisions, batch)
        return [decisions.get(c.id, Decision(c.id, keep=False)) for c in candidates]

    async def _match(self, batch: list[mm.Candidate]) -> tuple[mm.MatchResult, ...]:
        embedder = self.matcher.embedder
        keys = {c.id: text_key(c.text) for c in batch if c.text}
        cached = await self.vectors.load(self.matcher.model_key, self.embed_kind, keys)
        embedder.preload(self.embed_kind, {keys[pid]: vector for pid, vector in cached.items()})
        remaining = max(0, self.matcher.llm_settings.max_gray - self.llm_used)
        try:
            report = await self._step(batch, semantic=embedder.available)
        except EmbeddingsUnavailableError:
            # Сервис эмбеддингов упал посреди шага, отката на CPU нет. Смысловая близость
            # считается до нейросети, поэтому шаг без неё повторяется с тем же бюджетом.
            report = await self._step(batch, semantic=False)
        for name, seconds in report.timings.items():
            self.timings[name] = round(self.timings.get(name, 0.0) + seconds, 3)
        status = report.llm
        self.llm_used += min(remaining, status.checked + status.unchecked)
        if status.state == "unavailable":
            self._ai_failed = True
        fresh = embedder.take_new(self.embed_kind, set(keys.values()))
        rows = [(pid, key, fresh[key]) for pid, key in keys.items() if key in fresh]
        await self.vectors.save(self.matcher.model_key, self.embed_kind, rows)
        return report.results

    async def _step(self, batch: list[mm.Candidate], *, semantic: bool) -> mm.MatchReport:
        core = self._core_for_step(semantic=semantic)
        if self.news:
            return await run_in_threadpool(core.match_news, self.release_text, batch)
        if self.card is None:
            self.card = await run_in_threadpool(core.topic_card, self.query.text, self.query.kind)
        card: mm.TopicCard = self.card
        return await run_in_threadpool(core.match_topic, card, batch, kind=self.query.kind)

    def _decision(self, r: mm.MatchResult) -> Decision:
        if not r.included:
            excluded = {f.id for f in self.card.excludes} if self.card else set()
            facet = r.facet_id if r.facet_id in excluded else None
            return Decision(r.candidate_id, keep=False, cut_facet=facet, cut_reason=r.reason)
        evidence = None
        if r.evidence is not None:
            evidence = EvidenceDraft(
                r.evidence.sentence_index,
                [(t.start, t.end) for t in r.evidence.ranges],
                r.evidence.basis,
                r.evidence.note,
            )
        relevance = r.relevance or "disputed"
        citation = (r.citation.share, tuple(r.citation.fragment_ids)) if r.citation else None
        in_release = self.news and r.placement_type is not None and relevance != "disputed"
        return Decision(
            r.candidate_id,
            keep=True,
            relevance=relevance,
            method=r.method,
            method_note=r.method_note,
            evidence=evidence,
            placement_type=r.placement_type if self.news else None,
            citation=citation if self.news else None,
            cluster="release" if in_release else None,
            cluster_kind="release" if in_release else None,
            cluster_title=f"Релиз «{self.release_title}»" if in_release else None,
        )

    def _cluster_copies(self, decisions: dict[str, Decision], batch: list[mm.Candidate]) -> None:
        """Копии одного сообщения в разных источниках — одна группа (Р9, MinHash воронки).

        Каждая оставленная запись получает ключ кластера; группа появляется, когда в
        кластере двое и больше. Копии из следующих порций встают к уже известному ключу.
        """
        new = [(c.id, c.text) for c in batch if c.text and decisions[c.id].keep]
        if not new:
            return
        everything = self.included + new
        order = {pid: index for index, (pid, _) in enumerate(everything)}
        text_of = dict(everything)
        groups = self.matcher.core.group_copies(
            [mm.Candidate(id=pid, text=text) for pid, text in everything]
        )
        for group in groups:
            members = sorted(group, key=lambda m: order[m])
            fresh = [m for m in members if m not in self.cluster_of]
            if not fresh:
                continue
            known = [self.cluster_of[m] for m in members if m in self.cluster_of]
            key = known[0] if known else self._new_cluster(text_of[members[0]])
            for pid in fresh:
                self.cluster_of[pid] = key
        for pid, text in new:
            # Одиночка — свой ключ: копии из следующих порций встанут к нему.
            if pid not in self.cluster_of:
                self.cluster_of[pid] = self._new_cluster(text)
            key = self.cluster_of[pid]
            decisions[pid] = replace(
                decisions[pid],
                cluster=key,
                cluster_kind="copies",
                cluster_title=self.cluster_title[key],
            )
        self.included = everything

    def _new_cluster(self, text: str) -> str:
        key = f"copies-{len(self.cluster_title) + 1}"
        self.cluster_title[key] = f"«{truncate_text(text, 60)}» — копии"
        return key


def create_matcher(settings: Settings) -> FunnelMatcher:
    return FunnelMatcher(settings)
