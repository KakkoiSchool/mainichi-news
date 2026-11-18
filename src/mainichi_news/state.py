"""Idempotency guard: one digest per day, retryable on failure."""

from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path

APP_NAME = "mainichi-news"


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state"
    return Path(base) / APP_NAME


def last_run_path() -> Path:
    override = os.environ.get("MAINICHI_NEWS_STATE")
    if override:
        return Path(override).expanduser()
    return state_dir() / "last-run"


def last_run() -> date | None:
    path = last_run_path()
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        return date.fromisoformat(raw.splitlines()[0].strip())
    except (ValueError, IndexError):
        return None


def last_run_info() -> dict[str, str]:
    path = last_run_path()
    info: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines()[1:]:
            if "=" in line:
                key, _, value = line.partition("=")
                info[key.strip()] = value.strip()
    except OSError:
        pass
    return info


def is_done(day: date) -> bool:
    return last_run() == day


def mark_done(day: date, *, articles: int = 0, delivered: str = "") -> None:
    path = last_run_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    lines = [
        day.isoformat(),
        f"finished_at={datetime.now().isoformat(timespec='seconds')}",
        f"articles={articles}",
        f"delivered={delivered}",
    ]
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def clear() -> None:
    try:
        last_run_path().unlink()
    except FileNotFoundError:
        pass
