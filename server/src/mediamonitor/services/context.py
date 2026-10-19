"""Зависимости приложения в одном месте: настройки, база, площадки, нейросеть, отбор,
проверка текста на ИИ."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

import httpx

from mediamonitor.adapters import AdapterRegistry
from mediamonitor.ai.judge import AiJudge
from mediamonitor.aicheck import AiCheckService
from mediamonitor.db.session import SessionMaker
from mediamonitor.matcher import Matcher
from mediamonitor.services.events import EventBus
from mediamonitor.services.topic import TopicService
from mediamonitor.settings import Settings

if TYPE_CHECKING:
    from mediamonitor.services.runner import SearchRunner


@dataclass
class AppContext:
    settings: Settings
    sessions: SessionMaker
    adapters: AdapterRegistry
    judge: AiJudge
    matcher: Matcher
    http: httpx.AsyncClient
    bus: EventBus
    topics: TopicService
    ai_checks: AiCheckService
    started_at: datetime
    runner: SearchRunner = field(init=False)
