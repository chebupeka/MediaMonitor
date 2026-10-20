"""Сайт на «/» и веб-версия на «/app/» с того же адреса, что и API (api/static.py)."""

from __future__ import annotations

import base64
import gzip
import hashlib
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from mediamonitor.api.static import (
    CACHE_IMMUTABLE,
    StaticBundle,
    _accepted_encodings,
    media_type_of,
    page_csp,
)
from tests.conftest import make_app, make_settings, open_client

INLINE = "document.documentElement.classList.add('js');"
SITE_INDEX = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<title>Медиарадар</title><link rel="stylesheet" href="styles.css?v=1">
<script>{INLINE}</script></head><body><a href="/app/">Открыть веб-версию</a>
<script src="ui.js?v=1"></script></body></html>"""
APP_INDEX = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Панель</title>
<script type="module" crossorigin src="/app/assets/index-B1x2y3z4.js"></script></head>
<body><div id="root"></div></body></html>"""
APP_JS = "console.log('панель');\n" * 400
PRECOMPRESSED = b"brotli-bytes-from-the-build"


@pytest.fixture
def dirs(tmp_path: Path) -> tuple[Path, Path]:
    site = tmp_path / "site"
    (site / "fonts").mkdir(parents=True)
    (site / "index.html").write_text(SITE_INDEX, encoding="utf-8")
    (site / "styles.css").write_text("body{margin:0}\n" * 100, encoding="utf-8")
    (site / "ui.js").write_text("void 0;\n", encoding="utf-8")
    (site / "fonts" / "montserrat-400.woff2").write_bytes(b"wOF2" + bytes(300))
    (site / "README.md").write_text("# служебное", encoding="utf-8")
    (site / ".env").write_text("SECRET=1", encoding="utf-8")
    app = tmp_path / "app"
    (app / "assets").mkdir(parents=True)
    (app / "index.html").write_text(APP_INDEX, encoding="utf-8")
    (app / "assets" / "index-B1x2y3z4.js").write_bytes(APP_JS.encode())
    (app / "assets" / "index-B1x2y3z4.js.br").write_bytes(PRECOMPRESSED)
    (app / "favicon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", "utf-8")
    (tmp_path / "secret.txt").write_text("не для раздачи", encoding="utf-8")
    return site, app


@pytest.fixture
async def static_client(
    tmp_path: Path, dirs: tuple[Path, Path]
) -> AsyncIterator[httpx.AsyncClient]:
    site, app = dirs
    harness = make_app(make_settings(tmp_path, site_dir=str(site), web_app_dir=str(app)))
    async with open_client(harness.app) as client:
        yield client


async def test_site_page_with_strict_csp(static_client: httpx.AsyncClient) -> None:
    response = await static_client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert "Открыть веб-версию" in response.text
    csp = response.headers["content-security-policy"]
    digest = base64.b64encode(hashlib.sha256(INLINE.encode()).digest()).decode()
    assert f"script-src 'self' 'sha256-{digest}'" in csp
    assert "default-src 'self'" in csp
    assert "connect-src 'self'" in csp
    assert "font-src 'self' data:" in csp
    # Никаких внешних источников: ни CDN, ни Google Fonts, ни «любой https».
    assert "http" not in csp
    assert "*" not in csp
    assert "'unsafe-eval'" not in csp
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["etag"].startswith('"')
    assert (await static_client.get("/index.html")).text == response.text


async def test_site_files_mime_and_compression(static_client: httpx.AsyncClient) -> None:
    css = await static_client.get("/styles.css?v=1", headers={"Accept-Encoding": "gzip"})
    assert css.headers["content-type"] == "text/css; charset=utf-8"
    assert css.headers["content-encoding"] == "gzip"
    assert "Accept-Encoding" in css.headers["vary"]
    assert css.text.startswith("body{margin:0}")  # httpx распаковал gzip
    js = await static_client.get("/ui.js")
    assert js.headers["content-type"] == "text/javascript; charset=utf-8"
    assert "content-encoding" not in js.headers  # крошечный файл не сжимаем
    font = await static_client.get("/fonts/montserrat-400.woff2")
    assert font.status_code == 200
    assert font.headers["content-type"] == "font/woff2"
    assert "content-encoding" not in font.headers  # woff2 уже сжат


async def test_service_files_and_paths_outside_are_not_served(
    static_client: httpx.AsyncClient,
) -> None:
    for path in (
        "/README.md",
        "/.env",
        "/secret.txt",
        "/%2e%2e/secret.txt",
        "/app/%2e%2e/%2e%2e/secret.txt",
    ):
        response = await static_client.get(path)
        assert response.status_code == 404, path
        assert "не для раздачи" not in response.text
        assert "SECRET" not in response.text
    missing = await static_client.get("/no-such-page")
    assert missing.status_code == 404
    assert missing.headers["content-type"] == "text/html; charset=utf-8"
    assert "Страница не найдена" in missing.text


async def test_web_app_spa_fallback(static_client: httpx.AsyncClient) -> None:
    redirect = await static_client.get("/app")
    assert redirect.status_code == 308
    assert redirect.headers["location"] == "/app/"
    index = await static_client.get("/app/")
    assert index.status_code == 200
    assert '<div id="root">' in index.text
    assert index.headers["cache-control"] == "no-cache"
    assert "content-security-policy" in index.headers
    for route in ("/app/search", "/app/sources/vk/123", "/app/stand.html"):
        response = await static_client.get(route)
        assert response.status_code == 200, route
        assert response.text == index.text
    # Файл, которого нет, — 404, а не страница вместо скрипта.
    assert (await static_client.get("/app/assets/index-missing0.js")).status_code == 404
    favicon = await static_client.get("/app/favicon.svg")
    assert favicon.headers["content-type"] == "image/svg+xml"


async def test_hashed_assets_cached_forever_and_precompressed(
    static_client: httpx.AsyncClient,
) -> None:
    path = "/app/assets/index-B1x2y3z4.js"
    async with static_client.stream("GET", path, headers={"Accept-Encoding": "br, gzip"}) as br:
        raw = b"".join([chunk async for chunk in br.aiter_raw()])
        brotli = br
    assert brotli.headers["cache-control"] == CACHE_IMMUTABLE
    assert brotli.headers["content-encoding"] == "br"
    assert "Accept-Encoding" in brotli.headers["vary"]
    assert raw == PRECOMPRESSED  # готовый .br из сборки отдаётся как есть
    gz = await static_client.get(path, headers={"Accept-Encoding": "gzip"})
    assert gz.headers["content-encoding"] == "gzip"
    assert gz.text == APP_JS
    plain = await static_client.get(path, headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in plain.headers
    assert plain.text == APP_JS
    assert plain.headers["content-length"] == str(len(APP_JS.encode()))
    assert len({brotli.headers["etag"], gz.headers["etag"], plain.headers["etag"]}) == 3
    # «br;q=0» — brotli нельзя.
    refused = await static_client.get(path, headers={"Accept-Encoding": "br;q=0, gzip"})
    assert refused.headers["content-encoding"] == "gzip"


async def test_conditional_and_head_requests(static_client: httpx.AsyncClient) -> None:
    first = await static_client.get("/", headers={"Accept-Encoding": "identity"})
    etag = first.headers["etag"]
    again = await static_client.get(
        "/", headers={"Accept-Encoding": "identity", "If-None-Match": etag}
    )
    assert again.status_code == 304
    assert again.content == b""
    assert again.headers["etag"] == etag
    head = await static_client.head("/app/assets/index-B1x2y3z4.js")
    assert head.status_code == 200
    assert head.content == b""
    assert int(head.headers["content-length"]) > 0
    post = await static_client.post("/")
    assert post.status_code == 405
    assert post.headers["allow"] == "GET, HEAD"


async def test_api_and_health_unchanged(static_client: httpx.AsyncClient) -> None:
    health = await static_client.get("/health")
    assert health.json()["status"] == "ok"
    assert health.headers["content-security-policy"].startswith("default-src 'none'")
    unknown = await static_client.get("/api/no-such-method")
    assert unknown.status_code == 404
    assert unknown.headers["content-type"].startswith("application/json")
    assert unknown.json()["code"] == "not-found"
    assert unknown.headers["cache-control"] == "no-store"
    created = await static_client.post("/api/workspaces")
    assert created.status_code == 201
    stand = await static_client.get("/api/stand")
    assert stand.status_code == 200


async def test_without_static_dirs_only_api(tmp_path: Path) -> None:
    harness = make_app(make_settings(tmp_path))
    async with open_client(harness.app) as client:
        response = await client.get("/")
        assert response.status_code == 404
        assert response.json()["code"] == "not-found"


async def test_missing_build_is_not_fatal(tmp_path: Path, dirs: tuple[Path, Path]) -> None:
    site, _ = dirs
    empty = tmp_path / "no-build"
    empty.mkdir()
    settings = make_settings(tmp_path, site_dir=str(site), web_app_dir=str(empty))
    async with open_client(make_app(settings).app) as client:
        assert (await client.get("/")).status_code == 200
        assert (await client.get("/app/")).status_code == 404


def test_csp_hashes_each_inline_script() -> None:
    html = (
        b"<script>a()</script><script src='x.js'></script>"
        b"<SCRIPT type='module'>b()</SCRIPT><script>a()</script>"
    )
    csp = page_csp(html)
    script = next(part for part in csp.split("; ") if part.startswith("script-src"))
    assert script.count("'sha256-") == 2  # a() один раз, b(), внешний — без хеша


def test_csp_hash_matches_browser_for_windows_line_endings() -> None:
    # Браузер нормализует CRLF в LF до подсчёта хеша (так было на сайте с окончаниями Windows).
    body = "\n  document.documentElement.classList.add('js');\n"
    expected = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
    crlf = ("<script>" + body.replace("\n", "\r\n") + "</script>").encode()
    assert f"'sha256-{expected}'" in page_csp(crlf)


def test_accept_encoding_and_media_types() -> None:
    assert _accepted_encodings("gzip, deflate, br, zstd") >= {"gzip", "br"}
    assert _accepted_encodings("br;q=0, gzip;q=0.5") == {"gzip"}
    assert _accepted_encodings("*") >= {"br", "gzip"}
    assert _accepted_encodings("") == set()
    assert media_type_of("a/b.mjs") == "text/javascript; charset=utf-8"
    assert media_type_of("x.webmanifest") == "application/manifest+json"
    assert media_type_of("x.unknownext") == "application/octet-stream"


def test_gzip_variant_is_deterministic(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<p>" + "текст " * 200 + "</p>", encoding="utf-8")
    first = StaticBundle.load(tmp_path).files["index.html"].variants["gzip"]
    second = StaticBundle.load(tmp_path).files["index.html"].variants["gzip"]
    assert first.body == second.body
    assert first.etag == second.etag
    assert gzip.decompress(first.body).decode().startswith("<p>текст")
