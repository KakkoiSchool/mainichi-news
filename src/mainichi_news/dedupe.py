"""Title normalisation and duplicate removal."""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher

from .models import Article

_STRIP_PREFIX_RE = re.compile(r"^(【[^】]{1,8}】|\[[^\]]{1,8}\])\s*")
_PUNCT_RE = re.compile(r"[\s\u3000・、。,.!?！？:：;；「」『』（）()\[\]【】〈〉《》\"'“”‘’…‥\-—–―~〜/\\|_*#]+")
_QUOTE_RE = re.compile(r"「[^」]*」|『[^』]*』")
_TRAILING_PAREN_RE = re.compile(r"[（(]([^（）()]{1,24})[）)]\s*$")
_TRAILING_PIPE_RE = re.compile(r"\s*[|｜]\s*[^|｜]{2,40}$")
_PAGE_RE = re.compile(r"[（(\[]?(全)?\d{1,2}\s*ページ[）)\]]?\s*$")
_MEDIA_HINT_RE = re.compile(
    r"新聞|放送|テレビ|ニュース|通信|デジタル|タイムズ|日報|ページ|島根|山陰|NHK|TSK|BSS|TBS|Yahoo|日テレ|フジ|テレ朝"
)

# Media names that may appear as a title suffix even without the RSS <source>.
_MEDIA_SUFFIXES = (
    "山陰中央新報デジタル",
    "山陰中央新報",
    "NHK",
    "日本海テレビ",
    "TSKさんいん中央テレビ",
    "TSK",
    "BSS山陰放送",
    "BSS",
    "毎日新聞",
    "読売新聞",
    "朝日新聞",
    "産経新聞",
    "中国新聞",
    "時事通信",
    "共同通信",
    "日テレNEWS",
    "テレビ朝日",
    "TBS NEWS DIG",
    "FNNプライムオンライン",
    "Yahoo!ニュース",
    "島根県",
)


def _strip_media_tail(text: str) -> str:
    """Drop trailing `（島根）` / `| BSSニュース | BSS山陰放送` / `(1ページ)`."""
    previous = None
    while previous != text:
        previous = text
        text = _PAGE_RE.sub("", text).strip()
        match = _TRAILING_PIPE_RE.search(text)
        if match and _MEDIA_HINT_RE.search(match.group(0)):
            text = text[: match.start()].strip()
        match = _TRAILING_PAREN_RE.search(text)
        if match and _MEDIA_HINT_RE.search(match.group(1)):
            text = text[: match.start()].strip()
    return text


def normalize(text: str) -> str:
    text = _strip_media_tail(unicodedata.normalize("NFKC", text or ""))
    text = _STRIP_PREFIX_RE.sub("", text)
    text = _QUOTE_RE.sub("", text)
    text = _PUNCT_RE.sub("", text)
    return text.lower()


def make_key(title: str) -> str:
    """Stable key used to detect the same story from different queries."""
    key = normalize(title)
    for suffix in _MEDIA_SUFFIXES:
        n = normalize(suffix)
        if len(key) > len(n) + 3 and key.endswith(n):
            key = key[: -len(n)]
    return key


def _similar(a: str, b: str) -> bool:
    if a == b:
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) < 8:
        return False
    if short in long_ and len(short) / len(long_) >= 0.6:
        return True
    if len(short) < 14:
        return False
    return SequenceMatcher(None, a, b).ratio() >= 0.82


def _recency_key(article: Article) -> float:
    if article.published is None:
        return float("-inf")
    return article.published.timestamp()


def dedupe(articles: list[Article]) -> list[Article]:
    """Drop duplicate stories, keeping the newest (then most descriptive) item."""
    ordered = sorted(articles, key=_recency_key, reverse=True)
    kept: list[Article] = []
    for article in ordered:
        key = article.key or make_key(article.title)
        duplicate = False
        for existing in kept:
            if key and (key == existing.key or _similar(key, existing.key)):
                duplicate = True
                break
        if not duplicate:
            article.key = key
            kept.append(article)
    return kept


def within_window(
    articles: list[Article], hours: int, now: datetime | None = None
) -> list[Article]:
    """Keep items published within `hours`. Undated items are kept."""
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(hours=hours)
    result: list[Article] = []
    for article in articles:
        if article.published is None or article.published >= cutoff:
            result.append(article)
    return result
