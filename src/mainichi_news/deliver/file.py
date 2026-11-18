"""Always-on delivery: write digest/YYYY-MM-DD.md."""

from __future__ import annotations

from pathlib import Path

from ..models import Digest


class FileDeliverer:
    name = "file"

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def path_for(self, digest: Digest) -> Path:
        return self.directory / f"{digest.day.isoformat()}.md"

    def send(self, digest: Digest, subject: str, markdown: str, html: str) -> str:
        path = self.path_for(digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown, encoding="utf-8")
        return f"file:{path}"
