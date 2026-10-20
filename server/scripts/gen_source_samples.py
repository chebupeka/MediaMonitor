# ruff: noqa: E501, E101, PLR0917 — образцы разметки: длинные строки и табы, как в живых ответах
"""Образцы ответов сайтов СМИ и Дзена: `src/mediamonitor/fixtures/sources/`.

Нужны режиму SITES_SOURCE/DZEN_SOURCE=fixtures (adapters/replay.py) и тестам: из-за рубежа
сайты края не открываются. Разметка и структура повторяют живые ответы 20.10.2026
(«битрикс-платформа» районных газет: лента /rss/, статья, раздел /news/, поиск; лента
«Енисея» с дважды экранированным HTML; JSON страницы канала Дзена и страница публикации),
тексты — свои. Даты — 9–20 октября 2026 (время красноярское).

Запуск: uv run python scripts/gen_source_samples.py [папка]
"""

from __future__ import annotations

import html
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT = Path(__file__).resolve().parents[1] / "src" / "mediamonitor" / "fixtures" / "sources"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
OUT.mkdir(parents=True, exist_ok=True)
K = timezone(timedelta(hours=7))


def k(y, mo, d, h=0, mi=0, s=0):
    return datetime(y, mo, d, h, mi, s, tzinfo=K)


def rfc(dt):
    return dt.strftime("%a, %d %b %Y %H:%M:%S +0700")


RELEASE_TITLE = "Эскроу-счёт поможет воплотить мечту о своём доме"
RELEASE = [
    "Жители Красноярского края могут построить частный дом с использованием эскроу-счёта.",
    "Деньги на счёте хранятся в банке и переходят к подрядчику только после того, как дом "
    "построен и принят.",
    "Так семья защищена от недобросовестных строителей.",
    "Подробнее о программе рассказали в министерстве строительства края.",
    "Подать заявку можно в банках-партнёрах.",
]

# ------------------------------------------------------------ Битрикс: лента RSS


def bitrix_rss(site, items):
    head = (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0" '
        'xmlns="https://cyber.harvard.edu/rss/rss.html" xmlns:yandex="https://news.yandex.ru">\n'
        "<channel>\n<title>Новости</title>\n"
        f"<link>https://{site}</link>\n<description></description>\n"
        f"<lastBuildDate>{rfc(k(2026, 10, 20, 14, 47, 19))}</lastBuildDate>\n<ttl>60</ttl>\n"
    )
    body = []
    for it in items:
        full = "".join(
            (
                f"&lt;b&gt;{html.escape(p)}&lt;/b&gt;&lt;br&gt;\n"
                if i == 0
                else f" {html.escape(p)}&lt;br&gt;\n &lt;br&gt;\n"
            )
            for i, p in enumerate(it["text"])
        )
        body.append(
            "<item>\n"
            f"\t<title>{html.escape(it['title'])}</title>\n"
            f"\t<link>https://{site}/news/{it['slug']}/</link>\n"
            f"\t<description>{html.escape(it['text'][0])}</description>\n"
            f'\t\t\t<enclosure url="https://{site}/upload/iblock/0a1/{it["slug"][:12]}.jpg" '
            'length="52146" type="image/jpeg"/>\n'
            f"\t\t\t\t\t<yandex:full-text>{full}</yandex:full-text>\n"
            f"\t\t<pubDate>{rfc(it['at'])}</pubDate>\n"
            "</item>\n"
        )
    return head + "".join(body) + "</channel>\n</rss>\n"


BITRIX_HEAD = """<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="shortcut icon" type="image/png" href="/favicon.png"> <title>{title}</title>
    <meta property="og:type" content="website"> <meta property="og:site_name" content="{site_name}"> <meta property="og:title" content="{title}"> <meta property="og:description" content="{desc}"> <meta property="og:url" content="https://{host}"> <meta property="og:locale" content="ru_RU">
</head>
<body>
    <div class="wrapper">
        <header class="header">
            <section class="header__top"><a class="logo" href="/">{site_name}</a>
                <nav class="menu"><a href="/news/">Новости</a><a href="/search/">Поиск</a></nav>
            </section>
        </header>
        <main class="content">
            <div class="section">
                <div class="section__container-content">
"""
BITRIX_TAIL = """                </div>
            </div>
        </main>
        <footer class="footer"><p>Сетевое издание «{site_name}». 18+</p>
            <script>window.dataLayer = window.dataLayer || [];</script>
        </footer>
    </div>
</body>
</html>
"""


def bitrix_article(host, site_name, title, at, views, paragraphs):
    text = "<br>\n ".join(
        (f"<b>{html.escape(p)}</b>" if i == 0 else html.escape(p)) for i, p in enumerate(paragraphs)
    )
    middle = f"""  <div class="article">
                                <h1 class="article__title">{html.escape(title)}</h1>
                                <div class="article__attributes">
                                    <div class="article-attributes">
                                        <div class="article-attributes-item">
                                            <div class="article-attributes-item__icon">
                                                <i class="icon-time"></i>
                                            </div>
                                            <div data-format="article" class="article-attributes-item__value article-attributes-item--time">
                                                {at.strftime("%d.%m.%Y %H:%M:%S")}
                                            </div>
                                        </div>
                                        <div class="article-attributes-item">
                                            <div class="article-attributes-item__icon">
                                                <i class="icon-views"></i>
                                            </div>
                                            <div class="article-attributes-item__value article-attributes-item--views">
                                                {views}
                                            </div>
                                        </div>
                                    </div>
                                </div>
                                <div class="article__text-content">
                                    <div class="text-content"> <div class="text-content_image"><img src="/upload/iblock/487/photo.jpg" alt="{html.escape(title)}"></div>{text}</div>
                                </div>
                                <div class="article__share"><span>Поделиться</span><a href="https://vk.com/share.php">VK</a></div>
                            </div>
"""
    return (
        BITRIX_HEAD.format(
            title=html.escape(title),
            site_name=site_name,
            desc=html.escape(paragraphs[0]),
            host=host,
        )
        + middle
        + BITRIX_TAIL.format(site_name=site_name)
    )


def news_card(href, title, desc, date_text, fmt):
    return f"""				<li class="search-news__news-item">
				    <div class="search-news__news-card">
					<div class="news-card news-card_type_horiz-bycount news-card_full_container news-card_with_image">
					    <a class="news-card__link-to-article" href="{href}">
						<article class="news-card__article news-card__article_with_image">
						    <div class="news-card__content">
							<h3 class="news-card__title">{title}</h3>
							<p class="news-card__description">{desc}</p>
							<p class="news-card__meta-info"><time data-format="{fmt}" data-only-time="False" class="news-card__date">{date_text}</time></p>
						    </div>
						</article>
					    </a>
					</div>
				    </div>
				</li>
"""


def bitrix_search(host, site_name, query, cards):
    middle = (
        f"""                            <form action="/search/" class="search-form"><input type="text" name="q" value="{html.escape(query)}" class="search-form__input"><input type="hidden" name="how" value="d" class="search-form__sort"></form>
                            <div class="search-news__top">
                                <h1 class="search-news__title"> Найдено {len(cards)} материала  </h1>
                                <div class="sort tabs"><div class="tabs-buttons"><div class="tabs-buttons__inner">
                                    <div class="tabs-buttons__item" data-search-sort=""><a href="/search/?q=x&amp;where=&amp;how=r">По релевантности</a></div>
                                    <div class="tabs-buttons__item _active" data-search-sort="date"><a href="/search/?q=x&amp;where=&amp;how=d">По дате</a></div>
                                </div></div></div>
                            </div>
                            <ul class="search-news__news-list js-more-target">
"""
        + "".join(news_card(*c, "time-macro") for c in cards)
        + """                            </ul>
"""
    )
    return (
        BITRIX_HEAD.format(title="Поиск", site_name=site_name, desc="Поиск по сайту", host=host)
        + middle
        + BITRIX_TAIL.format(site_name=site_name)
    )


def bitrix_list(host, site_name, cards):
    items = "".join(
        f"""				<li class="materials__news-card  materials__news-card_with-image" id="bx_651765591_{13000 + i}">
                                        <div class="news-card news-card_type_horiz-bycount news-card_with_image">
                                            <a class="news-card__link-to-article" href="{href}">
                                                <article class="news-card__article news-card__article_with_image">
                                                    <figure class="news-card__image-wrapper">
                                                        <img class="news-card__image swiper-lazy lazy" src="/upload/iblock/0b4/card{i}.jpg" alt="{title}">
                                                    </figure>
                                                    <div class="news-card__content">
                                                        <h3 class="news-card__title">
                                                            {title}                                                         </h3>
                                                        <p class="news-card__description">
                                                            <br />
{desc}                                                         </p>
							<p class="news-card__meta-info">
                                                            <time data-format="date" class="news-card__date">
                                                                {date_text}
                                                            </time>
                                                        </p>
                                                    </div>
                                                </article>
                                            </a>
                                        </div>
                                    </li>
"""
        for i, (href, title, desc, date_text) in enumerate(cards)
    )
    middle = f"""    <h1 class="materials__title"><span class="materials__title-text">Новости</span></h1>

<ul class="materials__list js-more-target">
{items}</ul>
<div class="pagination"><a href="/news/?PAGEN_1=2">Показать ещё</a></div>
"""
    return (
        BITRIX_HEAD.format(title="Новости", site_name=site_name, desc="Новости", host=host)
        + middle
        + BITRIX_TAIL.format(site_name=site_name)
    )


def write(name, text):
    (OUT / name).write_text(text, encoding="utf-8", newline="\n")


# ------------------------------------------------------------ Власть труда (vtruda.ru)
medvedi = [
    "С августа на территории Минусинского округа охотнадзор зафиксировал больше сорока выходов медведей к жилью.",
    "Сообщения о хищниках возле домов продолжают поступать, особенно с окраин и садовых обществ.",
    "Специалисты просят жителей не выносить мусор за пределы контейнерных площадок и не оставлять корм для животных.",
]
perehod = [
    "В Минусинске у школы № 2 обновили разметку пешеходного перехода и установили светофор Т.7.",
    "Работы прошли по программе безопасности дорожного движения: в этом году переходы обновили у пяти школ.",
]
vtruda_items = [
    {
        "title": "Медведи не уходят",
        "slug": "medvedi-ne-ukhodyat",
        "at": k(2026, 10, 19, 13, 59, 24),
        "text": medvedi,
    },
    {
        "title": RELEASE_TITLE,
        "slug": "eskrou-schyet-pomozhet-voplotit-mechtu-o-svoyem-dome",
        "at": k(2026, 10, 19, 12, 9, 0),
        "text": RELEASE,
    },
    {
        "title": "У школы № 2 обновили пешеходный переход",
        "slug": "u-shkoly-2-obnovili-peshekhodnyy-perekhod",
        "at": k(2026, 10, 18, 10, 0, 0),
        "text": perehod,
    },
    {
        "title": "Осенний кросс собрал двести участников",
        "slug": "osenniy-kross-sobral-dvesti-uchastnikov",
        "at": k(2026, 10, 17, 15, 30, 0),
        "text": [
            "На стадионе «Электрон» прошёл осенний кросс.",
            "На старт вышли двести бегунов от школьников до ветеранов.",
        ],
    },
    {
        "title": "Библиотека приглашает на встречу с краеведом",
        "slug": "biblioteka-priglashaet-na-vstrechu-s-kraevedom",
        "at": k(2026, 10, 16, 9, 0, 0),
        "text": [
            "Центральная библиотека приглашает на встречу с краеведом.",
            "Разговор пойдёт об истории старого Минусинска.",
        ],
    },
]
write("vtruda-rss.xml", bitrix_rss("vtruda.ru", vtruda_items))
write(
    "vtruda-article-medvedi.html",
    bitrix_article(
        "vtruda.ru", "Власть труда", "Медведи не уходят", k(2026, 10, 19, 13, 59, 24), 52, medvedi
    ),
)
okolitsa = [
    "Медведь несколько ночей подряд приходил к огородам на окраине села Городок.",
    "Охотнадзор установил ловушку и просит жителей быть осторожнее по вечерам.",
]
write(
    "vtruda-article-okolitsa.html",
    bitrix_article(
        "vtruda.ru",
        "Власть труда",
        "Медведь за околицей",
        k(2026, 10, 14, 11, 20, 0),
        120,
        okolitsa,
    ),
)
write(
    "vtruda-search.html",
    bitrix_search(
        "vtruda.ru",
        "Власть труда",
        "медведи",
        [
            (
                "/news/medvedi-ne-ukhodyat/?sphrase_id=4885",
                "<b>Медведи</b> не уходят",
                "С августа на территории Минусинского округа охотнадзор зафиксировал больше сорока выходов <b>медведей</b> к жилью. ...",
                "19.10.2026",
            ),
            (
                "/news/medved-za-okolitsey/?sphrase_id=4885",
                "<b>Медведь</b> за околицей",
                "<b>Медведь</b> несколько ночей подряд приходил к огородам на окраине села Городок. ...",
                "14.10.2026",
            ),
            (
                "/news/medved-vyshel-k-dacham/?sphrase_id=4885",
                "<b>Медведь</b> вышел к дачам",
                "Жители СНТ «Электромашиностроитель» сообщили о <b>медведе</b> у дачных участков. ...",
                "08.10.2026",
            ),
            (
                "/news/kak-vesti-sebya-pri-vstreche-s-medvedem/?sphrase_id=4885",
                "Как вести себя при встрече с <b>медведем</b>",
                "Памятка охотнадзора для грибников и дачников. ...",
                "12.08.2026",
            ),
        ],
    ),
)

# ------------------------------------------------------------ Канские ведомости (kvgazeta.ru)
write(
    "kvgazeta-rss.xml",
    bitrix_rss(
        "kvgazeta.ru",
        [
            {
                "title": RELEASE_TITLE,
                "slug": "eskrou-schyet-pomozhet-voplotit-mechtu-o-svoyem-dome",
                "at": k(2026, 10, 19, 15, 40, 0),
                "text": RELEASE[:2],
            },
            {
                "title": "Канские школьники изучают правила дорожного движения",
                "slug": "kanskie-shkolniki-izuchayut-pdd",
                "at": k(2026, 10, 18, 11, 0, 0),
                "text": [
                    "В школах Канска прошла неделя безопасности дорожного движения.",
                    "Инспекторы ГИБДД рассказали ученикам о световозвращающих элементах.",
                ],
            },
            {
                "title": "Всемирный день качества",
                "slug": "vsemirnyy-den-kachestva-2026",
                "at": k(2026, 10, 17, 12, 0, 9),
                "text": [
                    "Во второй четверг ноября отмечают Всемирный день качества.",
                    "Предприятия Канска готовят дни открытых дверей.",
                ],
            },
        ],
    ),
)

write(
    "kvgazeta-search.html",
    bitrix_search(
        "kvgazeta.ru",
        "Канские ведомости",
        "дорожного движения",
        [
            (
                "/news/kanskie-shkolniki-izuchayut-pdd/?sphrase_id=5938",
                "Канские школьники изучают правила <b>дорожного движения</b>",
                "В школах Канска прошла неделя безопасности <b>дорожного движения</b>. ...",
                "18.10.2026",
            ),
            (
                "/articles/bezopasnaya-doroga-v-shkolu/?sphrase_id=5938",
                "Безопасная дорога в школу",
                "Инспекторы проверили маршруты школьных автобусов и переходы у школ Канского округа. ...",
                "09.10.2026",
            ),
        ],
    ),
)

# ------------------------------------------------------------ Ангарская правда (angarka.info): без ленты
write(
    "angarka-search.html",
    bitrix_search(
        "angarka.info",
        "Ангарская правда",
        "медведи",
        [
            (
                "/news/medved-u-poselka-govorkovo/?sphrase_id=4886",
                "<b>Медведь</b> у посёлка Говорково",
                "Охотники Богучанского округа предупреждают о <b>медведе</b> у посёлка. ...",
                "07.10.2026",
            ),
        ],
    ),
)
write(
    "angarka-news.html",
    bitrix_list(
        "angarka.info",
        "Ангарская правда",
        [
            (
                "/news/eskrou-schyet-pomozhet-voplotit-mechtu-o-svoyem-dome/",
                RELEASE_TITLE,
                RELEASE[0],
                "19 октября 2026 12:09",
            ),
            (
                "/news/moroz-prishel-povtorim-pravila/",
                "Мороз пришёл: повторим правила безопасности на льду",
                "Спасатели Богучанского округа напоминают: выходить на лёд рано.",
                "18 октября 2026 16:40",
            ),
            (
                "/news/boguchanskie-spasateli-proveli-ucheniya/",
                "Богучанские спасатели провели учения",
                "На Ангаре отработали спасение людей с плавучей техники.",
                "15 октября 2026 10:15",
            ),
            (
                "/news/sorok-let-kuet-metall-i-kharaktery/",
                "Сорок лет куёт металл и характеры",
                "История кузнеца из Богучан.",
                "10 октября 2026 09:00",
            ),
        ],
    ),
)
write(
    "angarka-article-eskrou.html",
    bitrix_article(
        "angarka.info", "Ангарская правда", RELEASE_TITLE, k(2026, 10, 19, 12, 9, 0), 31, RELEASE
    ),
)

# ------------------------------------------------------------ Енисей (enisey.tv): своя лента, текст экранирован дважды


def enisey_item(num, title, at, paragraphs, category):
    def ent(text):
        return text.replace("«", "&laquo;").replace("»", "&raquo;")

    inner = "".join(f"<p>{ent(p)}</p>\n" for p in paragraphs)
    encoded = html.escape(html.escape(inner, quote=False), quote=False)
    desc = html.escape(ent(paragraphs[0][:180]) + "&hellip;", quote=False)
    return (
        f"<item><title>{html.escape(title)}</title><guid>{num}</guid>"
        f"<link>https://www.enisey.tv/news/post-{num}/</link>"
        f"<description>{desc}</description><category>{category}</category>"
        f"<content:encoded>{html.escape(title)}\n{encoded}</content:encoded>"
        '<condition xmlns="http://base.google.com/ns/1.0">new</condition>'
        f"<pubDate>{rfc(at)}</pubDate></item>"
    )


write(
    "enisey-rss.xml",
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<rss xmlns:yandex="http://news.yandex.ru" xmlns:content="http://purl.org/rss/1.0/modules/content/" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:media="http://search.yahoo.com/mrss/" '
    'xmlns:atom="http://www.w3.org/2005/Atom" xmlns:georss="http://www.georss.org/georss" version="2.0">'
    "<channel><title>Енисей-ТВ</title><link>https://www.enisey.tv</link><description>Краевой телеканал Енисей </description>"
    "<yandex:logo>https://www.enisey.tv/static/i/rss_normal_logo.png</yandex:logo>"
    + enisey_item(
        96891,
        "На набережной появился арт-объект с рыбами «Рыбы Енисея»",
        k(2026, 10, 20, 14, 9, 35),
        [
            "В Красноярске на Центральной набережной появился новый арт-объект «Рыбы Енисея».",
            "На ограждениях можно увидеть фигуры налима, корюшки и тайменя.",
        ],
        "Общество",
    )
    + enisey_item(
        96850,
        "Водителям напомнят о ремонте Коммунального моста",
        k(2026, 10, 19, 18, 0, 0),
        [
            "С понедельника на Коммунальном мосту ограничат движение.",
            "Дорожники просят водителей заранее выбирать объезд.",
        ],
        "Транспорт",
    )
    + enisey_item(96801, RELEASE_TITLE, k(2026, 10, 19, 10, 5, 0), RELEASE, "Экономика")
    + "</channel></rss>\n",
)

# ------------------------------------------------------------ Дзен


def ts(dt):
    return str(int(dt.timestamp()))


VT = "647edcf397f79c2656d02daf"
AP = "611c742476e1862f7f85ab3a"


def dz_article(pub, item_id, num, title, text, at, views=None, likes=None):
    out = {
        "id": item_id,
        "type": "article",
        "itemId": num,
        "itemType": "native",
        "title": title,
        "text": text,
        "sourceId": pub,
        "shareLink": f"https://dzen.ru/a/{num}",
        "link": f"https://dzen.ru/a/{num}?feed_exp=ordinary_feed&from=channel&integration=site_desktop&place=layout",
        "isPromoPublication": False,
        "timeToReadSeconds": 40,
        "publicationDate": ts(at),
        "image": {
            "src": f"https://avatars.dzeninfra.ru/get-zen_doc/1/pub_{item_id}/smart_crop_516x290"
        },
        "socialInfo": {
            "commentsEnabled": True,
            "commentCount": 0,
            **({"likesCount": likes} if likes else {}),
            "avatarUrls": [],
        },
        "version": "newApi",
    }
    if views is not None:
        out["views"] = views
    return out


def dz_brief(pub, num, text, at, views=None):
    out = {
        "publisher_id": pub,
        "publication_id": f"brief:{num}",
        "id": "-690550802708067137",
        "type": "brief",
        "title": "",
        "text": "",
        "share_link": f"https://dzen.ru/b/{num}",
        "publication_date": ts(at),
        "items": [{"type": "image", "image": {"id": "img1"}}],
        "rich_text": {"length": len(text), "json": [{"type": "text", "data": text}]},
        "socialInfo": {"commentsEnabled": True, "commentCount": 0, "avatarUrls": []},
    }
    if views is not None:
        out["views"] = views
    return out


def dz_channel(pub, name, title, subscribers, items, more):
    feed = {
        "rid": "3785792931.1336.1792486195155.13243",
        "items": items,
        "ad_items": [],
        "isNewApi": True,
    }
    if more:
        feed["more"] = {"link": more}
    return {
        "clientDefinition": {},
        "isNewApi": True,
        "feedData": feed,
        "channel": {
            "status": "ok",
            "source": {
                "id": "2646461040013477267",
                "publisher_id": pub,
                "type": "publisher",
                "title": title,
                "subscribers": subscribers,
                "feed_share_link": f"https://dzen.ru/{name}"
                if name
                else f"https://dzen.ru/id/{pub}",
            },
        },
    }


more = "https://dzen.ru/api/web/v1/channel-more?channel_name=vtruda&sort_type=regular&country_code=ru&next_page_id=articles%2F1828941992899737570%2F1791936000000&lang=ru"
write(
    "dzen-vtruda.json",
    json.dumps(
        dz_channel(
            VT,
            "vtruda",
            "О Сибири с любовью!",
            2823,
            [
                dz_article(
                    VT,
                    "6ad72930f9c4b3533a4d5369",
                    "aTdzEskrou01QwEr",
                    RELEASE_TITLE,
                    " ".join(RELEASE[:3]),
                    k(2026, 10, 19, 14, 0, 0),
                    views=30,
                ),
                {"id": "17522652720167549", "type": "suites_carousel", "title": "Подборки автора"},
                dz_article(
                    VT,
                    "6ad18de2a82a603e7d1838c8",
                    "aTdzMedvedi01aBc",
                    "Медведи: карантин и новые меры",
                    "В Минусинском округе медведи продолжают выходить к домам. Охотнадзор рассказал, какие меры примут этой осенью и что делать, если зверь пришёл к огороду...",
                    k(2026, 10, 18, 12, 0, 0),
                    views=46,
                    likes=1,
                ),
                dz_brief(
                    VT,
                    "bTdzPerehod01xYz",
                    "Водители, будьте внимательны: у школ Минусинска обновили переходы и поставили новые светофоры.",
                    k(2026, 10, 17, 9, 30, 0),
                    views=7,
                ),
                dz_article(
                    VT,
                    "6ad0a49c1bcbe32a98c5a3b6",
                    "aTdzTochka01RoST",
                    "В селе Городок открылась «Точка роста»",
                    "В школе села Городок открылся центр «Точка роста» с лабораториями физики и биологии.",
                    k(2026, 10, 14, 10, 0, 0),
                    views=14,
                ),
            ],
            more,
        ),
        ensure_ascii=False,
        indent=1,
    ),
)
write(
    "dzen-vtruda-more.json",
    json.dumps(
        {
            "rid": "3785792931.1336.1792486195155.13244",
            "items": [
                dz_article(
                    VT,
                    "6acd0a49c1bcbe32a98c5a01",
                    "aTdzOldOne01ZzZz",
                    "Сентябрьский субботник на набережной",
                    "Жители Минусинска вышли на субботник на набережной Протоки.",
                    k(2026, 10, 5, 11, 0, 0),
                    views=21,
                ),
                dz_article(
                    VT,
                    "6acd0a49c1bcbe32a98c5a02",
                    "aTdzOldTwo01YyYy",
                    "Как город готовится к отопительному сезону",
                    "Коммунальники проверили котельные и тепловые сети.",
                    k(2026, 9, 28, 16, 0, 0),
                    views=18,
                ),
            ],
            "ad_items": [],
            "isNewApi": True,
        },
        ensure_ascii=False,
        indent=1,
    ),
)
write(
    "dzen-angarka.json",
    json.dumps(
        dz_channel(
            AP,
            None,
            "Ангарская правда",
            158,
            [
                {"id": "-1", "type": "channel_long_video_floor", "title": "Видео"},
                dz_article(
                    AP,
                    "6ad0a49c1bcbe32a98c5b001",
                    "aTdzBogSpas01AaA",
                    "Богучанские спасатели провели учения",
                    "На Ангаре отработали спасение людей с плавучей техники. В учениях участвовали спасатели и добровольцы.",
                    k(2026, 10, 15, 11, 0, 0),
                    views=12,
                ),
                dz_article(
                    AP,
                    "6ad0a49c1bcbe32a98c5b002",
                    "aTdzDomEskr01BbB",
                    "Как защитить деньги, если строите дом",
                    "Эскроу-счёт защищает семью: банк переведёт деньги строителю только после того, как дом построен и принят. Рассказываем, как подать заявку.",
                    k(2026, 10, 19, 16, 0, 0),
                    views=9,
                ),
            ],
            None,
        ),
        ensure_ascii=False,
        indent=1,
    ),
)

state = json.dumps(
    {
        "draftJsState": {
            "blocks": [
                {
                    "data": {},
                    "depth": 0,
                    "entityRanges": [],
                    "inlineStyleRanges": [],
                    "text": "В Минусинском округе медведи продолжают выходить к домам.",
                    "type": "unstyled",
                    "key": "a1",
                },
                {
                    "data": {},
                    "depth": 0,
                    "entityRanges": [],
                    "inlineStyleRanges": [],
                    "text": "",
                    "type": "unstyled",
                    "key": "a2",
                },
                {
                    "data": {},
                    "depth": 0,
                    "entityRanges": [],
                    "inlineStyleRanges": [],
                    "text": "Охотнадзор рассказал, какие меры примут этой осенью и что делать, если зверь пришёл к огороду.",
                    "type": "unstyled",
                    "key": "a3",
                },
            ]
        },
        "mentions": [],
    },
    ensure_ascii=False,
)
data = {
    "ssrData": {
        "publisherMeta": {
            "data": {
                "__type": "ru.yandex.zen.publishers.media.meta.output.PublicationPageMetaDataResponse",
                "publisher": {
                    "id": VT,
                    "name": "О Сибири с любовью!",
                    "nickname": {"raw": "vtruda", "normalized": "vtruda"},
                },
            }
        },
        "publicationData": {
            "publication": {
                "id": "6ad18de2a82a603e7d1838c8",
                "publisherId": VT,
                "addTime": int(k(2026, 10, 18, 12).timestamp() * 1000),
                "publishTime": int(k(2026, 10, 18, 12).timestamp() * 1000),
                "modificationTime": int(k(2026, 10, 18, 12, 5).timestamp() * 1000),
                "content": {"type": "article", "articleContent": {"contentState": state}},
            },
            "publicationStatistics": {"views": 46, "viewsTillEnd": 0, "pageViews": 46},
            "publisherSubscribersCount": {"publisherId": VT, "subscribersCount": 2823},
        },
    }
}
write(
    "dzen-article-medvedi.html",
    '<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8"/>'
    "<title>Медведи: карантин и новые меры | О Сибири с любовью! | Дзен</title>"
    '<meta name="robots" content="index, follow"/><meta property="og:type" content="article"/>'
    '<meta name="description" content="Статья автора «О Сибири с любовью!» в Дзене ✍: В Минусинском округе медведи продолжают выходить к домам."/>'
    '<meta property="og:title" content="Медведи: карантин и новые меры"/>'
    '<meta property="og:description" content="Статья автора «О Сибири с любовью!» в Дзене ✍: В Минусинском округе медведи продолжают выходить к домам."/>'
    '<meta property="og:url" content="https://dzen.ru/a/aTdzMedvedi01aBc"/></head>'
    '<body><div id="zen-root"></div><script nonce="test">window._data = '
    + json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    + ";</script></body></html>\n",
)

manifest = {
    "$comment": (
        "Записанные образцы ответов для SITES_SOURCE/DZEN_SOURCE=fixtures и тестов "
        "(adapters/replay.py). Разметка и структура — как в живых ответах 20.10.2026 "
        "(сайты — с сервера команды в РФ, Дзен — с ноутбука), тексты свои. Адрес не из списка — 404."
    ),
    "sites": ["vtruda.ru", "kvgazeta.ru", "angarka.info", "enisey.tv"],
    "channels": [VT, AP],
    "responses": [
        {
            "url": "https://www.vtruda.ru/rss/",
            "file": "vtruda-rss.xml",
            "type": "application/rss+xml; charset=UTF-8",
        },
        {
            "url": "https://vtruda.ru/news/medvedi-ne-ukhodyat/",
            "file": "vtruda-article-medvedi.html",
        },
        {
            "url": "https://vtruda.ru/news/medved-za-okolitsey/",
            "file": "vtruda-article-okolitsa.html",
        },
        {"prefix": "https://www.vtruda.ru/search/?q=", "file": "vtruda-search.html"},
        {
            "url": "https://www.kvgazeta.ru/rss/",
            "file": "kvgazeta-rss.xml",
            "type": "application/rss+xml; charset=UTF-8",
        },
        {"prefix": "https://www.kvgazeta.ru/search/?q=", "file": "kvgazeta-search.html"},
        {"url": "https://angarka.info/news/", "file": "angarka-news.html"},
        {"prefix": "https://angarka.info/search/?q=", "file": "angarka-search.html"},
        {
            "url": "https://angarka.info/news/eskrou-schyet-pomozhet-voplotit-mechtu-o-svoyem-dome/",
            "file": "angarka-article-eskrou.html",
        },
        {
            "url": "https://www.enisey.tv/rss.xml",
            "file": "enisey-rss.xml",
            "type": "text/xml; charset=UTF-8",
        },
        {
            "url": "https://dzen.ru/api/web/v1/channel?channel_name=vtruda&country_code=ru&lang=ru&referrer_place=layout",
            "file": "dzen-vtruda.json",
            "type": "application/json; charset=utf-8",
        },
        {
            "prefix": "https://dzen.ru/api/web/v1/channel-more?channel_name=vtruda",
            "file": "dzen-vtruda-more.json",
            "type": "application/json; charset=utf-8",
        },
        {
            "url": f"https://dzen.ru/api/web/v1/channel?channel_id={AP}&country_code=ru&lang=ru&referrer_place=layout",
            "file": "dzen-angarka.json",
            "type": "application/json; charset=utf-8",
        },
        {"url": "https://dzen.ru/a/aTdzMedvedi01aBc", "file": "dzen-article-medvedi.html"},
    ],
}
write("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
print("ok", sorted(p.name for p in OUT.iterdir()))
