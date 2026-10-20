"""Зависимости приложения в одном месте: настройки, база, площадки, нейросеть, отбор,
проверка текста на ИИ, бюджет вызовов площадок."""

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
    from mediamonitor.services.budget import CallBudget
    from mediamonitor.services.runner import SearchRunner
    from mediamonitor.services.workspace import NewWorkspaceLimit


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
    # Суточный и месячный предел вызовов платных площадок (НТ-6).
    budget: CallBudget
    # Новых рабочих мест с одного IP за сутки (НТ-6).
    new_workspaces: NewWorkspaceLimit
    started_at: datetime
    runner: SearchRunner = field(init=False)
