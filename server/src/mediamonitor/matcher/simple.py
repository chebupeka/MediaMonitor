"""Заглушка воронки отбора — простые правила, пока не подключена воронка «Э-Отбор».

Что делает (честно и без выдумок):
- тема и событие: совпадение основ слов запроса с текстом → «прямо» / «косвенно»;
  слабое совпадение — серая зона → нейросеть; нейросеть недоступна → «спорно,
  не проверено ИИ» (SC-08); грани «не то» из карточки темы отсекают пост;
- текст новости: доля абзацев релиза, вошедших дословно (П1) → «дословно» / «сокращено»
  / «репост», остальное с общими словами — серая зона («пересказ» решает нейросеть);
- копии одного сообщения склеиваются в кластер по фразам из трёх слов (Р9).

Метод отбора пишется честно: в пояснении сказано, что это упрощённый отбор по словам.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from mediamonitor.ai.judge import AiJudge, JudgeItem, JudgeRequest, Verdict
from mediamonitor.contract import (
    PlacementType,
    QueryKind,
    Relevance,
    SelectionMethod,
    TopicUnderstanding,
)
from mediamonitor.errors import required
from mediamonitor.labels import AI_UNAVAILABLE_NOTE, truncate_text
from mediamonitor.matcher.base import (
    Candidate,
    Decision,
    EvidenceDraft,
    QueryContext,
    StandNote,
    VectorStore,
)
from mediamonitor.normalize.query import (
    STOP_WORDS,
    ReleaseFragmentText,
    query_stems,
    release_of,
    stem,
)
from mediamonitor.normalize.text import Span, shingles, split_sentences, words
from mediamonitor.settings import Settings

SIMPLE_NOTE = "Упрощённый отбор по словам запроса (до подключения смысловой воронки)."
DIRECT_AT = 0.6
INDIRECT_AT = 0.3
COPY_JACCARD = 0.5
FRAGMENT_TAKEN = 0.8


def _stems_of(text: str) -> set[str]:
    return {stem(w) for w in words(text) if w not in STOP_WORDS and len(w) >= 3}


@dataclass
class _Cluster:
    key: str
    shingles: set[str]
    relevance: Relevance
    title: str


@dataclass
class _Rule:
    """Итог правил: решение или «серая зона» (нужна нейросеть)."""

    decision: Decision | None
    gray: bool = False
    placement: PlacementType | None = None
    citation: tuple[float, tuple[str, ...]] | None = None
    evidence: EvidenceDraft | None = None


class SimpleSession:
    def __init__(self, query: QueryContext, judge: AiJudge, ai_available: bool) -> None:
        self.query = query
        self.judge = judge
        self.ai_available = ai_available
        self._ai_failed = False
        self.stems = query_stems(query.text if query.kind != "news-text" else "")
        topic = query.topic
        if topic is not None:
            for facet in topic.includes:
                if facet.origin == "user":
                    self.stems += [s for s in query_stems(facet.label) if s not in self.stems]
        self.exclude = {
            f.id: (f.label, set(query_stems(f.label))) for f in (topic.excludes if topic else [])
        }
        release = query.release
        self.fragments = (
            [(f.id, f.text, shingles(f.text)) for f in release.fragments] if release else []
        )
        self.release_shingles: set[str] = (
            set().union(*(sh for _, _, sh in self.fragments)) if self.fragments else set()
        )
        self.release_stems = (
            _stems_of(" ".join(f.text for f in release.fragments[:2])) if release else set()
        )
        self.release_length = sum(len(t) for _, t, _ in self.fragments) or 1
        self.clusters: list[_Cluster] = []

    @property
    def ai_failed(self) -> bool:
        return self._ai_failed

    # ------------------------------------------------------------ правила

    def _best_sentence(self, candidate: Candidate, stems: set[str]) -> tuple[int, list[str]]:
        text = candidate.text or ""
        best, best_hits = 0, -1
        best_words: list[str] = []
        for index, span in enumerate(candidate.sentences):
            sentence_words = [w for w in words(text[span.start : span.end]) if stem(w) in stems]
            if len(sentence_words) > best_hits:
                best, best_hits, best_words = index, len(sentence_words), sentence_words
        return best, best_words

    def _sentence_evidence(
        self, candidate: Candidate, index: int, note: str | None
    ) -> EvidenceDraft:
        span = candidate.sentences[index]
        return EvidenceDraft(index, [(span.start, span.end)], "semantic", note)

    def _topic_rule(self, candidate: Candidate) -> _Rule:
        text_stems = _stems_of(f"{candidate.title or ''} {candidate.text or ''}")
        query = set(self.stems)
        if not candidate.text or not candidate.sentences:
            return _Rule(
                Decision(
                    candidate.id,
                    keep=True,
                    relevance="disputed",
                    method="semantic",
                    method_note="Текст отсутствует: пост из картинок или видео — проверьте сами.",
                )
            )
        overlap = len(query & text_stems) / len(query) if query else 0.0
        for facet_id, (label, facet_stems) in self.exclude.items():
            if not facet_stems:
                continue
            ex_overlap = len(facet_stems & text_stems) / len(facet_stems)
            if ex_overlap >= 0.5 and ex_overlap > overlap:
                return _Rule(
                    Decision(
                        candidate.id,
                        keep=False,
                        cut_facet=facet_id,
                        cut_reason=f"Это «{label}» — не то",
                    )
                )
        index, found = self._best_sentence(candidate, query)
        if overlap >= DIRECT_AT or overlap >= INDIRECT_AT:
            relevance: Relevance = "direct" if overlap >= DIRECT_AT else "indirect"
            shown = ", ".join(f"«{w}»" for w in dict.fromkeys(found)) or "слова запроса"
            evidence = self._sentence_evidence(candidate, index, f"Совпадают слова: {shown}")
            return _Rule(
                Decision(
                    candidate.id,
                    keep=True,
                    relevance=relevance,
                    method="semantic",
                    method_note=SIMPLE_NOTE,
                    evidence=evidence,
                ),
            )
        return _Rule(None, gray=True, evidence=self._sentence_evidence(candidate, index, None))

    def _release_rule(self, candidate: Candidate) -> _Rule:
        text = candidate.text or ""
        if not text or not candidate.sentences:
            return _Rule(Decision(candidate.id, keep=False))
        post_shingles = shingles(text)
        taken: list[str] = []
        ranges: list[tuple[int, int]] = []
        for fragment_id, fragment_text, fragment_shingles in self.fragments:
            if not fragment_shingles:
                continue
            if len(fragment_shingles & post_shingles) / len(fragment_shingles) >= FRAGMENT_TAKEN:
                taken.append(fragment_id)
                at = text.find(fragment_text)
                if at >= 0:
                    ranges.append((at, at + len(fragment_text)))
        share = round(
            sum(len(t) for fid, t, _ in self.fragments if fid in taken) / self.release_length, 2
        )
        from_release = (
            len(post_shingles & self.release_shingles) / len(post_shingles)
            if post_shingles
            else 0.0
        )
        if candidate.is_repost and (taken or from_release >= 0.3):
            placement: PlacementType | None = "repost"
        elif share >= 0.9:
            placement = "verbatim"
        elif taken or from_release >= 0.25:
            placement = "shortened"
        else:
            placement = None
        if placement is not None:
            if not ranges:
                index, _ = self._best_sentence(candidate, self.release_stems)
                span = candidate.sentences[index]
                ranges = [(span.start, span.end)]
            first = ranges[0][0]
            index = next(
                (i for i, s in enumerate(candidate.sentences) if s.start <= first < s.end), 0
            )
            percent = round(share * 100)
            evidence = EvidenceDraft(
                index, sorted(ranges), "release-match", f"Совпадает с релизом: {percent}% текста"
            )
            return _Rule(
                Decision(
                    candidate.id,
                    keep=True,
                    relevance="direct",
                    method="copy",
                    evidence=evidence,
                    placement_type=placement,
                    citation=(share, tuple(taken)),
                    cluster="release",
                    cluster_kind="release",
                    cluster_title=f"Релиз «{self.query.release.title}»"
                    if self.query.release
                    else None,
                )
            )
        text_stems = _stems_of(text)
        overlap = (
            len(self.release_stems & text_stems) / len(self.release_stems)
            if self.release_stems
            else 0.0
        )
        if overlap >= 0.15:
            index, _ = self._best_sentence(candidate, self.release_stems)
            return _Rule(
                None,
                gray=True,
                placement="retold" if overlap >= 0.4 else None,
                citation=(0.0, ()) if overlap >= 0.4 else None,
                evidence=self._sentence_evidence(candidate, index, None),
            )
        return _Rule(Decision(candidate.id, keep=False))

    # ------------------------------------------------------------ копии

    def _cluster(self, candidate: Candidate, decision: Decision) -> Decision:
        if decision.cluster is not None or not decision.keep or not candidate.text:
            return decision
        sh = shingles(candidate.text)
        if len(sh) < 5:
            return decision
        for cluster in self.clusters:
            union = len(sh | cluster.shingles)
            jaccard = len(sh & cluster.shingles) / union if union else 0.0
            if jaccard >= COPY_JACCARD:
                return Decision(
                    decision.id,
                    keep=True,
                    relevance=cluster.relevance,
                    method="copy" if decision.method != "manual" else "manual",
                    method_note=None,
                    evidence=decision.evidence,
                    placement_type="verbatim" if jaccard >= 0.9 else "shortened",
                    cluster=cluster.key,
                    cluster_kind="copies",
                    cluster_title=cluster.title,
                )
        key = f"copies-{len(self.clusters) + 1}"
        title = f"«{truncate_text(candidate.title or candidate.text, 60)}» — копии"
        self.clusters.append(_Cluster(key, sh, decision.relevance, title))
        return Decision(
            decision.id,
            keep=True,
            relevance=decision.relevance,
            method=decision.method,
            method_note=decision.method_note,
            evidence=decision.evidence,
            placement_type="verbatim",
            cluster=key,
            cluster_kind="copies",
            cluster_title=title,
        )

    # ------------------------------------------------------------ серая зона

    async def _ask_ai(self, gray: list[tuple[Candidate, _Rule]]) -> dict[str, Verdict]:
        if not gray or not self.ai_available:
            return {}
        internal = {f"c{i + 1}": cand for i, (cand, _) in enumerate(gray)}
        items = [
            JudgeItem(cid, [(c.text or "")[s.start : s.end] for s in c.sentences])
            for cid, c in internal.items()
        ]
        topic = self.query.topic
        request = JudgeRequest(
            query=self.query.text[:4000],
            includes=[f.label for f in topic.includes] if topic else [],
            excludes=[f.label for f in topic.excludes] if topic else [],
            items=items,
        )
        failures_before = self.judge.stats.failures
        verdicts = await self.judge.judge(request)
        if self.judge.stats.failures > failures_before:
            self._ai_failed = True
        return {internal[cid].id: v for cid, v in verdicts.items()}

    def _from_verdict(self, candidate: Candidate, rule: _Rule, verdict: Verdict | None) -> Decision:
        if verdict is None:
            evidence = rule.evidence
            return Decision(
                candidate.id,
                keep=True,
                relevance="disputed",
                method="ai-unchecked",
                method_note=AI_UNAVAILABLE_NOTE,
                evidence=evidence,
                placement_type=rule.placement,
                citation=rule.citation,
                cluster="release" if rule.placement else None,
                cluster_kind="release" if rule.placement else None,
                cluster_title=f"Релиз «{self.query.release.title}»"
                if rule.placement and self.query.release
                else None,
            )
        if verdict.label == "unrelated":
            return Decision(
                candidate.id, keep=False, cut_reason="Нейросеть: не относится к запросу"
            )
        span = candidate.sentences[verdict.sentence]
        method: SelectionMethod = "ai-confirmed"
        placement = rule.placement if verdict.label == "direct" else None
        return Decision(
            candidate.id,
            keep=True,
            relevance=verdict.label,
            method=method,
            evidence=EvidenceDraft(verdict.sentence, [(span.start, span.end)], "ai", None),
            placement_type=placement,
            citation=rule.citation if placement else None,
            cluster="release" if placement else None,
            cluster_kind="release" if placement else None,
            cluster_title=f"Релиз «{self.query.release.title}»"
            if placement and self.query.release
            else None,
        )

    async def classify(self, candidates: Sequence[Candidate]) -> list[Decision]:
        rules: list[tuple[Candidate, _Rule]] = []
        for candidate in candidates:
            rule = (
                self._release_rule(candidate)
                if self.query.kind == "news-text"
                else self._topic_rule(candidate)
            )
            rules.append((candidate, rule))
        gray = [(c, r) for c, r in rules if r.gray]
        verdicts = await self._ask_ai(gray)
        decisions: list[Decision] = []
        for candidate, rule in rules:
            decision = (
                rule.decision
                if not rule.gray
                else self._from_verdict(candidate, rule, verdicts.get(candidate.id))
            )
            decision = required(decision, "decision")
            if self.query.kind != "news-text":
                decision = self._cluster(candidate, decision)
            decisions.append(decision)
        return decisions


class SimpleMatcher:
    """Заглушка без моделей: для тестов и для стенда без воронки."""

    name = "simple"

    def split_sentences(self, text: str) -> list[Span]:
        return split_sentences(text)

    def release_fragments(self, text: str) -> tuple[ReleaseFragmentText, ...]:
        return release_of(text).fragments

    async def topic_card(
        self, text: str, kind: QueryKind, meaning: str | None
    ) -> TopicUnderstanding | None:
        del text, kind, meaning
        return None  # карточку составит сервер (TopicService)

    async def warmup(self) -> None:
        return None

    def stand_notes(self) -> list[StandNote]:
        return [StandNote("warning", "Отбор: упрощённая заглушка по словам, без модели смысла.")]

    def start(
        self, query: QueryContext, judge: AiJudge, ai_available: bool, vectors: VectorStore
    ) -> SimpleSession:
        del vectors
        return SimpleSession(query, judge, ai_available)


def create_matcher(settings: Settings | None = None) -> SimpleMatcher:
    del settings
    return SimpleMatcher()
