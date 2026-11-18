"""Google News RSS source (primary)."""

from __future__ import annotations

import urllib.parse

from ..config import SourceConfig
from ..dedupe import make_key, normalize
from ..models import Article
from . import rss

BASE = "https://news.google.com/rss/search"


def feed_url(query: str) -> str:
    params = {"q": query, "hl": "ja", "gl": "JP", "ceid": "JP:ja"}
    return f"{BASE}?{urllib.parse.urlencode(params)}"


def fetch_articles(
    cfg: SourceConfig, log=None
) -> list[Article]:
    """Fetch every configured query and return raw (non-deduped) articles."""
    articles: list[Article] = []
    for query in cfg.queries:
        url = feed_url(query)
        try:
            root = rss.parse_feed(rss.fetch(url, cfg.timeout, cfg.user_agent))
        except rss.FetchError as exc:
            if log:
                log.warning("google-news: %s", exc)
            continue
        count = 0
        for item in rss.iter_items(root):
            source = rss.item_source(item)
            raw_title = rss.item_text(item, "title")
            title = rss.clean_title(raw_title, source)
            link = rss.extract_link(item)
            if not title or not link:
                continue
            summary = rss.item_text(item, "description")
            for prefix in (raw_title, title):
                if prefix and summary.startswith(prefix):
                    summary = summary[len(prefix) :].strip()
                    break
            # Google News descriptions are just the title + media name: drop them.
            if normalize(summary) == normalize(source) or len(summary) < 15:
                summary = ""
            article = Article(
                title=title,
                url=link,
                source=source or "Google ニュース",
                published=rss.parse_date(item.findtext("pubDate")),
                summary=summary[:400],
                query=query,
            )
            article.key = make_key(title)
            articles.append(article)
            count += 1
            if count >= cfg.max_per_query:
                break
    return articles
