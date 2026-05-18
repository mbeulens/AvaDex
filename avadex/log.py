"""Logging setup for AvaDex.

Always writes WARNING+ to stderr (with a '[warn]' / '[error]' prefix that
matches the existing AnsiRenderer style). When debug mode is on, also
writes DEBUG+ to ~/.local/state/avadex/debug.log with rotation.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional


DEFAULT_LOG_DIR = Path.home() / ".local" / "state" / "avadex"
DEFAULT_LOG_FILE = DEFAULT_LOG_DIR / "debug.log"


class _LevelPrefixFormatter(logging.Formatter):
    """Renders WARNING as '[warn]' and ERROR/CRITICAL as '[error]' to match
    AvaDex's existing stderr style."""
    def format(self, record: logging.LogRecord) -> str:
        if record.levelno >= logging.ERROR:
            prefix = "[error]"
        elif record.levelno >= logging.WARNING:
            prefix = "[warn]"
        else:
            prefix = f"[{record.levelname.lower()}]"
        record.msg = f"{prefix} {record.getMessage()}"
        record.args = ()
        return super().format(record)


class _DynamicStderrHandler(logging.StreamHandler):
    """StreamHandler that resolves sys.stderr at emit-time rather than
    setup-time, so pytest's capsys patching is captured in tests."""

    def __init__(self) -> None:
        # Pass a dummy stream; we override .stream dynamically.
        super().__init__(sys.stderr)

    @property  # type: ignore[override]
    def stream(self):  # type: ignore[override]
        return sys.stderr

    @stream.setter
    def stream(self, value) -> None:
        # logging.StreamHandler.__init__ sets self.stream; ignore it.
        pass


_CONFIGURED = False


def setup(debug: bool = False, log_file: Optional[Path] = None) -> None:
    """Configure root logger. Idempotent — safe to call multiple times."""
    global _CONFIGURED
    root = logging.getLogger("avadex")
    # Clear any previous handlers from a re-setup (mainly for tests)
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(logging.DEBUG if debug else logging.WARNING)
    root.propagate = False

    # Stderr handler — always present, WARNING+
    # _DynamicStderrHandler looks up sys.stderr at emit-time so pytest's
    # capsys patching of sys.stderr is captured correctly in tests.
    stderr_handler = _DynamicStderrHandler()
    stderr_handler.setLevel(logging.WARNING)
    stderr_handler.setFormatter(_LevelPrefixFormatter("%(message)s"))
    root.addHandler(stderr_handler)

    if debug:
        path = log_file or DEFAULT_LOG_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=1_000_000, backupCount=5, encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
        ))
        root.addHandler(file_handler)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Get a child logger under the 'avadex' tree. If setup() hasn't run
    yet, run a default (non-debug) setup so library code can log safely
    even when called outside the CLI entry point."""
    if not _CONFIGURED:
        setup(debug=False)
    return logging.getLogger(f"avadex.{name}")
