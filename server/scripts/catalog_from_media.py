"""Каталог обязательных площадок из каталога СМИ края: сообщества VK, группы OK, каналы MAX.

Берёт `src/mediamonitor/data/krai-media.json` (таблица команды «Источники нужные.xlsx» и
проверки 20.10.2026) и пишет `src/mediamonitor/data/catalog.json` — только корректные
ссылки: сообщества VK, группы OK и каналы MAX. Личные страницы VK и профили OK (это личные
данные), приглашения MAX без имени канала в каталог не попадают: их список печатается, он же
— в `docs/research/catalog-issues.md` («уточнить у Агентства»).

Запуск: uv run python scripts/catalog_from_media.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

DATA = Path(__file__).resolve().parents[1] / "src" / "mediamonitor" / "data"
GOOD_KINDS = {"vk": {"community"}, "ok": {"group"}, "max": {"channel", "channel-gos"}}
WHAT = {"vk": "Сообщество", "ok": "Группа", "max": "Канал"}
OF_KIND = {"газета": "газеты", "телеканал": "телеканала"}
COMMENT = (
    "Каталог краевых источников обязательных площадок (Р4, НТ-14): сообщества VK, группы OK "
    "и каналы MAX районных и краевых СМИ из таблицы команды «Источники нужные.xlsx» "
    "(собран scripts/catalog_from_media.py из data/krai-media.json, 20.10.2026). Личные "
    "страницы, профили и приглашения MAX не перенесены — docs/research/catalog-issues.md. "
    "Формат записи: {platform, ownerId, slug, name, type, district, subscribers, description}; "
    "ownerId у VK — числовой id со знаком «-», если он есть в ссылке, иначе короткий адрес "
    "(пока адаптер VK не узнаёт id сам). Подписчики — по таблице Агентства на март 2026. "
    "Сайты СМИ и каналы Дзена берутся из data/krai-media.json напрямую."
)


def entry(media: dict[str, Any], platform: str, link: dict[str, Any]) -> dict[str, Any]:
    handle = link.get("handle")
    owner = link.get("ownerId")
    if platform in ("vk", "ok"):
        # Числовой id в ссылке (club…, public…, group/…) — ключ; иначе короткий адрес.
        slug = None if owner else handle
        owner_id = owner or handle
    else:
        slug = handle
        owner_id = handle
    of = OF_KIND.get(str(media.get("kind")), "редакции")
    where = f" ({media['district']})" if media.get("district") else ""
    return {
        "platform": platform,
        "ownerId": str(owner_id),
        "slug": slug.lower() if slug else None,
        "name": media["name"],
        "type": "media",
        "district": media.get("district"),
        "subscribers": (media.get("subscribers") or {}).get(platform),
        "description": f"{WHAT[platform]} {of} «{media['name']}»{where}. "
        "Из таблицы источников Агентства; подписчики — на март 2026.",
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # консоль Windows
    data = json.loads((DATA / "krai-media.json").read_text("utf-8"))
    sources: list[dict[str, Any]] = []
    skipped: list[str] = []
    for media in data["media"]:
        for platform in ("vk", "ok", "max"):
            link = (media.get("links") or {}).get(platform)
            if not link:
                continue
            if link.get("kind") in GOOD_KINDS[platform] and (
                link.get("handle") or link.get("ownerId")
            ):
                sources.append(entry(media, platform, link))
            else:
                skipped.append(f"{media['name']}: {platform} {link.get('kind')} {link.get('url')}")
    out = {"$comment": COMMENT, "sources": sources}
    (DATA / "catalog.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    counts = {p: sum(1 for s in sources if s["platform"] == p) for p in ("vk", "ok", "max")}
    print(f"catalog.json: {len(sources)} источников {counts}")
    print("Не перенесены (уточнить у Агентства):")
    for line in skipped:
        print("  -", line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
