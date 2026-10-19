"""Воронка отбора: интерфейс `Matcher`, заглушка и загрузка настоящей воронки."""

from __future__ import annotations

import importlib
import inspect
import sys
from pathlib import Path
from typing import cast

from mediamonitor.matcher.base import (
    Candidate,
    Decision,
    EvidenceDraft,
    Matcher,
    MatchSession,
    QueryContext,
    StandNote,
    VectorStore,
)
from mediamonitor.settings import Settings

# Папка server/: в ней лежит воронка «Э-Отбор» (server/matching/).
SERVER_ROOT = Path(__file__).resolve().parents[3]


def load_matcher(spec: str, settings: Settings | None = None) -> Matcher:
    """MATCHER=«модуль:функция» → вызвать функцию, она возвращает объект с интерфейсом Matcher.

    Функция получает настройки сервера, если принимает аргумент. По умолчанию —
    воронка «Э-Отбор» (`mediamonitor.matcher.funnel:create_matcher`); модуль ищется и в
    server/, рядом с пакетом mediamonitor.
    """
    module_name, _, factory_name = spec.partition(":")
    if not module_name or not factory_name:
        raise ValueError(f"MATCHER: нужна запись «модуль:функция», получено «{spec}»")
    if str(SERVER_ROOT) not in sys.path:
        sys.path.append(str(SERVER_ROOT))
    module = importlib.import_module(module_name)
    factory = getattr(module, factory_name)
    takes_settings = bool(inspect.signature(factory).parameters)
    matcher = factory(settings or Settings()) if takes_settings else factory()
    for attribute in (
        "name",
        "start",
        "split_sentences",
        "release_fragments",
        "topic_card",
        "warmup",
        "stand_notes",
    ):
        if not hasattr(matcher, attribute):
            raise TypeError(f"MATCHER: у объекта из {spec} нет «{attribute}» (интерфейс Matcher)")
    return cast(Matcher, matcher)


__all__ = [
    "Candidate",
    "Decision",
    "EvidenceDraft",
    "MatchSession",
    "Matcher",
    "QueryContext",
    "StandNote",
    "VectorStore",
    "load_matcher",
]
