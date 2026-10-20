"""Разбор ответов сайтов СМИ: лента RSS/Atom, страница статьи, карточки новостей и поиска.

Разметка «битрикс-платформы» районных газет края проверена на живых ответах 20.10.2026
(`docs/research/zen-and-sites.md` §2.3; образцы — `server/tests/samples/sites`):
- лента `/rss/`: `title`, `link`, `description`, `yandex:full-text` (полный текст в HTML),
  `pubDate` с поясом +0700; у «Енисея» полный текст — `content:encoded`;
- статья: `h1.article__title`, `.article-attributes-item--time` («19.10.2026 13:59:24»,
  время края), `.article-attributes-item--views`, `.article__text-content`;
- раздел `/news/` и поиск `/search/`: карточки `a.news-card__link-to-article` с
  `.news-card__title`, `.news-card__description` и `.news-card__date`.

XML лент разбираем безопасным парсером (`defusedxml`): чужая лента не может навредить
серверу. Непонятный ответ — `ParseError` (НТ-5: это ошибка, а не «ничего не найдено»).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as SafeXml
from defusedxml.common import DefusedXmlException

from mediamonitor.timeutil import KRSK, to_krsk


class ParseError(Exception):
    """Ответ сайта не удалось разобрать."""


# ---------------------------------------------------------------- лёгкое дерево HTML

_VOID = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
_BLOCK = {
    "p",
    "div",
    "br",
    "li",
    "ul",
    "ol",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "tr",
    "blockquote",
    "section",
    "article",
    "figure",
    "figcaption",
    "table",
    "hr",
}
_SKIP = {"script", "style", "noscript", "template", "svg"}


@dataclass
class Node:
    tag: str
    attrs: dict[str, str]
    children: list[Node | str] = field(default_factory=list)

    @property
    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def find_all(self, *, tag: str | None = None, cls: str | None = None) -> list[Node]:
        found: list[Node] = []
        stack: list[Node] = [self]
        while stack:
            node = stack.pop()
            for child in reversed(node.children):
                if isinstance(child, Node):
                    if (tag is None or child.tag == tag) and (cls is None or cls in child.classes):
                        found.append(child)
                    stack.append(child)
        return found

    def find(self, *, tag: str | None = None, cls: str | None = None) -> Node | None:
        found = self.find_all(tag=tag, cls=cls)
        return found[0] if found else None

    def text(self) -> str:
        """Текст узла: блоки — с новой строки, пробелы схлопнуты."""
        parts: list[str] = []
        _collect(self, parts)
        joined = "".join(parts).replace("­", "")  # мягкие переносы из вёрстки
        lines = [" ".join(line.split()) for line in joined.split("\n")]
        return "\n".join(line for line in lines if line)


def _collect(node: Node, parts: list[str]) -> None:
    if node.tag in _SKIP:
        return
    block = node.tag in _BLOCK
    if block:
        parts.append("\n")
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
        else:
            _collect(child, parts)
    if block:
        parts.append("\n")


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {})
        self.stack: list[Node] = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag, {k: v or "" for k, v in attrs})
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.stack[-1].children.append(Node(tag, {k: v or "" for k, v in attrs}))

    def handle_endtag(self, tag: str) -> None:
        # Незакрытые теги закрываем до ближайшего подходящего; лишний закрывающий — пропуск.
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def parse_html(markup: str) -> Node:
    builder = _TreeBuilder()
    builder.feed(markup)
    builder.close()
    return builder.root


_STILL_HTML = re.compile(r"</?[a-z][a-z0-9]*[^<>]*>|&(?:[a-z]{2,8}|#\d{2,5});", re.IGNORECASE)


def html_to_text(markup: str | None) -> str:
    """HTML (полный текст ленты, абзацы статьи) → простой текст с абзацами.

    Некоторые ленты экранируют HTML дважды («&amp;laquo;», «&lt;p&gt;» у «Енисея»):
    если после первого прохода остались теги или сущности — разбираем ещё раз.
    """
    if not markup:
        return ""
    text = parse_html(markup).text()
    if _STILL_HTML.search(text):
        text = parse_html(text).text()
    return text


# ---------------------------------------------------------------- даты на русском

_MONTHS = {
    "янв": 1,
    "фев": 2,
    "мар": 3,
    "апр": 4,
    "мая": 5,
    "май": 5,
    "июн": 6,
    "июл": 7,
    "авг": 8,
    "сен": 9,
    "окт": 10,
    "ноя": 11,
    "дек": 12,
}
_NUMERIC = re.compile(
    r"(?P<d>\d{1,2})\.(?P<m>\d{1,2})\.(?P<y>\d{4})"
    r"(?:[ ,T]+(?P<H>\d{1,2}):(?P<M>\d{2})(?::(?P<S>\d{2}))?)?"
)
_WORDS = re.compile(
    r"(?P<d>\d{1,2})\s+(?P<mon>[а-яё]+)\.?(?:\s+(?P<y>\d{4}))?"
    r"(?:[ ,в]+(?P<H>\d{1,2}):(?P<M>\d{2}))?",
    re.IGNORECASE,
)
_RELATIVE = re.compile(r"(?P<day>сегодня|вчера)(?:[ ,в]+(?P<H>\d{1,2}):(?P<M>\d{2}))?", re.I)
_AGO = re.compile(r"(?P<n>\d+)\s+(?P<unit>минут|час)", re.IGNORECASE)


@dataclass(frozen=True)
class SiteDate:
    moment: datetime  # UTC
    exact: bool  # известно время, а не только день


def parse_ru_date(value: str, now: datetime) -> SiteDate | None:
    """«19.10.2026 13:59:24», «20 октября 2026 09:48», «15.10.2026», «вчера, 12:09»,
    «46 минут назад». Время — красноярское. Не распознали — None."""
    text = " ".join(value.split()).lower()
    if not text:
        return None
    local_now = to_krsk(now)
    if match := _NUMERIC.search(text):
        return _build(
            int(match["y"]),
            int(match["m"]),
            int(match["d"]),
            hour=match["H"],
            minute=match["M"],
            second=match["S"],
        )
    if match := _RELATIVE.search(text):
        day = local_now.date() - timedelta(days=1 if match["day"] == "вчера" else 0)
        return _build(day.year, day.month, day.day, hour=match["H"], minute=match["M"])
    if match := _AGO.search(text):
        unit = timedelta(minutes=1) if match["unit"] == "минут" else timedelta(hours=1)
        return SiteDate((local_now - unit * int(match["n"])).astimezone(UTC), True)
    if match := _WORDS.search(text):
        month = _MONTHS.get(match["mon"][:3])
        if month is None:
            return None
        year = int(match["y"]) if match["y"] else local_now.year
        if not match["y"] and (month, int(match["d"])) > (local_now.month, local_now.day):
            year -= 1  # «19 дек» в январе — это прошлый год
        return _build(year, month, int(match["d"]), hour=match["H"], minute=match["M"])
    return None


def _build(
    year: int,
    month: int,
    day: int,
    *,
    hour: str | None,
    minute: str | None,
    second: str | None = None,
) -> SiteDate | None:
    try:
        clock = time(int(hour or 0), int(minute or 0), int(second or 0))
        local = datetime(year, month, day, clock.hour, clock.minute, clock.second, tzinfo=KRSK)
    except ValueError:
        return None
    return SiteDate(local.astimezone(UTC), hour is not None)


# ---------------------------------------------------------------- лента RSS / Atom


@dataclass(frozen=True)
class FeedItem:
    link: str
    title: str | None
    summary: str
    text: str  # полный текст, если лента его отдаёт; иначе анонс
    full_text: bool
    published_at: datetime | None
    has_media: bool


def _local(tag: Any) -> str:
    name = str(tag)
    return name.rsplit("}", 1)[-1].lower()


def _child(element: Element, name: str) -> Element | None:
    for child in element:
        if _local(child.tag) == name:
            return child
    return None


def _child_text(element: Element, name: str) -> str | None:
    child = _child(element, name)
    if child is None:
        return None
    return (child.text or "").strip() or None


def _feed_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        moment = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=KRSK)
    return moment.astimezone(UTC)


def parse_feed(data: str | bytes) -> list[FeedItem]:
    """Лента RSS 2.0 или Atom → материалы. Не лента — ParseError."""
    raw = data.encode("utf-8") if isinstance(data, str) else data
    try:
        root = SafeXml.fromstring(raw)
    except (SafeXml.ParseError, DefusedXmlException, ValueError) as error:
        raise ParseError("лента не читается как XML") from error
    kind = _local(root.tag)
    if kind == "rss":
        channel = _child(root, "channel")
        if channel is None:
            raise ParseError("в ленте нет channel")
        entries = [e for e in channel if _local(e.tag) == "item"]
    elif kind == "feed":
        entries = [e for e in root if _local(e.tag) == "entry"]
    else:
        raise ParseError(f"это не лента RSS или Atom: <{kind}>")
    items: list[FeedItem] = []
    for entry in entries:
        link = _child_text(entry, "link")
        if not link:
            node = _child(entry, "link")
            link = node.get("href") if node is not None else None
        if not link:
            continue
        summary = html_to_text(_child_text(entry, "description") or _child_text(entry, "summary"))
        full = (
            _child_text(entry, "full-text")
            or _child_text(entry, "encoded")
            or _child_text(entry, "content")
        )
        text = html_to_text(full) if full else summary
        published = _feed_date(
            _child_text(entry, "pubdate")
            or _child_text(entry, "published")
            or _child_text(entry, "updated")
            or _child_text(entry, "date")
        )
        media = any(_local(c.tag) in ("enclosure", "content", "thumbnail") for c in entry)
        items.append(
            FeedItem(
                link=link.strip(),
                title=html_to_text(_child_text(entry, "title")) or None,
                summary=summary,
                text=text or summary,
                full_text=bool(full),
                published_at=published,
                has_media=media or "<img" in (full or ""),
            )
        )
    return items


# ---------------------------------------------------------------- страница статьи


@dataclass(frozen=True)
class Article:
    title: str | None
    text: str
    published_at: datetime | None
    exact_time: bool
    views: int | None
    has_media: bool


_DIGITS = re.compile(r"\d[\d\s ]*")


def _meta(root: Node, prop: str) -> str | None:
    for node in root.find_all(tag="meta"):
        if node.attrs.get("property") == prop or node.attrs.get("name") == prop:
            value = node.attrs.get("content", "").strip()
            if value:
                return value
    return None


def parse_count(value: str | None) -> int | None:
    if not value:
        return None
    match = _DIGITS.search(value)
    if match is None:
        return None
    digits = re.sub(r"\D", "", match.group(0))
    return int(digits) if digits else None


def parse_article(markup: str, now: datetime) -> Article:
    """Страница статьи «битрикс-платформы»; запасной путь — метатеги Open Graph."""
    root = parse_html(markup)
    title_node = root.find(cls="article__title") or root.find(tag="h1")
    title = title_node.text() if title_node else None
    title = title or _meta(root, "og:title")
    body = root.find(cls="article__text-content")
    text = body.text() if body else ""
    if not text:
        text = _meta(root, "og:description") or ""
    when = root.find(cls="article-attributes-item--time")
    published: SiteDate | None = parse_ru_date(when.text(), now) if when else None
    if published is None:
        stamp = _meta(root, "article:published_time")
        moment = _feed_date(stamp) if stamp else None
        published = SiteDate(moment, True) if moment else None
    views_node = root.find(cls="article-attributes-item--views")
    views = parse_count(views_node.text()) if views_node else None
    if not title and not text:
        raise ParseError("на странице нет заголовка и текста статьи")
    return Article(
        title=title,
        text=text,
        published_at=published.moment if published else None,
        exact_time=published.exact if published else False,
        views=views,
        has_media=bool(body and body.find(tag="img")),
    )


# ---------------------------------------------------------------- карточки новостей и поиска


@dataclass(frozen=True)
class Card:
    href: str
    title: str | None
    summary: str
    date: SiteDate | None


def parse_cards(markup: str, now: datetime) -> list[Card]:
    """Карточки раздела новостей или выдачи поиска. Нет карточек — пустой список."""
    root = parse_html(markup)
    cards: list[Card] = []
    seen: set[str] = set()
    for link in root.find_all(tag="a", cls="news-card__link-to-article"):
        href = link.attrs.get("href", "").strip()
        if not href or href in seen:
            continue
        seen.add(href)
        title = link.find(cls="news-card__title")
        summary = link.find(cls="news-card__description")
        when = link.find(cls="news-card__date") or link.find(tag="time")
        cards.append(
            Card(
                href=href,
                title=(title.text() if title else None) or None,
                summary=summary.text() if summary else "",
                date=parse_ru_date(when.text(), now) if when else None,
            )
        )
    return cards


def search_found(markup: str) -> int | None:
    """«Найдено 176 материала» — сколько всего нашёл поиск сайта (для пометки «показаны 50»)."""
    root = parse_html(markup)
    head = root.find(cls="search-news__title")
    return parse_count(head.text()) if head else None
