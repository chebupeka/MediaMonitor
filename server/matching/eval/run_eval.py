"""Оценка воронки на мини-эталоне: полнота и точность по шагам, подбор порогов, скорость.

    uv run python eval/fetch.py               # один раз: скачать тексты по манифесту
    uv run python eval/run_eval.py            # оценка, отчёт в eval/results/latest.md
    uv run python eval/run_eval.py --tune     # плюс подбор порогов по сетке
    OLLAMA_URL=http://host:11434 uv run python eval/run_eval.py   # с шагом нейросети

Шаг нейросети оценивается, только если `OLLAMA_URL` задан и сервер отвечает.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from mm_matching.config import (
    LlmSettings,
    MatcherConfig,
    NewsThresholds,
    PlacementThresholds,
    TopicThresholds,
)
from mm_matching.embeddings import SentenceTransformerEmbedder
from mm_matching.events import EventExtractor
from mm_matching.funnel import NOTE_AI_UNSUPPORTED, NOTE_AI_UNSURE, FunnelMatcher
from mm_matching.llm import LlmClient, client_from_env
from mm_matching.placement import placement_type
from mm_matching.shingles import overlap, shingle
from mm_matching.topic import expand_query, fallback_card
from mm_matching.types import Candidate, MatchResult, TopicCard

HERE = Path(__file__).resolve().parent
RAW = HERE / "data" / "raw"
RESULTS = HERE / "results"
POSITIVE = ("verbatim", "shortened", "retold")
TOPIC_QUERIES = {"bdd": "безопасность дорожного движения", "fire": "пожарная безопасность"}
FloatArray = npt.NDArray[np.float64]


# ------------------------------------------------------------------------- данные


@dataclass(frozen=True)
class Doc:
    id: str
    url: str
    site: str
    label: str
    story: str | None
    theme: str | None  # тема сюжета или подборки: bdd / fire / None
    text: str


def load_corpus(manifest_path: Path) -> tuple[list[dict[str, Any]], list[Doc], list[str]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    docs: list[Doc] = []
    missing: list[str] = []

    def add(d: dict[str, Any], story: str | None, theme: str | None) -> None:
        path = RAW / f"{d['id']}.json"
        if not path.exists():
            missing.append(d["id"])
            return
        rec = json.loads(path.read_text(encoding="utf-8"))
        title = (rec.get("title") or "").strip()
        body = rec["text"].strip()
        text = body if not title or body.startswith(title[:40]) else f"{title}\n{body}"
        docs.append(Doc(d["id"], d["url"], d.get("site", ""), d["label"], story, theme, text))

    for s in manifest["stories"]:
        for d in s["docs"]:
            add(d, s["id"], s.get("theme"))
    for t in manifest["topics"]:
        for d in t["docs"]:
            add(d, None, t["id"])
    return manifest["stories"], docs, missing


# ------------------------------------------------------------------------- метрики


@dataclass
class PR:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 1.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0

    def add(self, other: PR) -> PR:
        return PR(self.tp + other.tp, self.fp + other.fp, self.fn + other.fn)


def pr_of(pred: npt.NDArray[np.bool_], gold: npt.NDArray[np.bool_]) -> PR:
    return PR(int((pred & gold).sum()), int((pred & ~gold).sum()), int((~pred & gold).sum()))


def fmt(x: float) -> str:
    return f"{x:.2f}"


# ------------------------------------------------------------------------- поиск по тексту новости


@dataclass
class NewsPairs:
    """Признаки для всех пар (исходная новость, кандидат) — массивами."""

    story: list[str]
    cand: list[str]
    label: list[str]
    gold: npt.NDArray[np.bool_]
    hard: npt.NDArray[np.bool_]  # похожая новость о другом событии
    share: FloatArray
    post_share: FloatArray
    matched: FloatArray
    hash_eq: npt.NDArray[np.bool_]
    cos: FloatArray
    support: FloatArray
    conflict: FloatArray
    placement_ov: list[Any] = field(default_factory=list)

    def subset(self, mask: npt.NDArray[np.bool_]) -> NewsPairs:
        idx = np.flatnonzero(mask)
        pick: Callable[[list[Any]], list[Any]] = lambda xs: [xs[i] for i in idx]  # noqa: E731
        return NewsPairs(
            pick(self.story), pick(self.cand), pick(self.label), self.gold[idx], self.hard[idx],
            self.share[idx], self.post_share[idx], self.matched[idx], self.hash_eq[idx], self.cos[idx],
            self.support[idx], self.conflict[idx], pick(self.placement_ov) if self.placement_ov else [],
        )  # fmt: skip


def news_pairs(
    stories: list[dict[str, Any]],
    docs: list[Doc],
    vecs: dict[str, npt.NDArray[np.float32]],
    ev: EventExtractor,
) -> NewsPairs:
    from mm_matching.text import text_hash

    by_id = {d.id: d for d in docs}
    rows: dict[str, list[Any]] = {k: [] for k in ("story", "cand", "label", "gold", "hard", "share", "post",
                                                  "matched", "hash", "cos", "sup", "con", "ov")}  # fmt: skip
    for s in stories:
        orig = next((d for d in s["docs"] if d["label"] == "original"), None)
        if orig is None or orig["id"] not in by_id:
            continue
        release = by_id[orig["id"]]
        rsh = shingle(release.text)
        rhash = text_hash(release.text)
        for c in docs:
            if c.id == release.id:
                continue
            ov = overlap(rsh, shingle(c.text))
            cmp = ev.compare(release.text, c.text)
            same_story = c.story == s["id"]
            rows["story"].append(s["id"])
            rows["cand"].append(c.id)
            rows["label"].append(c.label if same_story else "other")
            rows["gold"].append(same_story and c.label in POSITIVE)
            rows["hard"].append(same_story and c.label == "other_event")
            rows["share"].append(ov.release_share)
            rows["post"].append(ov.post_share)
            rows["matched"].append(ov.matched_tokens)
            rows["hash"].append(text_hash(c.text) == rhash)
            rows["cos"].append(float(vecs[c.id] @ vecs[release.id]))
            rows["sup"].append(cmp.support)
            rows["con"].append(cmp.conflict)
            rows["ov"].append(ov)
    a = np.asarray
    return NewsPairs(
        rows["story"], rows["cand"], rows["label"], a(rows["gold"], bool), a(rows["hard"], bool),
        a(rows["share"], float), a(rows["post"], float), a(rows["matched"], float), a(rows["hash"], bool),
        a(rows["cos"], float), a(rows["sup"], float), a(rows["con"], float), rows["ov"],
    )  # fmt: skip


def news_copy(p: NewsPairs, t: NewsThresholds) -> npt.NDArray[np.bool_]:
    """Копии после проверки шаблонных фраз признаками события."""
    raw = (p.share >= t.copy_release_share) | (
        (p.post_share >= t.copy_post_share) & (p.matched >= t.copy_min_tokens)
    )
    return p.hash_eq | (raw & ~news_template_cut(p, t))


def news_template_cut(p: NewsPairs, t: NewsThresholds) -> npt.NDArray[np.bool_]:
    """Частичные «копии», отсечённые признаками события (шаблонные фразы ведомства)."""
    raw = (p.share >= t.copy_release_share) | (
        (p.post_share >= t.copy_post_share) & (p.matched >= t.copy_min_tokens)
    )
    cut: npt.NDArray[np.bool_] = (
        ~p.hash_eq & raw & (p.share < t.copy_sure_share)
        & (p.conflict >= t.copy_conflict_for_no) & (p.support == 0)
    )  # fmt: skip
    return cut


def news_zones(p: NewsPairs, t: NewsThresholds) -> tuple[npt.NDArray[np.bool_], npt.NDArray[np.bool_]]:
    """Повторяет правила `FunnelMatcher._news_rules`: (явно да, серая зона)."""
    copy = news_copy(p, t)
    alive = ~copy & ~news_template_cut(p, t) & (p.cos >= t.cos_no)
    other = alive & (p.conflict >= t.conflict_for_no) & (p.support == 0)
    ok = alive & ~other & (p.conflict == 0)
    yes_sem = ok & ((p.cos >= t.cos_yes) | ((p.cos >= t.cos_supported) & (p.support >= t.support_for_yes)))
    yes = copy | yes_sem
    gray = alive & ~other & ~yes_sem
    return yes, gray


def news_objective(p: NewsPairs, t: NewsThresholds) -> tuple[float, ...]:
    yes, gray = news_zones(p, t)
    sel = pr_of(yes | gray, p.gold)
    sure = pr_of(yes, p.gold)
    return (round(sel.recall, 4), min(sure.precision, 0.97), -float(gray.sum()), sure.recall, sel.precision)


def news_grid() -> Iterable[NewsThresholds]:
    for copy_share in (0.15, 0.2, 0.25, 0.3):
        for cos_no in np.arange(0.50, 0.86, 0.02):
            for cos_yes in np.arange(0.70, 0.98, 0.02):
                if cos_yes < cos_no:
                    continue
                for cos_sup in np.arange(0.60, 0.96, 0.02):
                    if not cos_no <= cos_sup <= cos_yes:
                        continue
                    for sup in (1, 2, 3):
                        for con in (1, 2):
                            yield NewsThresholds(
                                copy_release_share=copy_share, cos_no=round(float(cos_no), 2),
                                cos_yes=round(float(cos_yes), 2), cos_supported=round(float(cos_sup), 2),
                                support_for_yes=sup, conflict_for_no=con,
                            )  # fmt: skip


def tune_news(p: NewsPairs) -> NewsThresholds:
    best: tuple[tuple[float, ...], NewsThresholds] | None = None
    for t in news_grid():
        score = news_objective(p, t)
        if best is None or score > best[0]:
            best = (score, t)
    assert best is not None
    return best[1]


def best_threshold(scores: FloatArray, gold: npt.NDArray[np.bool_]) -> tuple[float, PR]:
    best = (0.0, PR(0, 0, int(gold.sum())))
    for thr in np.unique(np.round(scores, 3)):
        pr = pr_of(scores >= thr, gold)
        if pr.f1 > best[1].f1:
            best = (float(thr), pr)
    return best


# ------------------------------------------------------------------------- поиск по теме


@dataclass
class TopicPairs:
    query: list[str]
    cand: list[str]
    gold: npt.NDArray[np.bool_]
    trap: npt.NDArray[np.bool_]  # документ «чужой» темы безопасности (ловушка)
    cos_q: FloatArray  # близость только к запросу
    pos: FloatArray  # максимум по «входит» карточки
    neg: FloatArray  # максимум по «не то» карточки

    def subset(self, mask: npt.NDArray[np.bool_]) -> TopicPairs:
        idx = np.flatnonzero(mask)
        return TopicPairs(
            [self.query[i] for i in idx], [self.cand[i] for i in idx], self.gold[idx], self.trap[idx],
            self.cos_q[idx], self.pos[idx], self.neg[idx],
        )  # fmt: skip


def topic_pairs(
    docs: list[Doc], embedder: SentenceTransformerEmbedder
) -> tuple[TopicPairs, dict[str, TopicCard]]:
    dv = embedder.encode([d.text for d in docs], "topic")
    rows: dict[str, list[Any]] = {k: [] for k in ("q", "c", "gold", "trap", "cq", "pos", "neg")}
    cards: dict[str, TopicCard] = {}
    for qid, query in TOPIC_QUERIES.items():
        card = fallback_card(query)
        cards[qid] = card
        q_text = expand_query(query)
        inc = [q_text]  # как в воронке: системные грани «входит» в близость не идут
        exc = [f.label for f in card.excludes]
        qv = embedder.encode(inc + exc, "topic")
        sims = dv @ qv.T
        for i, d in enumerate(docs):
            rows["q"].append(qid)
            rows["c"].append(d.id)
            rows["gold"].append(d.theme == qid)
            rows["trap"].append(d.theme is not None and d.theme != qid)
            rows["cq"].append(float(sims[i, 0]))
            rows["pos"].append(float(sims[i, : len(inc)].max()))
            rows["neg"].append(float(sims[i, len(inc) :].max()) if exc else -1.0)
    a = np.asarray
    tp = TopicPairs(
        rows["q"], rows["c"], a(rows["gold"], bool), a(rows["trap"], bool), a(rows["cq"], float),
        a(rows["pos"], float), a(rows["neg"], float),
    )  # fmt: skip
    return tp, cards


def topic_zones(p: TopicPairs, t: TopicThresholds) -> tuple[npt.NDArray[np.bool_], npt.NDArray[np.bool_]]:
    """Повторяет правила `FunnelMatcher._topic_rules` (без признаков события)."""
    margin = p.pos - p.neg
    alive = (p.pos >= t.sim_no) & ~((p.neg > -1.0) & (margin <= t.margin_no))
    yes = alive & (p.pos >= t.sim_yes) & (margin >= t.margin_yes)
    gray = alive & ~yes
    return yes, gray


def topic_objective(p: TopicPairs, t: TopicThresholds) -> tuple[float, ...]:
    yes, gray = topic_zones(p, t)
    sel = pr_of(yes | gray, p.gold)
    sure = pr_of(yes, p.gold)
    return (round(sel.recall, 2), min(sure.precision, 0.95), sel.f1, -float(gray.sum()), sure.recall)


def tune_topic(p: TopicPairs) -> TopicThresholds:
    best: tuple[tuple[float, ...], TopicThresholds] | None = None
    for sim_no in np.arange(0.40, 0.86, 0.02):
        for sim_yes in np.arange(0.50, 0.92, 0.02):
            if sim_yes < sim_no:
                continue
            for margin_yes in np.arange(-0.10, 0.22, 0.02):
                for margin_no in np.arange(-0.20, 0.12, 0.02):
                    if margin_no > margin_yes:
                        continue
                    t = TopicThresholds(
                        sim_no=round(float(sim_no), 2), sim_yes=round(float(sim_yes), 2),
                        margin_yes=round(float(margin_yes), 2), margin_no=round(float(margin_no), 2),
                    )  # fmt: skip
                    score = topic_objective(p, t)
                    if best is None or score > best[0]:
                        best = (score, t)
    assert best is not None
    return best[1]


# ------------------------------------------------------------------------- отчёт


class Report:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.data: dict[str, Any] = {}

    def __call__(self, line: str = "") -> None:
        print(line)
        self.lines.append(line)

    def table(self, head: Sequence[str], rows: Iterable[Sequence[str]]) -> None:
        self("| " + " | ".join(head) + " |")
        self("|" + "|".join("---" for _ in head) + "|")
        for r in rows:
            self("| " + " | ".join(r) + " |")
        self()


def pr_cells(pr: PR) -> list[str]:
    return [fmt(pr.precision), fmt(pr.recall), fmt(pr.f1), f"{pr.tp}/{pr.tp + pr.fn}", str(pr.fp)]


def changed_fields(new: Any, old: Any) -> str:
    diffs = [f"{f.name}: {getattr(old, f.name)} → {getattr(new, f.name)}" for f in fields(new)
             if getattr(new, f.name) != getattr(old, f.name)]  # fmt: skip
    return "; ".join(diffs) or "без изменений"


# ------------------------------------------------------------------------- прогоны


def run_news(out: Report, p: NewsPairs, t: NewsThresholds) -> None:
    hard_total = int(p.hard.sum())

    def hard_cut(pred: npt.NDArray[np.bool_]) -> str:
        return f"{int((~pred & p.hard).sum())}/{hard_total}"

    copy = news_copy(p, t)
    sem = p.cos >= t.cos_yes
    best_cos, best_cos_pr = best_threshold(p.cos, p.gold)
    yes, gray = news_zones(p, t)
    template_cut = news_template_cut(p, t)
    alive = ~copy & ~template_cut & (p.cos >= t.cos_no)
    events_cut = (alive & (p.conflict >= t.conflict_for_no) & (p.support == 0)) | template_cut
    rows = [
        ["1. Совпадение фраз (хеш, шинглы)", *pr_cells(pr_of(copy, p.gold)), hard_cut(copy)],
        [f"2. Смысл (BERTA), косинус ≥ {t.cos_yes}", *pr_cells(pr_of(sem, p.gold)), hard_cut(sem)],
        [f"2'. Смысл, лучший порог {best_cos:.2f}", *pr_cells(best_cos_pr), hard_cut(p.cos >= best_cos)],
        ["1+2. Фразы или смысл", *pr_cells(pr_of(copy | sem, p.gold)), hard_cut(copy | sem)],
        ["3. Признаки события: отсечено «другое событие»", "", "", "", "",
         f"{int((events_cut & ~p.gold).sum())} верно, {int((events_cut & p.gold).sum())} ошибочно",
         f"{int((events_cut & p.hard).sum())}/{hard_total}"],
        ["Итог правил: «явно да»", *pr_cells(pr_of(yes, p.gold)), hard_cut(yes)],
        ["Итог правил: в подборке (да + «Спорно»)", *pr_cells(pr_of(yes | gray, p.gold)),
         hard_cut(yes | gray)],
    ]  # fmt: skip
    gray_n = int(gray.sum())
    out.data["news"] = {
        "pairs": len(p.gold), "positives": int(p.gold.sum()), "hard_negatives": hard_total, "gray": gray_n,
        "gray_positive": int((gray & p.gold).sum()),
        "rows": {r[0]: r[1:] for r in rows},
    }  # fmt: skip

    out("### Поиск по тексту новости (сценарий 2)")
    out()
    out(f"Пар «исходная новость — кандидат»: {len(p.gold)}; из них перепечаток и пересказов: "
        f"{int(p.gold.sum())}; похожих новостей о другом событии: {hard_total}; остальные — новости "
        f"других сюжетов и тем. «Спорно» после правил: {gray_n} (из них настоящих перепечаток "
        f"{int((gray & p.gold).sum())}).")  # fmt: skip
    out()
    out.table(["Шаг", "Точность", "Полнота", "F1", "Найдено", "Лишних", "«Другое событие» отсеяно"], rows)


def run_news_cv(out: Report, p: NewsPairs, stories: list[str]) -> None:
    total_sel, total_sure, gray = PR(), PR(), 0
    for s in stories:
        train = p.subset(np.asarray([x != s for x in p.story], dtype=bool))
        test = p.subset(np.asarray([x == s for x in p.story], dtype=bool))
        t = tune_news(train)
        yes, g = news_zones(test, t)
        total_sel = total_sel.add(pr_of(yes | g, test.gold))
        total_sure = total_sure.add(pr_of(yes, test.gold))
        gray += int(g.sum())
    out("Перекрёстная проверка: пороги подобраны на остальных сюжетах и применены к отложенному "
        "(честная оценка для маленького эталона).")  # fmt: skip
    out()
    out.table(
        ["Итог правил", "Точность", "Полнота", "F1", "Найдено", "Лишних"],
        [["«явно да»", *pr_cells(total_sure)], ["в подборке (да + «Спорно»)", *pr_cells(total_sel)]],
    )
    out(f"«Спорно» на отложенных сюжетах: {gray}.")
    out()
    out.data["news_cv"] = {"sure": asdict(total_sure), "selection": asdict(total_sel), "gray": gray}


def run_placement(out: Report, p: NewsPairs, docs: list[Doc], pt: PlacementThresholds) -> None:
    by_id = {d.id: d for d in docs}
    conf: Counter[tuple[str, str]] = Counter()
    rows = []
    for i in np.flatnonzero(p.gold):
        ov = p.placement_ov[i]
        pred = placement_type(ov, is_repost=False, thresholds=pt)
        gold = p.label[i]
        conf[(gold, pred)] += 1
        d = by_id[p.cand[i]]
        rows.append([p.story[i], d.site, gold, pred, f"{round(ov.release_share * 100)}%",
                     f"{round(ov.post_share * 100)}%"])  # fmt: skip
    total = sum(conf.values())
    right = sum(v for (g, pr), v in conf.items() if g == pr)
    out("### Тип размещения (П2) и полнота цитирования (П1)")
    out()
    out(f"Тип размещения совпал с разметкой: {right} из {total} ({right / max(total, 1):.0%}). "
        "Разметка «дословно / сокращено» сама опирается на долю дословного текста, поэтому это "
        "проверка согласованности порогов, а не независимая оценка.")  # fmt: skip
    out()
    labels = list(POSITIVE)
    out.table(["Разметка \\ Воронка", *labels],
              [[g, *[str(conf[(g, x)]) for x in labels]] for g in labels])  # fmt: skip
    out.table(["Сюжет", "Сайт", "Разметка", "Воронка", "Перепечатано из релиза", "Доля поста из релиза"],
              sorted(rows))  # fmt: skip
    out.data["placement"] = {"right": right, "total": total}


def run_topic(out: Report, p: TopicPairs, t: TopicThresholds, cards: dict[str, TopicCard]) -> None:
    out("### Поиск по теме: «БДД» против «пожарной безопасности» (сценарий 1)")
    out()
    for card in cards.values():
        excl = ", ".join(f.label for f in card.excludes)
        out(f"Карточка темы «{card.query}» (правила, без нейросети): входит — "
            f"{len(card.includes)} граней, «не то» — {excl}.")  # fmt: skip
    out()
    rows = []
    for qid in TOPIC_QUERIES:
        sub = p.subset(np.asarray([q == qid for q in p.query], dtype=bool))
        trap_total = int(sub.trap.sum())

        def traps(pred: npt.NDArray[np.bool_], sub: TopicPairs = sub, n: int = trap_total) -> str:
            return f"{int((pred & sub.trap).sum())}/{n}"

        only_q = sub.cos_q >= t.sim_yes
        bt, bpr = best_threshold(sub.cos_q, sub.gold)
        yes, gray = topic_zones(sub, t)
        name = "БДД" if qid == "bdd" else "пожарная"
        rows += [
            [name, f"Смысл, только запрос, ≥ {t.sim_yes}", *pr_cells(pr_of(only_q, sub.gold)), traps(only_q)],
            [name, f"Смысл, только запрос, лучший порог {bt:.2f}", *pr_cells(bpr), traps(sub.cos_q >= bt)],
            [name, "Смысл + карточка темы: «явно да»", *pr_cells(pr_of(yes, sub.gold)), traps(yes)],
            [name, "В подборке (да + «Спорно»)", *pr_cells(pr_of(yes | gray, sub.gold)), traps(yes | gray)],
        ]  # fmt: skip
    out.table(
        ["Тема", "Шаг", "Точность", "Полнота", "F1", "Найдено", "Лишних", "Чужая тема в подборке"], rows
    )
    out.data["topic"] = {"rows": rows}
    # Перекрёстная проверка: пороги подобраны на другой теме и применены к этой.
    sure_cv, sel_cv, gray_cv = PR(), PR(), 0
    for qid in TOPIC_QUERIES:
        train = p.subset(np.asarray([q != qid for q in p.query], dtype=bool))
        test = p.subset(np.asarray([q == qid for q in p.query], dtype=bool))
        yes, gray = topic_zones(test, tune_topic(train))
        sure_cv = sure_cv.add(pr_of(yes, test.gold))
        sel_cv = sel_cv.add(pr_of(yes | gray, test.gold))
        gray_cv += int(gray.sum())
    out("Перекрёстная проверка: пороги подобраны на одной теме и применены к другой.")
    out()
    out.table(
        ["Итог правил", "Точность", "Полнота", "F1", "Найдено", "Лишних"],
        [["«явно да»", *pr_cells(sure_cv)], ["в подборке (да + «Спорно»)", *pr_cells(sel_cv)]],
    )
    out(f"«Спорно» при перекрёстной проверке: {gray_cv}.")
    out()


def run_speed(out: Report, docs: list[Doc], embedder: SentenceTransformerEmbedder, m: FunnelMatcher) -> None:
    rng = random.Random(7)
    texts = [d.text for d in docs]
    release = next(d.text for d in docs if d.label == "original")
    out("### Скорость на этом компьютере")
    out()
    out(f"Процессор: {platform.processor() or platform.machine()}; потоков torch: "
        f"{_torch_threads()}; Python {platform.python_version()}. Нейросеть не входит в замер.")  # fmt: skip
    out()
    rows = []
    for n in (50, 500):
        pool = []
        for i in range(n):
            base = texts[rng.randrange(len(texts))]
            sents = base.split(". ")
            rng.shuffle(sents)
            pool.append(Candidate(f"c{i}", ". ".join(sents) + f" Выпуск {i}."))
        embedder.clear_cache()
        t0 = time.perf_counter()
        rep = m.match_news(release, pool)
        cold = time.perf_counter() - t0
        t0 = time.perf_counter()
        m.match_news(release, pool)
        warm = time.perf_counter() - t0
        embedder.clear_cache()
        t0 = time.perf_counter()
        m.match_topic(TOPIC_QUERIES["bdd"], pool)
        topic_cold = time.perf_counter() - t0
        gray = sum(1 for r in rep.results if r.zone == "gray")
        rows.append([str(n), f"{cold:.1f} с", f"{warm:.2f} с", f"{topic_cold:.1f} с", str(gray)])
    out.table(
        ["Кандидатов", "По тексту новости, без индекса", "С индексом (векторы при сборе)",
         "По теме, без индекса", "Спорных для нейросети"],
        rows,
    )  # fmt: skip
    rss = _rss_mb()
    if rss is not None:
        out(f"Пиковая память процесса оценки: {rss:.0f} МБ (модель эмбеддингов, Natasha, данные).")
        out()
    out.data["speed"] = rows


def _rss_mb() -> float | None:
    """Пиковая память процесса, МБ (Windows и Linux), без лишних зависимостей."""
    import ctypes

    windll: Any = getattr(ctypes, "windll", None)
    if windll is not None:
        from ctypes import wintypes

        size = ctypes.c_size_t
        names = (
            "PeakWorkingSetSize WorkingSetSize QuotaPeakPagedPoolUsage QuotaPagedPoolUsage "
            "QuotaPeakNonPagedPoolUsage QuotaNonPagedPoolUsage PagefileUsage PeakPagefileUsage"
        ).split()
        fields_: list[tuple[str, Any]] = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)]
        counters_type: Any = type(
            "Counters", (ctypes.Structure,), {"_fields_": fields_ + [(n, size) for n in names]}
        )
        c = counters_type()
        c.cb = ctypes.sizeof(c)
        handle = wintypes.HANDLE(-1)  # псевдо-дескриптор текущего процесса (64-битный)
        if windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(c), c.cb):
            return float(c.PeakWorkingSetSize) / 2**20
        return None
    try:
        resource: Any = __import__("resource")
    except ImportError:
        return None
    return float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) / 1024


def _torch_threads() -> int:
    import torch

    return int(torch.get_num_threads())


# ------------------------------------------------------------------------- нейросеть


@dataclass(frozen=True)
class LlmCall:
    kind: str  # card / verdict
    seconds: float
    raw: str
    error: str | None


class TimedLlm:
    """Обёртка клиента нейросети для отчёта: время и сырой ответ каждого запроса."""

    def __init__(self, inner: LlmClient) -> None:
        self.inner = inner
        self.calls: list[LlmCall] = []
        self._lock = threading.Lock()

    @property
    def description(self) -> str:
        return self.inner.description

    @property
    def model_version(self) -> str:
        return str(getattr(self.inner, "model_version", self.inner.description))

    def available(self) -> bool:
        return self.inner.available()

    def mark_unavailable(self) -> None:
        mark = getattr(self.inner, "mark_unavailable", None)
        if mark is not None:
            mark()

    def chat_json(self, system: str, user: str, schema: dict[str, Any]) -> str:
        kind = "card" if "summary" in schema.get("properties", {}) else "verdict"
        t0 = time.perf_counter()
        raw, error = "", None
        try:
            raw = self.inner.chat_json(system, user, schema)
        except Exception as e:
            error = type(e).__name__
            raise
        finally:
            with self._lock:
                self.calls.append(LlmCall(kind, time.perf_counter() - t0, raw, error))
        return raw


def _llm_settings_note(s: LlmSettings) -> str:
    extra = [f"{name} {getattr(s, name)}" for name in ("concurrency", "keep_alive") if hasattr(s, name)]
    return ", ".join([f"LLM_MAX_GRAY {s.max_gray}", f"LLM_DEADLINE {s.deadline_s:g} с", *extra])


def _outcome(r: MatchResult) -> str:
    """Что нейросеть сделала со спорным постом (по полям результата)."""
    if r.stage != "llm":
        return "не проверено: " + (r.method_note or "—")
    if not r.included:
        return "нет"
    if r.method == "ai-confirmed":
        return "да"
    if r.method_note == NOTE_AI_UNSUPPORTED:
        return "да, не подтверждено текстом"
    if r.method_note == NOTE_AI_UNSURE:
        return "не может решить"
    return r.method_note or "?"


def _gray_row(search: str, r: MatchResult, gold: bool) -> list[str]:
    outcome = _outcome(r)
    said_yes = outcome.startswith("да")
    if outcome in ("да", "нет", "да, не подтверждено текстом"):
        right = "верно" if said_yes == gold else "**ошибка**"
    else:
        right = "—"
    sent = str(r.evidence.sentence_index) if r.evidence is not None and r.stage == "llm" else "—"
    ev_cos = getattr(r.scores, "evidence_cosine", None)
    return [search, r.candidate_id, "да" if gold else "нет", outcome, right, sent,
            "—" if ev_cos is None else f"{ev_cos:.3f}"]  # fmt: skip


def _print_evidence(search: str, r: MatchResult, text: str) -> None:
    """Предложение-доказательство — только в консоль: тексты публикаций в отчёт не идут."""
    if r.stage != "llm" or r.evidence is None or not r.sentences:
        return
    s = r.sentences[r.evidence.sentence_index]
    print(f"  [{search}] {r.candidate_id}: {_outcome(r)} — «{text[s.start : s.end][:140]}»")


def _card_sig(card: TopicCard) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    return card.summary, tuple(f.label for f in card.includes), tuple(f.label for f in card.excludes)


def _pct(xs: list[float], q: float) -> float:
    return float(np.percentile(np.asarray(xs), q)) if xs else 0.0


def _same(n: int) -> str:
    return "одинаковые" if n == 1 else f"{n} разные"


def run_llm(
    out: Report, stories: list[dict[str, Any]], docs: list[Doc], p: NewsPairs, llm: TimedLlm, m: FunnelMatcher
) -> None:  # fmt: skip
    """Шаг нейросети на эталоне: качество, что стало со спорными, карточка темы, время."""
    from mm_matching import topic as topic_module

    out("### Шаг нейросети")
    out()
    out(f"Модель: `{llm.model_version}`. «Уверенно» — в подборке без пометки «Спорно»: «явно да» "
        "по правилам плюс подтверждённое ИИ. «В подборке» — всё, что увидит сотрудник.")  # fmt: skip
    out()
    llm.calls.clear()
    by_id = {d.id: d for d in docs}
    rows: list[list[str]] = []
    gray_rows: list[list[str]] = []
    llm_seconds: list[float] = []
    started = time.perf_counter()

    # По тексту новости.
    index = {(st, c): i for i, (st, c) in enumerate(zip(p.story, p.cand, strict=True))}
    sure = np.zeros_like(p.gold)
    sel = np.zeros_like(p.gold)
    for s in stories:
        orig = next((d for d in docs if d.story == s["id"] and d.label == "original"), None)
        if orig is None:
            continue
        rep = m.match_news(orig.text, [Candidate(d.id, d.text) for d in docs if d.id != orig.id])
        llm_seconds.append(rep.timings.get("llm", 0.0))
        for r in rep.results:
            i = index[(s["id"], r.candidate_id)]
            sel[i] = r.included
            sure[i] = r.included and r.relevance != "disputed"
            if r.zone == "gray":
                gray_rows.append(_gray_row(f"новость {s['id']}", r, bool(p.gold[i])))
                _print_evidence(s["id"], r, by_id[r.candidate_id].text)
    hard_total = int(p.hard.sum())
    for name, pred in (("уверенно", sure), ("в подборке", sel)):
        rows.append(["По тексту новости", name, *pr_cells(pr_of(pred, p.gold)),
                     f"{int((pred & p.hard).sum())}/{hard_total}"])  # fmt: skip

    # По теме: карточка по правилам и карточка от нейросети.
    cands = [Candidate(d.id, d.text) for d in docs]
    ai_cards: dict[str, TopicCard] = {}
    for qid, query in TOPIC_QUERIES.items():
        gold = np.asarray([d.theme == qid for d in docs], dtype=bool)
        trap = np.asarray([d.theme is not None and d.theme != qid for d in docs], dtype=bool)
        name = "БДД" if qid == "bdd" else "Пожарная"
        ai_card = m.topic_card(query)
        ai_cards[qid] = ai_card
        ai_name = "нейросеть" if ai_card.made_by == "ai" else "правила (ответ нейросети не принят)"
        for card_name, card in (("правила", fallback_card(query)), (ai_name, ai_card)):
            rep = m.match_topic(card, cands)
            llm_seconds.append(rep.timings.get("llm", 0.0))
            res = {r.candidate_id: r for r in rep.results}
            t_sel = np.asarray([res[d.id].included for d in docs], dtype=bool)
            t_sure = np.asarray(
                [res[d.id].included and res[d.id].relevance != "disputed" for d in docs], dtype=bool
            )
            search = f"{name}, карточка: {card_name}"
            for pname, pred in (("уверенно", t_sure), ("в подборке", t_sel)):
                rows.append([f"Тема {name}, карточка: {card_name}", pname, *pr_cells(pr_of(pred, gold)),
                             f"{int((pred & trap).sum())}/{int(trap.sum())}"])  # fmt: skip
            for k, d in enumerate(docs):
                r = res[d.id]
                if r.zone == "gray":
                    gray_rows.append(_gray_row(search, r, bool(gold[k])))
                    _print_evidence(search, r, d.text)
    wall = time.perf_counter() - started

    out.table(["Поиск", "Что считаем", "Точность", "Полнота", "F1", "Найдено", "Лишних",
               "Ловушки в подборке"], rows)  # fmt: skip
    out("Ловушки: для новости — похожие новости о другом событии, для темы — публикации другой темы.")
    out()

    # Что стало со спорными.
    summary: dict[str, Counter[str]] = {}
    for g in gray_rows:
        c = summary.setdefault(g[0], Counter())
        c["спорных"] += 1
        c[g[3] if not g[3].startswith("не проверено") else "не проверено"] += 1
        c["ошибок"] += g[4] == "**ошибка**"
    kinds = ["да", "да, не подтверждено текстом", "нет", "не может решить", "не проверено"]
    out("Спорные после правил и решение нейросети:")
    out()
    out.table(["Поиск", "Спорных", *kinds, "Ошибочная метка"],
              [[k, str(c["спорных"]), *[str(c[x]) for x in kinds], str(c["ошибок"])]
               for k, c in summary.items()])  # fmt: skip
    out.table(["Поиск", "Публикация", "По разметке", "Нейросеть", "Метка", "Предложение",
               "Близость предложения"], gray_rows)  # fmt: skip

    # Карточка темы.
    out("#### Карточка темы от нейросети")
    out()
    clear = getattr(topic_module, "clear_card_cache", None)
    cutting = getattr(topic_module, "cutting_excludes", None)
    stability: dict[str, Any] = {}
    for qid, query in TOPIC_QUERIES.items():
        fresh = []
        for _ in range(3):
            if clear is not None:
                clear()
            fresh.append(_card_sig(m.topic_card(query)))
        cached = [_card_sig(m.topic_card(query)) for _ in range(3)]
        raw_card = next((c.raw for c in reversed(llm.calls) if c.kind == "card" and c.raw), "")
        card = m.topic_card(query)
        n_fresh, n_cached = len(set(fresh)), len(set(cached))
        same = _card_sig(card) == _card_sig(ai_cards[qid])
        stability[qid] = {"fresh_distinct": n_fresh, "cached_distinct": n_cached, "same_as_eval": same}
        made = "нейросеть" if card.made_by == "ai" else "правила"
        out(f"«{query}» ({made}): 3 запуска подряд без кэша — {_same(n_fresh)}; через кэш — "
            f"{_same(n_cached)}; совпадает с карточкой, по которой шёл отбор выше: "
            f"{'да' if same else 'нет'}.")  # fmt: skip
        out()
        out(f"- входит: {'; '.join(f.label for f in card.includes)}")
        cut = cutting(card) if cutting is not None else list(card.excludes)
        cut_ids = {f.id for f in cut}
        out(f"- «не то», отсекает: {'; '.join(f.label for f in card.excludes if f.id in cut_ids) or '—'}")
        hint = "; ".join(f.label for f in card.excludes if f.id not in cut_ids)
        out(f"- «не то», только подсказка: {hint or '—'}")
        try:
            raw_exc = [str(x) for x in json.loads(raw_card).get("excludes", [])] if raw_card else []
        except (ValueError, AttributeError):
            raw_exc = []
        shown = {f.label.lower() for f in card.excludes}
        dropped = [x for x in raw_exc if " ".join(x.split()).lower() not in shown]
        out(f"- нейросеть предложила в «не то», но убрано как часть темы: {'; '.join(dropped) or '—'}")
        out()

    # Время.
    ok = [c for c in llm.calls if c.error is None]
    verdict_s = [c.seconds for c in ok if c.kind == "verdict"]
    card_s = [c.seconds for c in ok if c.kind == "card"]
    errors = Counter(c.error for c in llm.calls if c.error is not None)
    out("#### Время")
    out()
    out.table(["Запрос", "Сколько", "Среднее", "Медиана", "95%", "Макс."],
              [[name, str(len(xs)), f"{np.mean(xs):.2f} с" if xs else "—", f"{_pct(xs, 50):.2f} с",
                f"{_pct(xs, 95):.2f} с", f"{max(xs, default=0):.2f} с"]
               for name, xs in (("Решение по спорному посту", verdict_s),
                                ("Карточка темы", card_s))])  # fmt: skip
    err_note = " (" + ", ".join(f"{k} {v}" for k, v in errors.items()) + ")" if errors else ""
    out(f"Шаг нейросети во всех {len(llm_seconds)} поисках раздела — {sum(llm_seconds):.1f} с; "
        f"раздел целиком (с эмбеддингами из кэша) — {wall:.1f} с. Ошибок запросов: "
        f"{sum(errors.values())}{err_note}.")  # fmt: skip
    out()
    out.data["llm"] = {"rows": rows, "gray": gray_rows, "cards": stability, "verdict_seconds": verdict_s,
                       "card_seconds": card_s, "errors": dict(errors)}  # fmt: skip


def run_llm_speed(
    out: Report, docs: list[Doc], embedder: SentenceTransformerEmbedder, m: FunnelMatcher, llm: TimedLlm
) -> None:  # fmt: skip
    """Поиск по теме целиком с нейросетью: пулы как в замере скорости, векторы готовы заранее."""
    rng = random.Random(7)
    texts = [d.text for d in docs]
    rows = []
    for n in (50, 500):
        pool = []
        for i in range(n):
            base = texts[rng.randrange(len(texts))]
            sents = base.split(". ")
            rng.shuffle(sents)
            pool.append(Candidate(f"c{i}", ". ".join(sents) + f" Выпуск {i}."))
        t0 = time.perf_counter()
        embedder.encode([c.text or "" for c in pool], "topic")  # векторы «посчитаны при сборе»
        print(f"(векторы пула {n}: {time.perf_counter() - t0:.0f} с)")
        card = fallback_card(TOPIC_QUERIES["bdd"])
        llm.calls.clear()
        t0 = time.perf_counter()
        rep = m.match_topic(card, pool)
        total = time.perf_counter() - t0
        gray = sum(1 for r in rep.results if r.zone == "gray")
        rows.append([str(n), str(gray), str(rep.llm.checked), f"{rep.timings.get('llm', 0.0):.1f} с",
                     f"{total:.1f} с"])  # fmt: skip
    out("#### Поиск по теме «БДД» целиком с нейросетью (векторы посчитаны заранее)")
    out()
    out.table(["Кандидатов", "Спорных", "Проверено ИИ", "Время нейросети", "Всего"], rows)
    out.data["llm_speed"] = rows


# ------------------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=os.environ.get("EMBEDDING_MODEL", "sergeyzh/BERTA"))
    ap.add_argument("--chunk-chars", type=int, default=MatcherConfig().max_chunk_chars)
    ap.add_argument("--max-chunks", type=int, default=MatcherConfig().max_chunks)
    ap.add_argument("--manifest", type=Path, default=HERE / "manifest.json")
    ap.add_argument("--tune", action="store_true", help="подобрать пороги по сетке и показать разницу")
    ap.add_argument("--no-speed", action="store_true")
    ap.add_argument("--llm-speed", action="store_true", help="с нейросетью: поиск целиком на пулах 50 и 500")
    ap.add_argument("--out", type=Path, default=RESULTS / "latest.md")
    args = ap.parse_args()

    stories, docs, missing = load_corpus(args.manifest)
    if missing:
        print(f"Нет скачанных текстов: {', '.join(missing)}. Запустите eval/fetch.py.", file=sys.stderr)
    if not docs:
        return 1
    out = Report()
    defaults = MatcherConfig()
    llm_settings = LlmSettings.from_env()
    client = client_from_env(llm_settings)
    llm: TimedLlm | None = None
    llm_note = "не задан OLLAMA_URL — шаг пропущен"
    if client is not None:
        if client.available():
            llm = TimedLlm(client)
            llm_note = f"{client.description}; {_llm_settings_note(llm_settings)}"
        else:
            llm_note = f"{llm_settings.url} не отвечает или нет модели — шаг пропущен"

    out(f"## Мини-эталон: результаты ({datetime.now():%d.%m.%Y %H:%M})")
    out()
    labels = Counter(d.label for d in docs)
    out(f"Документов: {len(docs)} ({', '.join(f'{k} {v}' for k, v in sorted(labels.items()))}); "
        f"сюжетов: {len({d.story for d in docs if d.story})}. Модель эмбеддингов: `{args.model}` "
        f"(кусков до {args.max_chunks} по {args.chunk_chars} знаков). "
        f"Нейросеть: {llm_note}.")  # fmt: skip
    out()

    t0 = time.perf_counter()
    embedder = SentenceTransformerEmbedder(
        args.model, max_chunk_chars=args.chunk_chars, max_chunks=args.max_chunks
    )
    ev = EventExtractor()
    vec_list = embedder.encode([d.text for d in docs], "paraphrase")
    vecs = {d.id: vec_list[i] for i, d in enumerate(docs)}
    pairs = news_pairs(stories, docs, vecs, ev)
    tpairs, cards = topic_pairs(docs, embedder)
    print(f"(признаки посчитаны за {time.perf_counter() - t0:.1f} с)")

    news_t = defaults.news
    topic_t = defaults.topic
    if args.tune:
        tuned = tune_news(pairs)
        out(f"Подбор порогов, поиск по тексту новости: {changed_fields(tuned, news_t)}.")
        news_t = tuned
        tuned_t = tune_topic(tpairs)
        out(f"Подбор порогов, поиск по теме: {changed_fields(tuned_t, topic_t)}.")
        topic_t = tuned_t
        out()
    out.data["thresholds"] = {"news": asdict(news_t), "topic": asdict(topic_t)}

    def factory(cfg: MatcherConfig, client: LlmClient | None) -> FunnelMatcher:
        return FunnelMatcher(cfg, embedder=embedder, llm=client, events=ev, llm_settings=llm_settings)

    run_news(out, pairs, news_t)
    run_news_cv(out, pairs, sorted(set(pairs.story)))
    run_placement(out, pairs, docs, defaults.placement)
    run_topic(out, tpairs, topic_t, cards)
    _check_rules_match_funnel(out, stories, docs, pairs, news_t, factory)
    if llm is not None:
        cfg = replace(defaults, news=news_t, topic=topic_t)
        run_llm(out, stories, docs, pairs, llm, factory(cfg, llm))
        if args.llm_speed:
            run_llm_speed(out, docs, embedder, factory(cfg, llm), llm)
    if not args.no_speed:
        run_speed(out, docs, embedder, factory(replace(defaults, news=news_t, topic=topic_t), None))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(out.lines) + "\n", encoding="utf-8")
    args.out.with_suffix(".json").write_text(
        json.dumps(out.data, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    print(f"\nОтчёт: {args.out}")
    return 0


def _check_rules_match_funnel(
    out: Report, stories: list[dict[str, Any]], docs: list[Doc], p: NewsPairs, t: NewsThresholds,
    factory: Callable[[MatcherConfig, LlmClient | None], FunnelMatcher],
) -> None:  # fmt: skip
    """Сверка: быстрые правила оценки и настоящая воронка дают одни и те же зоны."""
    m = factory(MatcherConfig(news=t), None)
    yes, gray = news_zones(p, t)
    mismatch = 0
    for s in stories:
        orig = next((d for d in docs if d.story == s["id"] and d.label == "original"), None)
        if orig is None:
            continue
        rep = m.match_news(orig.text, [Candidate(d.id, d.text) for d in docs if d.id != orig.id])
        zones = {r.candidate_id: r.zone for r in rep.results}
        for i, (st, c) in enumerate(zip(p.story, p.cand, strict=True)):
            if st != s["id"]:
                continue
            expect = "yes" if yes[i] else ("gray" if gray[i] else "no")
            mismatch += zones[c] != expect
    out(f"Сверка оценки с настоящей воронкой: расхождений в зонах {mismatch}.")
    out()


if __name__ == "__main__":
    raise SystemExit(main())
