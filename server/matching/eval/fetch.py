"""Скачивает тексты мини-эталона по манифесту в `eval/data/raw/` (не коммитится).

Репозиторий публичный: чужие тексты храним только локально. В git лежат манифест
(ссылки и разметка) и контрольные суммы извлечённых текстов (`data/checksums.json`),
чтобы было видно, если текст на сайте изменился.

    uv run python eval/fetch.py            # скачать недостающее
    uv run python eval/fetch.py --force    # скачать всё заново
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import trafilatura

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "manifest.json"
RAW = HERE / "data" / "raw"
CHECKSUMS = HERE / "data" / "checksums.json"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0 Safari/537.36"
)


def iter_docs(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    for story in manifest["stories"]:
        docs.extend(story["docs"])
    for topic in manifest["topics"]:
        docs.extend(topic["docs"])
    return docs


def extract(content: bytes, url: str) -> tuple[str | None, str | None]:
    """Заголовок и текст статьи. trafilatura сама определяет кодировку."""
    doc = trafilatura.bare_extraction(
        content, url=url, favor_recall=True, include_comments=False, include_tables=True, with_metadata=True
    )
    if doc is None:
        return None, None
    data: dict[str, Any] = doc.as_dict() if hasattr(doc, "as_dict") else dict(doc)
    title = data.get("title")
    text = data.get("text")
    return (str(title).strip() if title else None), (str(text).strip() if text else None)


def fetch_one(client: httpx.Client, doc: dict[str, Any]) -> dict[str, Any]:
    last_error = ""
    for attempt in range(3):
        try:
            r = client.get(doc["url"])
            if r.status_code == 200:
                title, text = extract(r.content, str(r.url))
                if not text:
                    raise ValueError("текст не извлечён")
                return {
                    "id": doc["id"],
                    "url": doc["url"],
                    "final_url": str(r.url),
                    "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "title": title or doc.get("headline"),
                    "text": text,
                }
            last_error = f"HTTP {r.status_code}"
        except (httpx.HTTPError, ValueError) as e:
            last_error = f"{type(e).__name__}: {e}"
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(last_error)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="скачать всё заново")
    ap.add_argument("--update-checksums", action="store_true", help="записать суммы текущих текстов")
    args = ap.parse_args()

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    RAW.mkdir(parents=True, exist_ok=True)
    known: dict[str, dict[str, Any]] = (
        json.loads(CHECKSUMS.read_text(encoding="utf-8")) if CHECKSUMS.exists() else {}
    )
    failed: list[str] = []
    changed: list[str] = []
    with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True, timeout=30.0) as client:
        for doc in iter_docs(manifest):
            path = RAW / f"{doc['id']}.json"
            if path.exists() and not args.force:
                rec = json.loads(path.read_text(encoding="utf-8"))
            else:
                try:
                    rec = fetch_one(client, doc)
                except RuntimeError as e:
                    print(f"  ✗ {doc['id']}: {doc['url']} — {e}", file=sys.stderr)
                    failed.append(doc["id"])
                    continue
                path.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"  ✓ {doc['id']}: {len(rec['text'])} знаков")
                time.sleep(0.5)
            digest = sha(rec["text"])
            if args.update_checksums or doc["id"] not in known:
                known[doc["id"]] = {"sha256_16": digest, "chars": len(rec["text"])}
            elif known[doc["id"]]["sha256_16"] != digest:
                changed.append(doc["id"])
    CHECKSUMS.write_text(json.dumps(known, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    total = len(iter_docs(manifest))
    print(f"Готово: {total - len(failed)} из {total} документов в {RAW}")
    if changed:
        print(f"Текст изменился (результаты могут отличаться от README): {', '.join(changed)}")
    if failed:
        print(f"Не скачались: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
