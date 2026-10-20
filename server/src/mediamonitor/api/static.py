"""Сайт-витрина и веб-версия панели с того же адреса и порта, что и API.

- `/` — сайт «Медиарадар» (папка `site/`, настройка `SITE_DIR`);
- `/download/mediaradar-chrome.zip`, `/download/mediaradar-firefox.zip` — архивы расширения
  для установки из файла. Они лежат в папке сайта (`download/`, кладёт Dockerfile) и уходят
  с `Content-Disposition: attachment` — браузер сохраняет файл, а не пытается его открыть;
- `/app/` — веб-версия панели (сборка `web`: `npm run build:web` → `dist-web/`, base `/app/`,
  настройка `WEB_APP_DIR`). Адреса без файла (`/app/search`) получают `index.html` (SPA);
  адрес с расширением (`/app/assets/нет.js`) — честный 404, а не страницу вместо скрипта;
- `/api/…`, `/health` — маршруты FastAPI; сюда попадает только неизвестный адрес API,
  он получает обычный ответ API «нет такого адреса».

Файлы читаются в память при старте: раздаётся только то, что лежало в папке (путь из
запроса не превращается в путь на диске — выйти за папку нельзя), ETag — по содержимому.
Сжатие: готовые `.br` и `.gz` рядом с файлом (их делает Dockerfile, scripts/precompress.mjs)
или gzip, посчитанный при старте. Кэш: файлы с хешем в имени (`assets/index-B1x2y3z4.js`)
браузер хранит год без проверок; остальное — `no-cache`: каждый раз сверяет ETag и при
совпадении получает 304 без тела.

Страницы получают Content-Security-Policy без внешних источников: скрипты, стили, шрифты,
картинки и запросы — только с этого адреса (НТ-9). Встроенные `<script>` страницы
разрешаются по SHA-256 их текста, поэтому правки сайта не требуют правки сервера.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import logging
import mimetypes
import re
import urllib.parse
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.types import Receive, Scope, Send

log = logging.getLogger(__name__)

# MIME по расширению: явно, чтобы не зависеть от /etc/mime.types образа.
MEDIA_TYPES: dict[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".map": "application/json",
    ".webmanifest": "application/manifest+json",
    ".txt": "text/plain; charset=utf-8",
    ".xml": "application/xml",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".wasm": "application/wasm",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".pdf": "application/pdf",
    ".zip": "application/zip",
    ".crx": "application/x-chrome-extension",
    ".xpi": "application/x-xpinstall",
}
# Что браузер должен скачать как файл, а не показать: архивы расширения (/download/…).
DOWNLOAD_SUFFIXES = frozenset({".zip", ".crx", ".xpi"})
# Что имеет смысл сжимать (картинки, woff2, архивы уже сжаты).
COMPRESSIBLE = re.compile(
    r"^(text/|application/(json|javascript|manifest\+json|xml|wasm)|image/svg\+xml|font/(ttf|otf))"
)
MIN_COMPRESS_BYTES = 256
# Имя с хешем сборки Vite: index-B1x2y3z4.js, chunk.3f9a1c2b.css.
HASHED_NAME = re.compile(r"[.-][A-Za-z0-9_-]{8,}\.[A-Za-z0-9]+$")
INLINE_SCRIPT = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.IGNORECASE | re.DOTALL)
SRC_ATTRIBUTE = re.compile(r"\bsrc\s*=", re.IGNORECASE)

CACHE_IMMUTABLE = "public, max-age=31536000, immutable"
CACHE_REVALIDATE = "no-cache"

CSP_BASE = (
    "default-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    "connect-src 'self'",
    "media-src 'self' blob:",
    "worker-src 'self' blob:",
    "manifest-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
)
PAGE_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=(), usb=()"),
    (b"cross-origin-opener-policy", b"same-origin"),
)
NOT_FOUND_PAGE = (
    '<!doctype html><html lang="ru"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1">'
    "<title>Страница не найдена — Медиарадар</title></head>"
    '<body style="font-family:system-ui,sans-serif;max-width:36rem;margin:4rem auto;'
    'padding:0 1rem;line-height:1.5"><h1>Страница не найдена</h1>'
    '<p>Такой страницы нет. <a href="/">На главную</a> · '
    '<a href="/app/">Веб-версия</a></p></body></html>'
)


def media_type_of(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in MEDIA_TYPES:
        return MEDIA_TYPES[suffix]
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "application/octet-stream"


def page_csp(html: bytes) -> str:
    """CSP страницы: только свой адрес; встроенные скрипты — по SHA-256 их текста.

    Браузер считает хеш по тексту после разбора HTML, а разбор превращает CRLF и CR в LF:
    файл с окончаниями строк Windows иначе получил бы чужой хеш и скрипт бы не выполнился.
    """
    hashes: list[str] = []
    text = html.decode("utf-8", errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    for attributes, body in INLINE_SCRIPT.findall(text):
        if SRC_ATTRIBUTE.search(attributes) or not body.strip():
            continue
        digest = base64.b64encode(hashlib.sha256(body.encode("utf-8")).digest()).decode()
        token = f"'sha256-{digest}'"
        if token not in hashes:
            hashes.append(token)
    script = " ".join(["script-src 'self'", *hashes])
    return "; ".join([*CSP_BASE[:1], script, *CSP_BASE[1:]])


@dataclass(frozen=True)
class Variant:
    body: bytes
    etag: str
    encoding: str | None  # br, gzip или None — без сжатия


@dataclass(frozen=True)
class StaticFile:
    path: str
    media_type: str
    cache_control: str
    variants: dict[str, Variant]  # "identity", "br", "gzip"
    csp: str | None = None  # только у страниц
    disposition: str | None = None  # только у файлов для скачивания (архивы расширения)

    def choose(self, accept_encoding: str) -> Variant:
        accepted = _accepted_encodings(accept_encoding)
        for encoding in ("br", "gzip"):
            if encoding in self.variants and encoding in accepted:
                return self.variants[encoding]
        return self.variants["identity"]


def _accepted_encodings(header: str) -> set[str]:
    result: set[str] = set()
    for part in header.split(","):
        name, _, params = part.strip().partition(";")
        name = name.strip().lower()
        if not name:
            continue
        quality = 1.0
        for param in params.split(";"):
            key, _, value = param.strip().partition("=")
            if key.strip().lower() == "q":
                try:
                    quality = float(value)
                except ValueError:
                    quality = 0.0
        if quality > 0:
            result.add(name)
    if "*" in result:
        result |= {"br", "gzip"}
    return result


def attachment_disposition(path: str) -> str:
    """`Content-Disposition` для скачивания под именем файла из пути.

    Имя латиницей — как есть; с другими буквами — запасное латинское имя и `filename*` в UTF-8
    (RFC 6266), потому что заголовок передаётся в latin-1.
    """
    name = Path(path).name
    if name.isascii() and name.isprintable() and not any(ch in name for ch in '"\\;'):
        return f'attachment; filename="{name}"'
    suffix = Path(name).suffix
    fallback = "download" + (suffix if suffix.isascii() else "")
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{urllib.parse.quote(name)}"


def _etag(body: bytes, suffix: str = "") -> str:
    digest = hashlib.sha256(body).hexdigest()[:20]
    return f'"{digest}{suffix}"'


@dataclass
class StaticBundle:
    """Все файлы одной папки в памяти: путь от корня папки («assets/x.js») → файл."""

    root: Path
    files: dict[str, StaticFile] = field(default_factory=dict)

    @property
    def total_bytes(self) -> int:
        return sum(len(v.body) for f in self.files.values() for v in f.variants.values())

    def get(self, path: str) -> StaticFile | None:
        return self.files.get(path)

    @classmethod
    def load(cls, root: Path, *, hashed_dirs: Iterable[str] = ()) -> StaticBundle:
        """Прочитать папку. `hashed_dirs` — папки сборки, где имена файлов несут хеш."""
        bundle = cls(root=root)
        hashed = tuple(d.strip("/") + "/" for d in hashed_dirs)
        paths = sorted(p for p in root.rglob("*") if p.is_file())
        names = {p.relative_to(root).as_posix() for p in paths}
        for path in paths:
            rel = path.relative_to(root).as_posix()
            if _skipped(rel, names):
                continue
            body = path.read_bytes()
            media_type = media_type_of(rel)
            variants = {"identity": Variant(body, _etag(body), None)}
            if COMPRESSIBLE.match(media_type) and len(body) >= MIN_COMPRESS_BYTES:
                for encoding, ext in (("br", ".br"), ("gzip", ".gz")):
                    ready = path.with_name(path.name + ext)
                    packed = ready.read_bytes() if ready.is_file() else None
                    if packed is None and encoding == "gzip":
                        packed = gzip.compress(body, compresslevel=9, mtime=0)
                    if packed is not None and len(packed) < len(body) * 0.95:
                        suffix = "-br" if encoding == "br" else "-gz"
                        variants[encoding] = Variant(packed, _etag(body, suffix), encoding)
            immutable = rel.startswith(hashed) and HASHED_NAME.search(rel) is not None
            is_page = media_type.startswith("text/html")
            bundle.files[rel] = StaticFile(
                path=rel,
                media_type=media_type,
                cache_control=CACHE_IMMUTABLE if immutable else CACHE_REVALIDATE,
                variants=variants,
                csp=page_csp(body) if is_page else None,
                disposition=(
                    attachment_disposition(rel)
                    if Path(rel).suffix.lower() in DOWNLOAD_SUFFIXES
                    else None
                ),
            )
        return bundle


def _skipped(rel: str, names: set[str]) -> bool:
    """Служебное не раздаём: скрытые файлы, документацию, готовые .br/.gz (они — варианты)."""
    parts = rel.split("/")
    if any(part.startswith(".") for part in parts):
        return True
    if rel.lower().endswith(".md"):
        return True
    return any(rel.endswith(ext) and rel[: -len(ext)] in names for ext in (".br", ".gz"))


def load_bundle(
    directory: Path | None, what: str, *, hashed_dirs: Iterable[str] = ()
) -> StaticBundle | None:
    if directory is None:
        return None
    if not (directory / "index.html").is_file():
        log.warning("%s: в папке %s нет index.html — не раздаётся", what, directory)
        return None
    bundle = StaticBundle.load(directory, hashed_dirs=hashed_dirs)
    log.info(
        "%s: %s файлов, %s КБ в памяти (с вариантами сжатия)",
        what,
        len(bundle.files),
        bundle.total_bytes // 1024,
    )
    return bundle


class StaticSite:
    """ASGI-приложение: сайт на «/», веб-версия на «/app/». Подключается к FastAPI последним."""

    APP_PREFIX = "/app"

    def __init__(self, site: StaticBundle | None, app: StaticBundle | None) -> None:
        self.site = site
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return
        path = str(scope.get("path", "/"))
        if path == "/api" or path.startswith(("/api/", "/health")):
            # Неизвестный адрес API — ответ API (JSON), а не страница сайта.
            raise HTTPException(status_code=404)
        method = str(scope.get("method", "GET"))
        if method not in ("GET", "HEAD"):
            await _plain(send, 405, "Метод не поддерживается.", [(b"allow", b"GET, HEAD")])
            return
        if path == self.APP_PREFIX:
            query = scope.get("query_string", b"")
            await _redirect(send, b"/app/" + (b"?" + query if query else b""))
            return
        if path.startswith(self.APP_PREFIX + "/"):
            await self._serve_app(scope, send, path[len(self.APP_PREFIX) + 1 :])
            return
        await self._serve_site(scope, send, path.lstrip("/"))

    async def _serve_app(self, scope: Scope, send: Send, rel: str) -> None:
        if self.app is None:
            await _not_found(send, scope)
            return
        found = self.app.get(rel or "index.html")
        if found is None and _is_route(rel):
            found = self.app.get("index.html")  # маршрут интерфейса (SPA)
        if found is None:
            await _not_found(send, scope)
            return
        await _send_file(scope, send, found)

    async def _serve_site(self, scope: Scope, send: Send, rel: str) -> None:
        if self.site is None:
            await _not_found(send, scope)
            return
        if rel == "" or rel.endswith("/"):
            rel += "index.html"
        found = self.site.get(rel)
        if found is None and self.site.get(rel + "/index.html") is not None:
            await _redirect(send, ("/" + rel + "/").encode())
            return
        if found is None:
            await _not_found(send, scope)
            return
        await _send_file(scope, send, found)


def _is_route(rel: str) -> bool:
    """«search/123» — маршрут интерфейса; «assets/x.js», «favicon.png» — файл."""
    last = rel.rsplit("/", 1)[-1]
    return "." not in last or last.endswith(".html")


def _request_header(scope: Scope, name: bytes) -> str:
    for key, value in scope.get("headers") or []:
        if key.lower() == name:
            return bytes(value).decode("latin-1")
    return ""


def _etag_matches(header: str, etag: str) -> bool:
    if not header:
        return False
    tags = [t.strip() for t in header.split(",")]
    plain = etag.strip('"')
    for tag in tags:
        if tag == "*":
            return True
        candidate = tag[2:] if tag.startswith("W/") else tag
        if candidate.strip('"') == plain:
            return True
    return False


async def _send_file(scope: Scope, send: Send, file: StaticFile) -> None:
    variant = file.choose(_request_header(scope, b"accept-encoding"))
    headers: list[tuple[bytes, bytes]] = [
        (b"etag", variant.etag.encode()),
        (b"cache-control", file.cache_control.encode()),
    ]
    if len(file.variants) > 1:
        headers.append((b"vary", b"Accept-Encoding"))
    if _etag_matches(_request_header(scope, b"if-none-match"), variant.etag):
        await send({"type": "http.response.start", "status": 304, "headers": headers})
        await send({"type": "http.response.body", "body": b""})
        return
    headers += [
        (b"content-type", file.media_type.encode()),
        (b"content-length", str(len(variant.body)).encode()),
    ]
    if variant.encoding is not None:
        headers.append((b"content-encoding", variant.encoding.encode()))
    if file.disposition is not None:
        headers.append((b"content-disposition", file.disposition.encode("latin-1")))
    if file.csp is not None:
        headers.append((b"content-security-policy", file.csp.encode()))
        headers += PAGE_HEADERS
    body = b"" if scope.get("method") == "HEAD" else variant.body
    await send({"type": "http.response.start", "status": 200, "headers": headers})
    await send({"type": "http.response.body", "body": body})


async def _not_found(send: Send, scope: Scope) -> None:
    body = NOT_FOUND_PAGE.encode()
    headers = [
        (b"content-type", b"text/html; charset=utf-8"),
        (b"content-length", str(len(body)).encode()),
        (b"cache-control", b"no-store"),
        (b"content-security-policy", page_csp(body).encode()),
    ]
    await send({"type": "http.response.start", "status": 404, "headers": headers})
    await send(
        {"type": "http.response.body", "body": b"" if scope.get("method") == "HEAD" else body}
    )


async def _redirect(send: Send, location: bytes) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 308,
            "headers": [(b"location", location), (b"content-length", b"0")],
        }
    )
    await send({"type": "http.response.body", "body": b""})


async def _plain(send: Send, status: int, message: str, extra: list[tuple[bytes, bytes]]) -> None:
    body = message.encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
                *extra,
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def build_static(site_dir: Path | None, web_app_dir: Path | None) -> StaticSite | None:
    """Раздача статики по настройкам; ни одной папки — None (сервер отдаёт только API)."""
    site = load_bundle(site_dir, "Сайт")
    app = load_bundle(web_app_dir, "Веб-версия", hashed_dirs=("assets",))
    if site is None and app is None:
        return None
    return StaticSite(site, app)
