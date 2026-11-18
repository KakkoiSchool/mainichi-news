"""Shared RSS helpers (stdlib only: urllib + ElementTree)."""

from __future__ import annotations

import html
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from ..config import DEFAULT_USER_AGENT

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_GOOGLE_SUFFIX_RE = re.compile(r"\s+[-–—]\s+[^-–—]{2,40}$")
_PAREN_SOURCE_RE = re.compile(r"[（(][^（）()]{2,20}(新聞|新報|テレビ|放送|通信|デジタル|日報|タイムズ)[）)]\s*$")


class FetchError(RuntimeError):
    """RSS fetch/parse failed."""


def fetch(url: str, timeout: float = 20.0, user_agent: str = DEFAULT_USER_AGENT) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
            "Accept-Language": "ja,en;q=0.7",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        raise FetchError(f"取得失敗 {url}: {exc}") from exc


def parse_feed(payload: bytes) -> ET.Element:
    try:
        return ET.fromstring(payload)
    except ET.ParseError as exc:
        raise FetchError(f"RSS の解析に失敗: {exc}") from exc


def strip_html(text: str) -> str:
    text = _TAG_RE.sub(" ", text or "")
    text = html.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def iter_items(root: ET.Element) -> list[ET.Element]:
    items = root.findall("./channel/item")
    if not items:
        items = root.findall(".//item")
    return items


def item_text(item: ET.Element, tag: str) -> str:
    return strip_html(item.findtext(tag) or "")


def item_source(item: ET.Element) -> str:
    node = item.find("source")
    if node is None:
        return ""
    return strip_html(node.text or "")


def clean_title(title: str, source: str = "") -> str:
    """Remove trailing media name that Google News appends."""
    title = _WS_RE.sub(" ", title).strip()
    if source:
        for sep in (" - ", " – ", " — ", " | "):
            suffix = f"{sep}{source}"
            if title.endswith(suffix):
                return title[: -len(suffix)].strip()
    title = _PAREN_SOURCE_RE.sub("", title).strip()
    if source and len(title) > len(source) + 4:
        title = _GOOGLE_SUFFIX_RE.sub("", title).strip()
    return title


def extract_link(item: ET.Element) -> str:
    link = (item.findtext("link") or "").strip()
    if link:
        return link
    guid = (item.findtext("guid") or "").strip()
    return guid if guid.startswith("http") else ""
