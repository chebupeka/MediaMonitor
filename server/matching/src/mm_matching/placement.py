"""Тип размещения (П2): дословно / сокращено / пересказ / репост.

Решает только по числам шага 1 и флагу площадки — без нейросети, поэтому объяснимо:
«перепечатано 92%» → дословно, «перепечатано 40%» → сокращено.
"""

from __future__ import annotations

from mm_matching.config import PlacementThresholds
from mm_matching.shingles import Overlap
from mm_matching.types import PlacementType


def placement_type(
    ov: Overlap, *, is_repost: bool, thresholds: PlacementThresholds | None = None
) -> PlacementType:
    """Тип размещения для публикации, которая уже признана связанной с релизом.

    - репост — так его отдала площадка (своего текста нет или он короткий);
    - дословно — дословно вошло не меньше `verbatim` текста релиза;
    - сокращено — дословно вошла часть релиза, или пост почти целиком из фраз релиза;
    - пересказ — то же событие, но своими словами.
    """
    t = thresholds or PlacementThresholds()
    if is_repost:
        return "repost"
    if ov.release_share >= t.verbatim:
        return "verbatim"
    if ov.release_share >= t.shortened:
        return "shortened"
    if ov.post_share >= t.shortened_post_share and ov.matched_tokens >= t.shortened_min_tokens:
        return "shortened"
    return "retold"


PLACEMENT_LABELS: dict[PlacementType, str] = {
    "verbatim": "дословно",
    "shortened": "сокращено",
    "retold": "пересказ",
    "repost": "репост",
}
