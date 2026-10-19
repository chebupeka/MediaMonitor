"""Воронка отбора (Р5): хеш → шинглы → смысл → признаки события → правила → нейросеть.

Каждый шаг дешевле следующего и решает «явно да» / «явно нет»; до нейросети
доходит только серая зона. Без нейросети серая зона остаётся в подборке с
меткой «Спорно — проверьте» и методом «не проверено ИИ».
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum

import numpy as np

from mm_matching.config import LlmSettings, MatcherConfig
from mm_matching.embeddings import Embedder, SentenceTransformerEmbedder
from mm_matching.events import EventComparison, EventExtractor
from mm_matching.guard import (
    NEWS_LABELS,
    TOPIC_LABELS,
    InvalidResponseError,
    Verdict,
    has_injection,
    new_nonce,
    news_prompt,
    parse_verdicts,
    prompt_post,
    topic_prompt,
    verdict_schema,
)
from mm_matching.llm import LlmClient, LlmError, client_from_env
from mm_matching.placement import placement_type
from mm_matching.shingles import (
    Overlap,
    ReleaseParagraphs,
    ShingledText,
    citation,
    fragment_map,
    group_copies,
    overlap,
    release_paragraphs,
    shingle,
)
from mm_matching.text import content_stems, split_sentences, text_hash, tokenize
from mm_matching.topic import apply_correction, expand_query, fallback_card, llm_card
from mm_matching.types import (
    Candidate,
    EventSigns,
    Evidence,
    EvidenceBasis,
    Excerpt,
    LlmState,
    LlmStatus,
    MatchReport,
    MatchResult,
    QueryKind,
    Relevance,
    Scores,
    SelectionMethod,
    Sentence,
    Stage,
    TextRange,
    TopicCard,
    Zone,
)


class _Default(Enum):
    TOKEN = 0


DEFAULT = _Default.TOKEN
OnResult = Callable[[MatchResult], None]

NOTE_AI_OFF = "Смысловая проверка недоступна: нейросеть не подключена"
NOTE_AI_DOWN = "Смысловая проверка недоступна: нейросеть не отвечает"
NOTE_AI_INVALID = "Ответ нейросети не прошёл проверку — проверьте вручную"
NOTE_AI_UNSURE = "Нейросеть не смогла решить — проверьте"
NOTE_AI_BUDGET = "Не хватило времени на проверку нейросетью — проверьте"
NOTE_AI_INJECTION = "В тексте есть фразы-команды для нейросети — проверьте вручную"
NOTE_AI_UNSUPPORTED = "Ответ нейросети не подтверждается текстом — проверьте"
EXCERPT_CHARS = 300


@dataclass(slots=True)
class _Work:
    """Рабочее состояние по одному кандидату внутри поиска."""

    index: int
    cand: Candidate
    text: str
    sentences: tuple[Sentence, ...]
    sh: ShingledText
    ov: Overlap | None = None
    cos: float | None = None
    anti: float | None = None
    facet_id: str | None = None
    cmp: EventComparison | None = None
    zone: Zone = "gray"
    stage: Stage = "rules"
    reason: str = ""
    verdict: Verdict | None = None
    unchecked: str | None = None
    extra: dict[str, float] = field(default_factory=dict)


class _Timer:
    def __init__(self) -> None:
        self.start = self.last = time.perf_counter()
        self.laps: dict[str, float] = {}

    def lap(self, name: str) -> None:
        now = time.perf_counter()
        self.laps[name] = round(self.laps.get(name, 0.0) + now - self.last, 4)
        self.last = now

    def done(self) -> dict[str, float]:
        self.laps["total"] = round(time.perf_counter() - self.start, 4)
        return self.laps


class FunnelMatcher:
    """Реализация интерфейса `Matcher`.

    Зависимости подменяются: `embedder=None` — без смыслового шага (только фразы и
    признаки), `llm=None` — без нейросети, `events=None` — без признаков события.
    По умолчанию модель эмбеддингов из конфига, нейросеть — по `OLLAMA_URL`.
    """

    def __init__(
        self,
        config: MatcherConfig | None = None,
        *,
        embedder: Embedder | _Default | None = DEFAULT,
        llm: LlmClient | _Default | None = DEFAULT,
        events: EventExtractor | _Default | None = DEFAULT,
        llm_settings: LlmSettings | None = None,
    ) -> None:
        self.config = config or MatcherConfig.from_env()
        self.llm_settings = llm_settings or LlmSettings.from_env()
        if isinstance(embedder, _Default):
            embedder = SentenceTransformerEmbedder(
                self.config.embedding_model,
                max_chunk_chars=self.config.max_chunk_chars,
                max_chunks=self.config.max_chunks,
            )
        if isinstance(llm, _Default):
            llm = client_from_env(self.llm_settings)
        if isinstance(events, _Default):
            events = EventExtractor()
        self.embedder: Embedder | None = embedder
        self.llm: LlmClient | None = llm
        self.events: EventExtractor | None = events

    # ------------------------------------------------------------------ служебное

    def warmup(self) -> None:
        """Загрузить модели заранее (при старте сервера), чтобы первый поиск не ждал."""
        if self.embedder is not None:
            self.embedder.encode(["Красноярск"], "paraphrase")
        if self.events is not None:
            self.events.signs("Красноярск")

    def prefetch(self, candidates: Sequence[Candidate], kind: QueryKind) -> None:
        """Посчитать векторы постов заранее, пока сборщик ещё получает остальные.

        Самый дорогой шаг — эмбеддинги (~0,2–0,4 с на пост на CPU). Если звать его
        по мере прихода постов, к концу сбора векторы уже в кеше и отбор занимает секунды.
        """
        if self.embedder is None:
            return
        texts = [c.text for c in candidates if c.text and c.text.strip()]
        if texts:
            self.embedder.encode(texts, "paraphrase" if kind == "news-text" else "topic")

    def split_sentences(self, text: str) -> list[Sentence]:
        return split_sentences(text)

    def text_hash(self, text: str) -> str:
        return text_hash(text)

    def find_repeats(self, candidates: Sequence[Candidate]) -> dict[str, str]:
        """Повторы одного поста (ТЗ-Ф30): тот же источник и тот же нормализованный текст.

        Возвращает id повтора → id записи, которую оставляем. Копии в разных
        источниках — отдельные размещения (ТЗ-Ф29), их здесь нет: см. `group_copies`.
        Без `source_id` повтор по тексту не ищется — только по ключу поста на сервере.
        """
        seen: dict[tuple[str, str], str] = {}
        out: dict[str, str] = {}
        for c in candidates:
            if not c.text or c.source_id is None:
                continue
            key = (c.source_id, text_hash(c.text))
            if key in seen:
                out[c.id] = seen[key]
            else:
                seen[key] = c.id
        return out

    def group_copies(self, candidates: Sequence[Candidate], threshold: float = 0.8) -> list[list[str]]:
        """Группы почти одинаковых текстов в разных источниках (MinHash LSH)."""
        return group_copies([(c.id, c.text) for c in candidates if c.text], threshold)

    def event_signs(self, text: str) -> EventSigns:
        if self.events is None:
            return EventSigns()
        return self.events.signs(text)

    def topic_card(self, query: str, kind: QueryKind = "topic") -> TopicCard:
        """«Как система поняла тему»: нейросеть, а без неё — правила по словам запроса."""
        card: TopicCard | None = None
        note: str | None = None
        if self.llm is not None and self.llm.available():
            card = llm_card(query, self.llm)
            if card is None:
                note = "Карточка собрана по словам запроса: ответ нейросети не прошёл проверку."
        card = card or fallback_card(query, note)
        if kind != "topic" and self.events is not None:
            card = replace(card, signs=self.events.signs(query))
        return card

    def correct_topic_card(
        self,
        card: TopicCard,
        *,
        include: Sequence[str] = (),
        exclude: Sequence[str] = (),
        add_includes: Sequence[str] = (),
        add_excludes: Sequence[str] = (),
    ) -> TopicCard:
        return apply_correction(
            card, include=include, exclude=exclude, add_includes=add_includes, add_excludes=add_excludes
        )

    # ------------------------------------------------------------------ по тексту новости

    def match_news(
        self, release_text: str, candidates: Sequence[Candidate], *, on_result: OnResult | None = None
    ) -> MatchReport:
        """Поиск перепечаток и пересказов исходной новости (сценарий 2, ТЗ-Ф23, Ф24)."""
        cfg = self.config.news
        timer = _Timer()
        release_sh = shingle(release_text)
        release_h = text_hash(release_text)
        paras = release_paragraphs(release_sh)
        release_stems = content_stems(list(release_sh.tokens))
        works, results = self._prepare(candidates, on_result)

        for w in works:
            ov = overlap(release_sh, w.sh)
            w.ov = ov
            if text_hash(w.text) == release_h:
                self._decide(w, "yes", "hash", "Копия: текст совпадает с исходной новостью")
            elif ov.release_share >= cfg.copy_release_share or (
                ov.post_share >= cfg.copy_post_share and ov.matched_tokens >= cfg.copy_min_tokens
            ):
                # Частичное совпадение бывает и у разных новостей одного ведомства (шаблонные
                # фразы пресс-службы). Если место и дата другие и ничего не совпало — не копия.
                if ov.release_share < cfg.copy_sure_share and self.events is not None:
                    w.cmp = self.events.compare(release_text, w.text)
                    if w.cmp.conflict >= cfg.copy_conflict_for_no and w.cmp.support == 0:
                        reason = "Другое событие: общие только шаблонные фразы; " + _differs(w.cmp)
                        self._decide(w, "no", "events", reason)
                        continue
                pct = round(ov.release_share * 100)
                self._decide(w, "yes", "shingles", f"Копия: дословно совпадает {pct}% текста новости")
        timer.lap("shingles")

        pending = [w for w in works if w.stage == "rules"]
        self._news_similarity(release_text, release_stems, pending)
        timer.lap("embeddings")

        for w in pending:
            self._news_rules(release_text, w)
        timer.lap("events")

        finished = [w for w in works if w.zone != "gray"]
        for w in finished:
            results[w.index] = self._emit(self._news_result(w, paras, release_stems), on_result)

        gray = [w for w in works if w.zone == "gray"]
        nonce = new_nonce()

        def build(post_pid: str, w: _Work) -> tuple[str, str, int]:
            pp = prompt_post(post_pid, w.text, w.sentences)
            system, user = news_prompt(release_text, [pp], nonce)
            return system, user, len(pp.sentences)

        def finish(w: _Work) -> None:
            results[w.index] = self._emit(self._news_result(w, paras, release_stems), on_result)

        status = self._run_llm(gray, build, NEWS_LABELS, finish)
        timer.lap("llm")

        final = tuple(r for r in results if r is not None)
        cits = [r.citation for r in final if r.included]
        return MatchReport(
            results=final, llm=status, fragments=fragment_map(release_text, cits), timings=timer.done()
        )

    def _news_similarity(self, release_text: str, release_stems: set[str], pending: list[_Work]) -> None:
        if not pending:
            return
        if self.embedder is not None:
            vecs = self.embedder.encode([release_text] + [w.text for w in pending], "paraphrase")
            sims = vecs[1:] @ vecs[0]
            for w, s in zip(pending, sims, strict=True):
                w.cos = float(s)
        else:
            for w in pending:
                w.extra["lexical"] = _stem_overlap(release_stems, content_stems(list(w.sh.tokens)))

    def _news_rules(self, release_text: str, w: _Work) -> None:
        cfg = self.config.news
        if w.cos is None:  # без эмбеддингов: только фразы и признаки события
            if w.extra.get("lexical", 0.0) < 0.15:
                self._decide(w, "no", "rules", "Не похоже на исходную новость")
                return
        elif w.cos < cfg.cos_no:
            self._decide(w, "no", "embeddings", "Не похоже по смыслу на исходную новость")
            return
        if self.events is not None:
            w.cmp = self.events.compare(release_text, w.text)
        sup = w.cmp.support if w.cmp else 0
        con = w.cmp.conflict if w.cmp else 0
        if con >= cfg.conflict_for_no and sup == 0 and w.cmp is not None:
            self._decide(w, "no", "events", "Другое событие: " + _differs(w.cmp))
        elif w.cos is not None and w.cos >= cfg.cos_yes and con == 0:
            self._decide(w, "yes", "embeddings", "Пересказ: высокая смысловая близость" + _shared(w.cmp))
        elif w.cos is not None and w.cos >= cfg.cos_supported and sup >= cfg.support_for_yes and con == 0:
            self._decide(w, "yes", "events", "Пересказ: близко по смыслу" + _shared(w.cmp))
        else:
            self._decide(w, "gray", "rules", "Спорно: похоже по смыслу, но это может быть другое событие")

    def _news_result(self, w: _Work, paras: ReleaseParagraphs, release_stems: set[str]) -> MatchResult:
        assert w.ov is not None
        ov = w.ov
        scores = Scores(
            release_share=round(ov.release_share, 4),
            post_share=round(ov.post_share, 4),
            cosine=_r(w.cos),
            event_support=w.cmp.support if w.cmp else None,
            event_conflict=w.cmp.conflict if w.cmp else None,
        )
        shared_words = list(w.cmp.shared) if w.cmp else []
        if w.zone == "yes" and w.stage in ("hash", "shingles"):
            idx = _best_copy_sentence(w, ov)
            ranges = ov.post_ranges or (TextRange(w.sentences[idx].start, w.sentences[idx].end),)
            copy_ev: Evidence | None = Evidence(idx, ranges, "release-match", w.reason)
            return self._result(w, True, "direct", "copy", None, copy_ev, ov, paras, scores)
        if w.zone == "yes":
            idx = _best_lexical_sentence(w, release_stems, shared_words)
            ev = _sentence_evidence(w, idx, "semantic", w.reason)
            return self._result(w, True, "direct", "semantic", None, ev, ov, paras, scores)
        if w.zone == "no":
            idx = _best_lexical_sentence(w, release_stems, shared_words)
            ev = _sentence_evidence(w, idx, "semantic", w.reason)
            return self._result(w, False, None, "semantic", None, ev, None, paras, scores)
        return self._gray_result(
            w, release_stems, shared_words, ov, paras, scores, positive="same_event", min_shared=2
        )

    # ------------------------------------------------------------------ по теме или событию

    def match_topic(
        self,
        query: str | TopicCard,
        candidates: Sequence[Candidate],
        *,
        kind: QueryKind = "topic",
        on_result: OnResult | None = None,
    ) -> MatchReport:
        """Отбор по теме или событию своими словами (сценарий 1, ТЗ-Ф22).

        `query` — текст запроса (карточка составится сама) или уже показанная и
        поправленная пользователем карточка темы.
        """
        timer = _Timer()
        card = query if isinstance(query, TopicCard) else self.topic_card(query, kind)
        timer.lap("card")
        works, results = self._prepare(candidates, on_result)
        # Близость к теме считаем по самому запросу и по граням, которые добавил
        # пользователь. Системные грани «входит» на мини-эталоне не помогали (только
        # размывали тему), они идут в карточку и в нейросеть. «Не то» — все грани.
        query_text = expand_query(card.query)
        inc = [f for f in card.includes if f.origin == "user" and f.label != query_text]
        inc_labels = [query_text] + [f.label for f in inc]
        inc_ids: list[str | None] = [None] + [f.id for f in inc]
        exc = list(card.excludes)
        query_stems = content_stems(tokenize(" ".join([query_text] + [f.label for f in card.includes])))

        if works and self.embedder is not None:
            qv = self.embedder.encode(inc_labels + [f.label for f in exc], "topic")
            dv = self.embedder.encode([w.text for w in works], "topic")
            sims = dv @ qv.T
            pos = sims[:, : len(inc_labels)]
            for i, w in enumerate(works):
                best = int(np.argmax(pos[i]))
                w.cos = float(pos[i, best])
                w.facet_id = inc_ids[best]
                if exc:
                    neg = sims[i, len(inc_labels) :]
                    j = int(np.argmax(neg))
                    w.anti = float(neg[j])
                    w.extra["anti_facet"] = float(j)
        timer.lap("embeddings")

        for w in works:
            self._topic_rules(w, card, kind, query_stems)
        timer.lap("events")

        for w in works:
            if w.zone != "gray":
                results[w.index] = self._emit(self._topic_result(w, query_stems), on_result)

        gray = [w for w in works if w.zone == "gray"]
        nonce = new_nonce()
        inc_texts = [f.label for f in card.includes]
        exc_texts = [f.label for f in card.excludes]

        def build(post_pid: str, w: _Work) -> tuple[str, str, int]:
            pp = prompt_post(post_pid, w.text, w.sentences)
            system, user = topic_prompt(card.query, inc_texts, exc_texts, [pp], nonce)
            return system, user, len(pp.sentences)

        def finish(w: _Work) -> None:
            results[w.index] = self._emit(self._topic_result(w, query_stems), on_result)

        status = self._run_llm(gray, build, TOPIC_LABELS, finish)
        timer.lap("llm")
        final = tuple(r for r in results if r is not None)
        return MatchReport(results=final, llm=status, timings=timer.done())

    def _topic_rules(self, w: _Work, card: TopicCard, kind: QueryKind, query_stems: set[str]) -> None:
        cfg = self.config.topic
        if w.cos is None:
            lex = _stem_overlap(query_stems, content_stems(list(w.sh.tokens)))
            w.extra["lexical"] = lex
            if lex < 0.2:
                self._decide(w, "no", "rules", "Не по теме: нет общих слов с темой")
            else:
                self._decide(w, "gray", "rules", "Спорно: есть общие слова с темой")
            return
        anti = w.anti if w.anti is not None else -1.0
        margin = w.cos - anti
        exc_label = None
        if w.anti is not None:
            exc_facet = card.excludes[int(w.extra["anti_facet"])]
            exc_label = exc_facet.label
        if w.cos < cfg.sim_no:
            self._decide(w, "no", "embeddings", "Не по теме")
            return
        if exc_label is not None and margin <= cfg.margin_no:
            w.facet_id = card.excludes[int(w.extra["anti_facet"])].id
            self._decide(w, "no", "embeddings", f"Не то: ближе к теме «{exc_label}»")
            return
        if kind == "event" and self.events is not None:
            w.cmp = self.events.compare(card.query, w.text)
            if w.cmp.conflict >= self.config.news.conflict_for_no and w.cmp.support == 0:
                self._decide(w, "no", "events", "Другое событие: " + _differs(w.cmp))
                return
        if w.cos >= cfg.sim_yes and margin >= cfg.margin_yes:
            self._decide(w, "yes", "embeddings", "По теме: высокая смысловая близость")
        else:
            self._decide(w, "gray", "rules", "Спорно: тема затронута, но связь неочевидна")

    def _topic_result(self, w: _Work, query_stems: set[str]) -> MatchResult:
        cfg = self.config.topic
        scores = Scores(
            cosine=_r(w.cos),
            anti_cosine=_r(w.anti),
            event_support=w.cmp.support if w.cmp else None,
            event_conflict=w.cmp.conflict if w.cmp else None,
        )
        shared_words = list(w.cmp.shared) if w.cmp else []
        if w.zone == "yes":
            rel: Relevance = "direct" if (w.cos or 0.0) >= cfg.sim_direct else "indirect"
            idx = _best_lexical_sentence(w, query_stems, shared_words)
            ev = _sentence_evidence(w, idx, "semantic", w.reason)
            return self._result(w, True, rel, "semantic", None, ev, None, None, scores)
        if w.zone == "no":
            idx = _best_lexical_sentence(w, query_stems, shared_words)
            ev = _sentence_evidence(w, idx, "semantic", w.reason)
            return self._result(w, False, None, "semantic", None, ev, None, None, scores)
        return self._gray_result(
            w, query_stems, shared_words, None, None, scores, positive="direct", min_shared=1
        )

    # ------------------------------------------------------------------ общее

    def _prepare(
        self, candidates: Sequence[Candidate], on_result: OnResult | None
    ) -> tuple[list[_Work], list[MatchResult | None]]:
        works: list[_Work] = []
        results: list[MatchResult | None] = [None] * len(candidates)
        for i, c in enumerate(candidates):
            text = c.text or ""
            sh = shingle(text) if text.strip() else None
            if sh is None or not sh.tokens:
                results[i] = self._emit(_no_text(c), on_result)
                continue
            works.append(_Work(i, c, text, tuple(split_sentences(text)), sh))
        return works, results

    @staticmethod
    def _decide(w: _Work, zone: Zone, stage: Stage, reason: str) -> None:
        w.zone, w.stage, w.reason = zone, stage, reason

    @staticmethod
    def _emit(result: MatchResult, on_result: OnResult | None) -> MatchResult:
        if on_result is not None:
            on_result(result)
        return result

    def _result(
        self,
        w: _Work,
        included: bool,
        relevance: Relevance | None,
        method: SelectionMethod,
        method_note: str | None,
        ev: Evidence | None,
        ov: Overlap | None,
        paras: ReleaseParagraphs | None,
        scores: Scores,
        stage: Stage | None = None,
    ) -> MatchResult:
        placement = None
        cit = None
        if included and ov is not None and paras is not None:
            placement = placement_type(ov, is_repost=w.cand.is_repost, thresholds=self.config.placement)
            cit = citation(ov, paras, self.config.placement.fragment_taken)
        excerpt = _excerpt(w.text, w.sentences, ev.sentence_index) if ev is not None else None
        return MatchResult(
            candidate_id=w.cand.id,
            included=included,
            relevance=relevance,
            method=method,
            method_note=method_note,
            reason=w.reason,
            stage=stage or w.stage,
            zone=w.zone,
            sentences=w.sentences,
            evidence=ev,
            excerpt=excerpt,
            placement_type=placement,
            citation=cit,
            text_hash=text_hash(w.text),
            scores=scores,
            facet_id=w.facet_id,
        )

    def _gray_result(
        self,
        w: _Work,
        ref_stems: set[str],
        shared_words: list[str],
        ov: Overlap | None,
        paras: ReleaseParagraphs | None,
        scores: Scores,
        *,
        positive: str,
        min_shared: int,
    ) -> MatchResult:
        """Решение по серой зоне: по ответу нейросети или «не проверено ИИ».

        Положительный ответ принимаем, только если предложение-доказательство само
        похоже на запрос: не меньше `min_shared` общих основ слов или общий признак
        события. Так «послушная» ловушке нейросеть не протолкнёт пост в «Прямо».
        """
        v = w.verdict
        if v is None:
            idx = _best_lexical_sentence(w, ref_stems, shared_words)
            ev = _sentence_evidence(w, idx, "semantic", w.reason)
            note = w.unchecked or NOTE_AI_OFF
            return self._result(w, True, "disputed", "ai-unchecked", note, ev, ov, paras, scores)
        ev = _sentence_evidence(w, v.sentence, "ai", "Нейросеть решила по этому предложению")
        if v.label in (positive, "indirect"):
            sent = w.sentences[v.sentence]
            sent_stems = content_stems(tokenize(w.text[sent.start : sent.end]))
            if len(sent_stems & ref_stems) < min_shared and not _has_shared(w.text, sent, shared_words):
                w.reason = "Спорно: нейросеть ответила «да», но предложение не похоже на запрос"
                return self._result(
                    w, True, "disputed", "ai-unchecked", NOTE_AI_UNSUPPORTED, ev, ov, paras, scores, "llm"
                )
            rel: Relevance = "indirect" if v.label == "indirect" else "direct"
            w.reason = "Подтверждено ИИ" + ("" if rel == "direct" else ": тема затронута косвенно")
            return self._result(w, True, rel, "ai-confirmed", None, ev, ov, paras, scores, "llm")
        if v.label == "cannot_tell":
            w.reason = "Спорно: нейросеть не смогла решить"
            return self._result(
                w, True, "disputed", "ai-unchecked", NOTE_AI_UNSURE, ev, ov, paras, scores, "llm"
            )
        w.reason = {
            "other_event": "Другое событие (по проверке ИИ)",
            "unrelated": "Не об этом (по проверке ИИ)",
            "not_related": "Не по теме (по проверке ИИ)",
        }.get(v.label, "Не подходит (по проверке ИИ)")
        return self._result(w, False, None, "ai-confirmed", None, ev, None, None, scores, "llm")

    def _run_llm(
        self,
        gray: list[_Work],
        build: Callable[[str, _Work], tuple[str, str, int]],
        labels: Sequence[str],
        finish: Callable[[_Work], None],
    ) -> LlmStatus:
        """Серая зона → нейросеть по одному посту (чужой пост не влияет на соседа)."""
        if not gray:
            return LlmStatus("not-needed")
        llm = self.llm
        if llm is None:
            for w in gray:
                w.unchecked = NOTE_AI_OFF
                finish(w)
            return LlmStatus("not-configured", 0, len(gray), NOTE_AI_OFF)
        if not llm.available():
            for w in gray:
                w.unchecked = NOTE_AI_DOWN
                finish(w)
            return LlmStatus("unavailable", 0, len(gray), NOTE_AI_DOWN)
        s = self.llm_settings
        deadline = time.monotonic() + s.deadline_s
        checked = 0
        failures = 0
        down = False
        for k, w in enumerate(gray):
            if down:
                w.unchecked = NOTE_AI_DOWN
            elif has_injection(w.text):
                w.unchecked = NOTE_AI_INJECTION
            elif k >= s.max_gray or time.monotonic() > deadline:
                w.unchecked = NOTE_AI_BUDGET
            else:
                pid = f"p{k + 1}"
                system, user, n_sent = build(pid, w)
                try:
                    raw = llm.chat_json(system, user, verdict_schema([pid], labels, n_sent))
                    verdicts = parse_verdicts(raw, {pid: n_sent}, labels)
                    w.verdict = verdicts.get(pid)
                    w.unchecked = None if w.verdict else NOTE_AI_INVALID
                    checked += 1 if w.verdict else 0
                    failures = 0
                except InvalidResponseError:
                    w.unchecked = NOTE_AI_INVALID
                except LlmError:
                    w.unchecked = NOTE_AI_DOWN
                    failures += 1
                    down = failures >= 2  # два отказа подряд — дальше не ждём
                    if down and hasattr(llm, "mark_unavailable"):
                        llm.mark_unavailable()
            finish(w)
        unchecked = len(gray) - checked
        state: LlmState = (
            "used" if unchecked == 0 else ("unavailable" if checked == 0 and down else "partial")
        )
        msg = None if state == "used" else f"Нейросеть проверила {checked} из {len(gray)} спорных"
        return LlmStatus(state, checked, unchecked, msg)


# ---------------------------------------------------------------------- помощники


def _r(x: float | None) -> float | None:
    return None if x is None else round(x, 4)


def _no_text(c: Candidate) -> MatchResult:
    return MatchResult(
        candidate_id=c.id,
        included=False,
        relevance=None,
        method="semantic",
        method_note=None,
        reason="Текста нет: пост из картинок или видео, сравнить нечего",
        stage="no-text",
        zone="no",
        sentences=(),
        evidence=None,
        excerpt=None,
    )


def _stem_overlap(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _differs(cmp: EventComparison) -> str:
    names = {"место": "другое место", "дата": "другая дата", "числа": "другие числа"}
    return ", ".join(names.get(d, d) for d in cmp.differs) or "признаки не совпадают"


def _shared(cmp: EventComparison | None) -> str:
    if cmp is None or not cmp.shared:
        return ""
    return "; совпадают: " + ", ".join(cmp.shared[:4])


def _best_copy_sentence(w: _Work, ov: Overlap) -> int:
    counts = [0] * len(w.sentences)
    si = 0
    for tok, cov in zip(w.sh.tokens, ov.post_covered, strict=True):
        while si < len(w.sentences) - 1 and tok.start >= w.sentences[si].end:
            si += 1
        if cov:
            counts[si] += 1
    return max(range(len(counts)), key=lambda i: (counts[i], -i)) if counts else 0


def _best_lexical_sentence(w: _Work, ref_stems: set[str], shared_words: list[str]) -> int:
    best, best_score = 0, -1.0
    shared_low = [s.lower() for s in shared_words]
    for s in w.sentences:
        chunk = w.text[s.start : s.end]
        stems = content_stems(tokenize(chunk))
        score = float(len(stems & ref_stems)) + 2.0 * sum(1 for x in shared_low if x and x in chunk.lower())
        if score > best_score:
            best, best_score = s.index, score
    return best


def _has_shared(text: str, sent: Sentence, shared_words: list[str]) -> bool:
    chunk = text[sent.start : sent.end].lower()
    return any(x.lower() in chunk for x in shared_words if x)


def _sentence_evidence(w: _Work, idx: int, basis: EvidenceBasis, note: str) -> Evidence | None:
    if not w.sentences:
        return None
    idx = min(max(idx, 0), len(w.sentences) - 1)
    s = w.sentences[idx]
    return Evidence(idx, (TextRange(s.start, s.end),), basis, note)


def _excerpt(text: str, sentences: tuple[Sentence, ...], idx: int) -> Excerpt | None:
    """Выдержка вокруг предложения-доказательства — всегда подстрока оригинала."""
    if not sentences:
        return None
    idx = min(max(idx, 0), len(sentences) - 1)
    start, end = sentences[idx].start, sentences[idx].end
    j = idx
    while j + 1 < len(sentences) and sentences[j + 1].end - start <= EXCERPT_CHARS:
        j += 1
        end = sentences[j].end
    if end - start > EXCERPT_CHARS:
        cut = text.rfind(" ", start, start + EXCERPT_CHARS)
        end = cut if cut > start + EXCERPT_CHARS // 2 else start + EXCERPT_CHARS
    return Excerpt(
        start=start,
        end=end,
        text=text[start:end],
        cut_start=bool(text[:start].strip()),
        cut_end=bool(text[end:].strip()),
    )
