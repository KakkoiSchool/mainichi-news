"""Delivery backends."""

from __future__ import annotations

from typing import Protocol

from ..models import Digest


class Deliverer(Protocol):
    name: str

    def send(self, digest: Digest, subject: str, markdown: str, html: str) -> str:
        """Deliver and return a short description of what happened."""
        ...
