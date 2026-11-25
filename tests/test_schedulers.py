"""Scheduler artifact tests: Linux / macOS / Windows.

These do not need the target OS: every scheduler file is rendered by
`mainichi_news.install.artifacts(platform)` and validated by parsing it.
Actual firing is covered by scripts/firing_test.py (runs the real scheduler).
"""

from __future__ import annotations

import configparser
import plistlib
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import pytest

from mainichi_news.install import (
    TASK_NAME,
    Artifact,
    InstallError,
    artifacts,
    exec_start,
    install,
    platform_key,
    windows_start_boundary,
    write_artifact,
)

# install() resolves the workdir, so Windows adds a drive letter (D:\\srv\\...)
WD = Path("/srv/mainichi-news").resolve()
PY = "/srv/mainichi-news/.venv/bin/python"
NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


def render(platform: str) -> list[Artifact]:
    return artifacts(platform, workdir=WD, python=PY)


def test_platform_key_mapping():
    assert platform_key("linux") == "linux"
    assert platform_key("linux2") == "linux"
    assert platform_key("darwin") == "macos"
    assert platform_key("win32") == "windows"
    with pytest.raises(InstallError):
        platform_key("plan9")


def test_exec_start_uses_explicit_python():
    assert exec_start(PY) == f"{PY} -m mainichi_news run"


def test_linux_artifacts_parse():
    service, timer = render("linux")
    assert service.path.name == "mainichi-news.service"
    assert timer.path.name == "mainichi-news.timer"

    parser = configparser.ConfigParser(strict=False)
    parser.read_string(service.content + "\n" + timer.content)
    assert parser["Service"]["Type"] == "oneshot"
    assert parser["Service"]["WorkingDirectory"] == str(WD)
    assert parser["Service"]["ExecStart"] == f"{PY} -m mainichi_news run"
    assert parser["Timer"]["OnCalendar"] == "*-*-* 06:00:00"
    assert parser["Timer"]["OnBootSec"] == "90s"
    assert parser["Timer"]["Persistent"] == "true"
    assert parser["Timer"]["Unit"] == "mainichi-news.service"


def test_macos_artifacts_parse():
    (plist,) = render("macos")
    assert plist.path.name == "dev.kakkoi.mainichi-news.plist"
    data = plistlib.loads(plist.content.encode("utf-8"))
    assert data["Label"] == "dev.kakkoi.mainichi-news"
    assert data["ProgramArguments"] == [PY, "-m", "mainichi_news", "run"]
    assert data["WorkingDirectory"] == str(WD)
    assert data["RunAtLoad"] is True
    assert data["StartCalendarInterval"] == {"Hour": 6, "Minute": 0}
    assert data["StandardErrorPath"].endswith("mainichi-news.log")


def test_windows_artifacts_parse():
    (task,) = render("windows")
    assert task.path.name == "task.xml"
    root = ET.fromstring(task.content)

    assert root.findtext(".//t:RegistrationInfo/t:URI", namespaces=NS) == f"\\{TASK_NAME}"

    logon = root.find(".//t:Triggers/t:LogonTrigger", NS)
    assert logon.findtext("t:Enabled", namespaces=NS) == "true"
    assert logon.findtext("t:Delay", namespaces=NS) == "PT90S"

    calendar = root.find(".//t:Triggers/t:CalendarTrigger", NS)
    start = calendar.findtext("t:StartBoundary", namespaces=NS)
    assert start.endswith("T06:00:00")
    assert calendar.findtext(".//t:DaysInterval", namespaces=NS) == "1"

    settings = root.find(".//t:Settings", NS)
    assert settings.findtext("t:StartWhenAvailable", namespaces=NS) == "true"
    assert settings.findtext("t:MultipleInstancesPolicy", namespaces=NS) == "IgnoreNew"
    assert settings.findtext("t:DisallowStartIfOnBatteries", namespaces=NS) == "false"

    assert root.findtext(".//t:Actions/t:Exec/t:Command", namespaces=NS) == PY
    assert root.findtext(".//t:Actions/t:Exec/t:Arguments", namespaces=NS) == "-m mainichi_news run"
    assert root.findtext(".//t:Actions/t:Exec/t:WorkingDirectory", namespaces=NS) == str(WD)


def test_unknown_platform_not_rendered():
    with pytest.raises(InstallError):
        artifacts("plan9", workdir=WD, python=PY)


def test_windows_start_boundary_next_six_am():
    late = datetime(2026, 11, 18, 23, 0, 0)
    assert windows_start_boundary(late) == "2026-11-19T06:00:00"
    early = datetime(2026, 11, 18, 5, 0, 0)
    assert windows_start_boundary(early) == "2026-11-18T06:00:00"


def test_write_task_artifact_is_utf16(tmp_path):
    target = tmp_path / "task.xml"
    artifact = Artifact(target, render("windows")[0].content, "task")
    write_artifact(artifact)
    raw = target.read_bytes()
    assert raw.startswith(b"\xff\xfe") or raw.startswith(b"\xef\xbb\xbf") is False
    parsed = ET.fromstring(raw)
    assert parsed.tag.endswith("Task")


def test_install_writes_only_target_platform_files(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    paths = install(enable=False, platform="linux")
    assert {p.name for p in paths} == {"mainichi-news.service", "mainichi-news.timer"}
    for path in paths:
        assert path.is_file()
    # no macOS / Windows artifacts on a linux install
    assert not (tmp_path / "cfg" / "systemd" / "user" / "task.xml").exists()
    assert not (tmp_path / "Library").exists()


def test_cli_install_print_does_not_write(tmp_path, monkeypatch, capsys):
    from mainichi_news.cli import main

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    code = main(["--quiet", "install", "--print", "--platform", "windows"])
    out = capsys.readouterr().out
    assert code == 0
    assert "LogonTrigger" in out
    assert "CalendarTrigger" in out
    assert not (tmp_path / "cfg").exists()


def test_cli_install_print_all_platforms(tmp_path, monkeypatch, capsys):
    from mainichi_news.cli import main

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    for platform, marker in (
        ("linux", "OnCalendar"),
        ("macos", "StartCalendarInterval"),
        ("windows", "StartWhenAvailable"),
    ):
        assert main(["--quiet", "install", "--print", "--platform", platform]) == 0
        assert marker in capsys.readouterr().out
