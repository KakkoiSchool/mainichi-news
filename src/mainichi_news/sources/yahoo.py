"""Yahoo! News regional RSS (auxiliary, filtered by Shimane keywords)."""

from __future__ import annotations

from ..config import SourceConfig
from ..dedupe import make_key
from ..models import Article
from . import rss

SHIMANE_KEYWORDS = (
    "島根",
    "松江",
    "出雲",
    "浜田",
    "益田",
    "安来",
    "雲南",
    "大田",
    "江津",
    "隠岐",
    "奥出雲",
    "飯南",
    "邑南",
    "川本",
    "美郷",
    "津和野",
    "吉賀",
    "海士",
    "西ノ島",
    "知夫",
    "山陰",
)


def is_shimane(*texts: str) -> bool:
    blob = " ".join(texts)
    return any(k in blob for k in SHIMANE_KEYWORDS)


def fetch_articles(cfg: SourceConfig, log=None) -> list[Article]:
    try:
        root = rss.parse_feed(rss.fetch(cfg.yahoo_url, cfg.timeout, cfg.user_agent))
    except rss.FetchError as exc:
        if log:
            log.warning("yahoo: %s", exc)
        return []

    articles: list[Article] = []
    for item in rss.iter_items(root):
        title = rss.item_text(item, "title")
        link = rss.extract_link(item)
        if not title or not link:
            continue
        summary = rss.item_text(item, "description")
        if not is_shimane(title, summary):
            continue
        article = Article(
            title=rss.clean_title(title),
            url=link,
            source="Yahoo!ニュース",
            published=rss.parse_date(item.findtext("pubDate")),
            summary=summary[:400],
            query="yahoo-local",
        )
        article.key = make_key(title)
        articles.append(article)
    return articles
