"""Data models shared across the pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class Article:
    """One RSS item."""

    title: str
    url: str
    source: str = ""
    published: datetime | None = None
    summary: str = ""
    query: str = ""
    key: str = ""


@dataclass
class Story:
    """A story as it appears in the digest."""

    title: str
    summary: str = ""
    why: str = ""
    url: str = ""
    source: str = ""


@dataclass
class Digest:
    """One day's issue."""

    day: date
    one_liner: str = ""
    top: list[Story] = field(default_factory=list)
    others: list[Story] = field(default_factory=list)
    numbers: list[str] = field(default_factory=list)
    degraded: bool = False
    article_count: int = 0

    @property
    def all_stories(self) -> list[Story]:
        return [*self.top, *self.others]

    @property
    def subject(self) -> str:
        weekday = "月火水木金土日"[self.day.weekday()]
        stamp = f"{self.day.month}/{self.day.day}({weekday})"
        head = f"{stamp} 島根"
        if self.one_liner:
            head = f"{head} — {self.one_liner}"
        return head
