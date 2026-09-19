"""Ava's per-key privacy policy, as echoed on every API response.

Ava (≥ 0.4.6) returns `"ava": {"key", "private", "rag", "retained"}` on
/api/v1/messages and /api/v1/models. A private key gets no RAG and nothing it
sends is learned into Ava's knowledge base. The block is read per response
because the key's setting can change while a run is in progress.
"""
from __future__ import annotations

from avadex.ava_client import AvaError


class KeyNotPrivate(AvaError):
    """Raised under --require-private when Ava doesn't report the key private."""


def is_private(block) -> bool:
    """True only when Ava explicitly reports `private: true`. A missing block
    (older Ava) or any other value is not private: fail closed."""
    return isinstance(block, dict) and block.get("private") is True


class PolicyTracker:
    """The policy blocks seen during a run: the last one, and whether it ever
    changed (including appearing or disappearing) between requests."""

    def __init__(self):
        self.last: dict | None = None
        self.changed: bool = False
        self._seen = False

    def record(self, block) -> None:
        block = block if isinstance(block, dict) else None
        if self._seen and block != self.last:
            self.changed = True
        self.last = block
        self._seen = True
