#!/usr/bin/env python3
"""Real scheduler firing test for Linux / macOS / Windows.

Two checks per platform:

  fire   : schedule a harmless marker command a few seconds ahead through the
           OS scheduler and wait for it to actually run.
  digest : run `mainichi-news run` through the OS scheduler with a temp
           config/state, then fire again and assert the daily guard is a no-op.

Exit codes: 0 = pass, 1 = fail, 77 = skipped (no usable scheduler session).

Usage:
  python scripts/firing_test.py                 # fire + digest, current OS
  python scripts/firing_test.py --mode fire     # no network needed
  python scripts/firing_test.py --yes           # required for --mode digest
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKIP = 77
STUB = (
    "import datetime, pathlib, sys; "
    "pathlib.Path(sys.argv[1]).write_text(datetime.datetime.now().isoformat())"
)


class Skip(Exception):
    pass


class Fail(Exception):
    pass


def log(message: str) -> None:
    print(f"[firing] {message}", flush=True)


def run(args: list[str], *, timeout: float = 120, env: dict | None = None) -> subprocess.CompletedProcess:
    merged = {**os.environ, **(env or {})}
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=merged, check=False)


def wait_for(predicate, timeout: float, interval: float = 0.5, what: str = "condition") -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise Fail(f"timeout ({timeout:.0f}s) waiting for {what}")


def temp_digest_env(root: Path) -> tuple[Path, dict[str, str]]:
    """Temp config + state so tests never touch the real digest/history."""
    cfg = root / "config.toml"
    cfg.write_text(
        textwrap.dedent(
            f"""
            digest_dir = "{root / 'digest'}"

            [archive]
            enabled = false

            [deliver]
            to = ""
            """
        ),
        encoding="utf-8",
    )
    env = {
        "MAINICHI_NEWS_CONFIG": str(cfg),
        "MAINICHI_NEWS_ENV": str(root / "no.env"),
        "XDG_STATE_HOME": str(root / "state"),
        "XDG_CONFIG_HOME": str(root / "xdg"),
    }
    env.pop("DEEPSEEK_API_KEY", None)
    return cfg, env


def digest_path(root: Path) -> Path:
    return root / "digest" / f"{datetime.now().date().isoformat()}.md"


def state_path(env: dict[str, str]) -> Path:
    return Path(env["XDG_STATE_HOME"]) / "mainichi-news" / "last-run"


# --------------------------------------------------------------------------- linux


def _systemd_user_ok() -> bool:
    if not shutil.which("systemd-run") or not shutil.which("systemctl"):
        return False
    done = run(["systemctl", "--user", "is-system-running"], timeout=15)
    return done.returncode == 0


def linux_fire(root: Path) -> None:
    if not _systemd_user_ok():
        raise Skip("systemd --user が使えない")
    marker = root / "fired"
    unit = f"mn-e2e-fire-{os.getpid()}"
    done = run(
        [
            "systemd-run", "--user", "--collect", f"--unit={unit}",
            "--on-active=3", "--property=Type=oneshot",
            sys.executable, "-c", STUB, str(marker),
        ],
        timeout=30,
    )
    if done.returncode != 0:
        raise Skip(f"systemd-run 失敗: {done.stderr.strip()}")
    wait_for(marker.exists, timeout=60, what="transient timer to fire")
    log(f"linux: timer fired -> {marker}")


def linux_digest(root: Path, env: dict[str, str]) -> None:
    if not _systemd_user_ok():
        raise Skip("systemd --user が使えない")
    unit = f"mn-e2e-digest-{os.getpid()}"
    args = [
        "systemd-run", "--user", "--wait", "--collect", f"--unit={unit}",
        "--property=Type=oneshot", f"--property=WorkingDirectory={REPO}",
    ]
    for key, value in env.items():
        args += [f"--setenv={key}={value}"]
    args += [sys.executable, "-m", "mainichi_news", "run"]
    done = run(args, timeout=300)
    if done.returncode != 0:
        raise Fail(f"systemd service failed rc={done.returncode}: {done.stderr.strip()[-500:]}")
    path = digest_path(root)
    wait_for(path.exists, timeout=10, what="digest file")
    first = state_path(env).read_text(encoding="utf-8")
    log(f"linux: digest written under systemd -> {path}")

    done = run(args, timeout=300)
    if done.returncode != 0:
        raise Fail("second run failed")
    second = state_path(env).read_text(encoding="utf-8")
    if first != second:
        raise Fail("daily guard did not prevent a second digest")
    log("linux: second fire was a no-op (state unchanged)")


# --------------------------------------------------------------------------- macos


def _macos_bootstrap(plist: Path) -> None:
    uid = os.getuid()
    done = run(["launchctl", "bootstrap", f"gui/{uid}", str(plist)], timeout=60)
    if done.returncode == 0:
        return
    done = run(["launchctl", "load", "-w", str(plist)], timeout=60)
    if done.returncode != 0:
        raise Skip(f"launchctl bootstrap/load 不可: {done.stderr.strip()}")


def _macos_bootout(plist: Path) -> None:
    uid = os.getuid()
    run(["launchctl", "bootout", f"gui/{uid}", str(plist)], timeout=60)
    run(["launchctl", "unload", str(plist)], timeout=60)


def macos_plist(label: str, program: list[str], *, env: dict[str, str], workdir: Path, logfile: Path) -> Path:
    import plistlib

    data = {
        "Label": label,
        "ProgramArguments": program,
        "WorkingDirectory": str(workdir),
        "StartInterval": 5,
        "RunAtLoad": False,
        "StandardOutPath": str(logfile),
        "StandardErrorPath": str(logfile),
        "ProcessType": "Background",
    }
    if env:
        data["EnvironmentVariables"] = env
    path = Path(tempfile.mkdtemp(prefix="mn-e2e-")) / f"{label}.plist"
    path.write_bytes(plistlib.dumps(data))
    return path


def macos_fire(root: Path) -> None:
    if not shutil.which("launchctl"):
        raise Skip("launchctl が無い")
    marker = root / "fired"
    plist = macos_plist(
        f"dev.kakkoi.mn.e2e.fire.{os.getpid()}",
        [sys.executable, "-c", STUB, str(marker)],
        env={},
        workdir=REPO,
        logfile=root / "launchd-fire.log",
    )
    _macos_bootstrap(plist)
    try:
        wait_for(marker.exists, timeout=90, what="launchd StartInterval to fire")
    finally:
        _macos_bootout(plist)
    log(f"macos: launchd fired -> {marker}")


def macos_digest(root: Path, env: dict[str, str]) -> None:
    if not shutil.which("launchctl"):
        raise Skip("launchctl が無い")
    plist = macos_plist(
        f"dev.kakkoi.mn.e2e.digest.{os.getpid()}",
        [sys.executable, "-m", "mainichi_news", "run"],
        env=env,
        workdir=REPO,
        logfile=root / "launchd-digest.log",
    )
    _macos_bootstrap(plist)
    try:
        path = digest_path(root)
        wait_for(path.exists, timeout=180, what="digest file from launchd")
        first = state_path(env).read_text(encoding="utf-8")
        time.sleep(12)  # StartInterval=5 -> at least two more fires
        second = state_path(env).read_text(encoding="utf-8")
        if first != second:
            raise Fail("daily guard did not prevent a second digest")
    finally:
        _macos_bootout(plist)
    log(f"macos: digest written under launchd -> {path}")
    log("macos: repeated fires were no-ops (state unchanged)")


# --------------------------------------------------------------------------- windows


def _schtasks() -> str:
    found = shutil.which("schtasks")
    if not found:
        raise Skip("schtasks が無い")
    return found


def windows_fire(root: Path) -> None:
    schtasks = _schtasks()
    name = f"mn-e2e-fire-{os.getpid()}"
    marker = root / "fired"
    wrapper = root / "fire.cmd"
    wrapper.write_text(f'@echo off\r\n"{sys.executable}" -c "{STUB}" "{marker}"\r\n', encoding="utf-8")
    start = (datetime.now() + timedelta(minutes=1)).strftime("%H:%M")
    created = run([schtasks, "/Create", "/TN", name, "/SC", "ONCE", "/ST", start,
                   "/TR", f'"{wrapper}"', "/F"], timeout=60)
    if created.returncode != 0:
        raise Skip(f"schtasks /Create 不可: {created.stderr.strip()}")
    try:
        wait_for(marker.exists, timeout=180, what="Task Scheduler ONCE trigger")
    finally:
        run([schtasks, "/Delete", "/TN", name, "/F"], timeout=60)
    log(f"windows: Task Scheduler fired -> {marker}")


def windows_digest(root: Path, env: dict[str, str]) -> None:
    schtasks = _schtasks()
    name = f"mn-e2e-digest-{os.getpid()}"
    wrapper = root / "digest.cmd"
    sets = "".join(f"set {k}={v}\r\n" for k, v in env.items())
    wrapper.write_text(
        f'@echo off\r\n{sets}"{sys.executable}" -m mainichi_news run\r\n',
        encoding="utf-8",
    )
    start = (datetime.now() + timedelta(minutes=1)).strftime("%H:%M")
    created = run([schtasks, "/Create", "/TN", name, "/SC", "ONCE", "/ST", start,
                   "/TR", f'"{wrapper}"', "/F"], timeout=60)
    if created.returncode != 0:
        raise Skip(f"schtasks /Create 不可: {created.stderr.strip()}")
    try:
        path = digest_path(root)
        wait_for(path.exists, timeout=300, what="digest file from Task Scheduler")
        first = state_path(env).read_text(encoding="utf-8")
        done = run([schtasks, "/Run", "/TN", name], timeout=60)
        if done.returncode != 0:
            raise Fail(f"schtasks /Run failed: {done.stderr.strip()}")
        time.sleep(10)
        second = state_path(env).read_text(encoding="utf-8")
        if first != second:
            raise Fail("daily guard did not prevent a second digest")
    finally:
        run([schtasks, "/Delete", "/TN", name, "/F"], timeout=60)
    log(f"windows: digest written under Task Scheduler -> {path}")
    log("windows: second run was a no-op (state unchanged)")


# --------------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["fire", "digest", "all"], default="all")
    parser.add_argument("--yes", action="store_true", help="schedule real OS entries")
    parser.add_argument("--keep", action="store_true", help="keep temp dir")
    args = parser.parse_args(argv)

    platform = "linux" if sys.platform.startswith("linux") else "macos" if sys.platform == "darwin" else "windows" if sys.platform.startswith("win") else None
    if not platform:
        print(f"[firing] SKIP unsupported platform: {sys.platform}")
        return SKIP

    root = Path(tempfile.mkdtemp(prefix="mn-e2e-"))
    _, env = temp_digest_env(root)
    log(f"{platform}: temp dir {root}")

    modes = ["fire", "digest"] if args.mode == "all" else [args.mode]
    if "digest" in modes and not args.yes:
        log("--mode digest は実スケジューラに登録する。/Create 系を避けるには --mode fire か --yes")
        return 2

    try:
        for mode in modes:
            log(f"{platform}: === {mode} ===")
            if mode == "fire":
                {"linux": linux_fire, "macos": macos_fire, "windows": windows_fire}[platform](root)
            else:
                {"linux": linux_digest, "macos": macos_digest, "windows": windows_digest}[platform](root, env)
    except Skip as exc:
        log(f"{platform}: SKIP {exc}")
        return SKIP
    except Fail as exc:
        log(f"{platform}: FAIL {exc}")
        return 1
    except subprocess.TimeoutExpired as exc:
        log(f"{platform}: FAIL timeout: {exc}")
        return 1
    finally:
        if args.keep:
            log(f"kept temp dir: {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)

    log(f"{platform}: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
