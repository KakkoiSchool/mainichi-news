"""Install/uninstall scheduler entries.

Artifacts and activation are separated so every platform's scheduler file can be
generated and validated from any OS (`mainichi-news install --print --platform ...`).

- Linux   : systemd user service + timer (06:00 calendar, 90s after boot, Persistent)
- macOS   : launchd LaunchAgent (RunAtLoad + StartCalendarInterval 06:00)
- Windows : Task Scheduler task (90s after logon + daily 06:00, StartWhenAvailable)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from importlib.resources import files
from pathlib import Path
from string import Template

LABEL = "dev.kakkoi.mainichi-news"
TASK_NAME = "mainichi-news"


class InstallError(RuntimeError):
    pass


@dataclass(frozen=True)
class Artifact:
    """A scheduler file to write (path + rendered content)."""

    path: Path
    content: str
    kind: str  # "systemd" | "launchd" | "task"


def template(name: str) -> Template:
    return Template((files("mainichi_news") / "templates" / name).read_text(encoding="utf-8"))


def platform_key(platform: str | None = None) -> str:
    value = platform or sys.platform
    if value.startswith("linux"):
        return "linux"
    if value in {"darwin", "macos", "osx"}:
        return "macos"
    if value.startswith("win"):
        return "windows"
    raise InstallError(f"未対応 OS: {value}")


def exec_start(python: str | None = None) -> str:
    """Prefer the installed console script, else `python -m mainichi_news`."""
    script = shutil.which("mainichi-news")
    if script and not python:
        return f"{script} run"
    return f"{python or sys.executable} -m mainichi_news run"


def systemd_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "systemd" / "user"


def launchd_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def windows_task_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return base / "mainichi-news" / "task.xml"


def windows_start_boundary(day: datetime | None = None) -> str:
    day = day or datetime.now()
    start = day.replace(hour=6, minute=0, second=0, microsecond=0)
    if start <= day:
        start += timedelta(days=1)
    return start.strftime("%Y-%m-%dT%H:%M:%S")


def artifacts(
    platform: str | None = None,
    *,
    workdir: Path | None = None,
    python: str | None = None,
    logfile: Path | None = None,
) -> list[Artifact]:
    """Render every scheduler file for `platform` without touching the system."""
    key = platform_key(platform)
    wd = Path(workdir or Path.cwd()).resolve()
    py = python or sys.executable

    if key == "linux":
        target = systemd_dir()
        return [
            Artifact(
                target / "mainichi-news.service",
                template("mainichi-news.service").substitute(
                    workdir=wd, exec_start=exec_start(python) if python else exec_start()
                ),
                "systemd",
            ),
            Artifact(
                target / "mainichi-news.timer",
                template("mainichi-news.timer").substitute(),
                "systemd",
            ),
        ]

    if key == "macos":
        log = logfile or Path.home() / "Library" / "Logs" / "mainichi-news.log"
        return [
            Artifact(
                launchd_dir() / f"{LABEL}.plist",
                template("dev.kakkoi.mainichi-news.plist").substitute(
                    python=py, workdir=wd, logfile=log
                ),
                "launchd",
            )
        ]

    return [
        Artifact(
            windows_task_path(),
            template("mainichi-news-task.xml").substitute(
                python=py, workdir=wd, start_boundary=windows_start_boundary()
            ),
            "task",
        )
    ]


def write_artifact(artifact: Artifact) -> None:
    artifact.path.parent.mkdir(parents=True, exist_ok=True)
    # Task Scheduler XML must be UTF-16 (its declaration says so).
    encoding = "utf-16" if artifact.kind == "task" else "utf-8"
    artifact.path.write_text(artifact.content, encoding=encoding)
    if artifact.kind != "launchd":
        artifact.path.chmod(0o644)


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=False, timeout=120)


def activate(platform: str | None = None, *, dry_run: bool = False) -> None:
    key = platform_key(platform)
    if dry_run:
        return
    if key == "linux":
        if not shutil.which("systemctl"):
            raise InstallError("systemctl が見つからない（systemd 環境か確認）")
        for args in (
            ["systemctl", "--user", "daemon-reload"],
            ["systemctl", "--user", "enable", "--now", "mainichi-news.timer"],
        ):
            done = _run(args)
            if done.returncode != 0:
                raise InstallError(f"{' '.join(args)} 失敗: {done.stderr.strip()}")
    elif key == "macos":
        target = launchd_dir() / f"{LABEL}.plist"
        done = _run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(target)])
        if done.returncode != 0:
            _run(["launchctl", "load", "-w", str(target)])
    else:
        task_file = windows_task_path()
        done = _run(["schtasks", "/Create", "/TN", TASK_NAME, "/XML", str(task_file), "/F"])
        if done.returncode != 0:
            raise InstallError(f"schtasks 失敗: {done.stderr.strip() or done.stdout.strip()}")


def deactivate(platform: str | None = None) -> None:
    key = platform_key(platform)
    if key == "linux":
        if shutil.which("systemctl"):
            _run(["systemctl", "--user", "disable", "--now", "mainichi-news.timer"])
            _run(["systemctl", "--user", "daemon-reload"])
    elif key == "macos":
        target = launchd_dir() / f"{LABEL}.plist"
        _run(["launchctl", "bootout", f"gui/{os.getuid()}", str(target)])
        _run(["launchctl", "unload", str(target)])
    else:
        _run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])


def install(enable: bool = True, platform: str | None = None) -> list[Path]:
    key = platform_key(platform)
    rendered = artifacts(key)
    for artifact in rendered:
        write_artifact(artifact)
    activate(key, dry_run=not enable)
    return [a.path for a in rendered]


def uninstall(platform: str | None = None) -> list[Path]:
    key = platform_key(platform)
    deactivate(key)
    removed: list[Path] = []
    for artifact in artifacts(key):
        if artifact.path.exists():
            artifact.path.unlink()
            removed.append(artifact.path)
    return removed
