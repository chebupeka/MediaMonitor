"""Проверка текста на ИИ: нормализация, провайдеры детектора, общий кэш результатов."""

from mediamonitor.aicheck.providers import (
    AiDetector,
    DetectorError,
    DetectorReply,
    FixtureDetector,
    GigaCheckDetector,
)
from mediamonitor.aicheck.service import AiCheckService, Identity, build_detector
from mediamonitor.aicheck.text import PreparedText, count_words, normalize_text, prepare, text_hash

__all__ = [
    "AiCheckService",
    "AiDetector",
    "DetectorError",
    "DetectorReply",
    "FixtureDetector",
    "GigaCheckDetector",
    "Identity",
    "PreparedText",
    "build_detector",
    "count_words",
    "normalize_text",
    "prepare",
    "text_hash",
]
