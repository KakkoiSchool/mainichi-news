"""Install/uninstall scheduler entries (systemd user units / launchd LaunchAgent)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from importlib.resources import files
from pathlib import Path
from string import Template

LABEL = "dev.kakkoi.mainichi-news"


class InstallError(RuntimeError):
    pass


def template(name: str) -> Template:
    return Template((files("mainichi_news") / "templates" / name).read_text(encoding="utf-8"))


def workdir() -> Path:
    return Path.cwd()


def python_executable() -> str:
    return sys.executable


def exec_start() -> str:
    """Prefer the installed console script, else `python -m mainichi_news`."""
    script = shutil.which("mainichi-news")
    if script:
        return f"{script} run"
    return f"{python_executable()} -m mainichi_news run"


def systemd_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "systemd" / "user"


def launchd_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if path.suffix != ".plist":
        path.chmod(0o644)


def install_linux(enable: bool = True) -> list[Path]:
    if not shutil.which("systemctl"):
        raise InstallError("systemctl が見つからない（systemd 環境か確認）")
    target = systemd_dir()
    service = target / "mainichi-news.service"
    timer = target / "mainichi-news.timer"
    write_file(
        service,
        template("mainichi-news.service").substitute(
            workdir=workdir(), exec_start=exec_start()
        ),
    )
    write_file(timer, template("mainichi-news.timer").substitute())
    if enable:
        for args in (
            ["systemctl", "--user", "daemon-reload"],
            ["systemctl", "--user", "enable", "--now", "mainichi-news.timer"],
        ):
            done = subprocess.run(args, capture_output=True, text=True, check=False)
            if done.returncode != 0:
                raise InstallError(
                    f"{' '.join(args)} 失敗: {done.stderr.strip() or done.stdout.strip()}"
                )
    return [service, timer]


def uninstall_linux() -> list[Path]:
    target = systemd_dir()
    removed: list[Path] = []
    if shutil.which("systemctl"):
        subprocess.run(
            ["systemctl", "--user", "disable", "--now", "mainichi-news.timer"],
            capture_output=True,
            check=False,
        )
    for name in ("mainichi-news.timer", "mainichi-news.service"):
        path = target / name
        if path.exists():
            path.unlink()
            removed.append(path)
    if shutil.which("systemctl"):
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"], capture_output=True, check=False
        )
    return removed


def install_macos(enable: bool = True) -> list[Path]:
    logfile = Path.home() / "Library" / "Logs" / "mainichi-news.log"
    logfile.parent.mkdir(parents=True, exist_ok=True)
    target = launchd_dir() / f"{LABEL}.plist"
    write_file(
        target,
        template("dev.kakkoi.mainichi-news.plist").substitute(
            python=python_executable(),
            workdir=workdir(),
            logfile=logfile,
        ),
    )
    if enable:
        uid = os.getuid()
        done = subprocess.run(
            ["launchctl", "bootstrap", f"gui/{uid}", str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if done.returncode != 0:
            subprocess.run(
                ["launchctl", "load", "-w", str(target)],
                capture_output=True,
                check=False,
            )
    return [target]


def uninstall_macos() -> list[Path]:
    target = launchd_dir() / f"{LABEL}.plist"
    if not target.exists():
        return []
    uid = os.getuid()
    subprocess.run(
        ["launchctl", "bootout", f"gui/{uid}", str(target)],
        capture_output=True,
        check=False,
    )
    subprocess.run(["launchctl", "unload", str(target)], capture_output=True, check=False)
    target.unlink()
    return [target]


def install(enable: bool = True) -> list[Path]:
    if sys.platform == "darwin":
        return install_macos(enable)
    if sys.platform.startswith("linux"):
        return install_linux(enable)
    raise InstallError(f"未対応 OS: {sys.platform}（Windows は手動でタスク登録）")


def uninstall() -> list[Path]:
    if sys.platform == "darwin":
        return uninstall_macos()
    if sys.platform.startswith("linux"):
        return uninstall_linux()
    raise InstallError(f"未対応 OS: {sys.platform}")
