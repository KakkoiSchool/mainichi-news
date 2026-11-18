"""Commit the digest to git (optional push). Never fatal."""

from __future__ import annotations

import logging
import subprocess
from datetime import date
from pathlib import Path

from .config import Config

log = logging.getLogger(__name__)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def archive_digest(cfg: Config, day: date) -> bool:
    repo = Path(cfg.digest_dir).resolve().parent
    if not (repo / ".git").exists():
        log.info("git リポジトリではないためアーカイブしない: %s", repo)
        return False

    rel = (Path(cfg.digest_dir).resolve() / f"{day.isoformat()}.md").relative_to(repo)
    added = _git(repo, "add", str(rel))
    if added.returncode != 0:
        log.warning("git add 失敗: %s", added.stderr.strip())
        return False

    if _git(repo, "diff", "--cached", "--quiet").returncode == 0:
        log.info("アーカイブに差分なし: %s", rel)
        return True

    committed = _git(repo, "commit", "-m", f"digest: {day.isoformat()}", "--", str(rel))
    if committed.returncode != 0:
        log.warning("git commit 失敗: %s", committed.stderr.strip())
        return False
    log.info("アーカイブを commit: %s", rel)

    if not cfg.archive.push:
        return True

    args = ["push"]
    if cfg.archive.remote:
        args.append(cfg.archive.remote)
    if cfg.archive.branch:
        args.append(cfg.archive.branch)
    pushed = _git(repo, *args)
    if pushed.returncode != 0:
        log.warning("git push 失敗（commit は残った）: %s", pushed.stderr.strip())
        return False
    log.info("アーカイブを push した")
    return True
