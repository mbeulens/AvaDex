"""TTY-only spinner shown during the blocking Ava request.

In non-TTY contexts (tests, piped output, NO_COLOR set) the spinner is a
no-op so log output stays clean.
"""
from __future__ import annotations

import os
import sys
import threading
from typing import Optional


class Spinner:
    FRAMES = "|/-\\"
    INTERVAL_S = 0.1

    def __init__(self, label: str = "thinking"):
        self.label = label
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _enabled(self) -> bool:
        if os.environ.get("NO_COLOR", ""):
            return False
        return sys.stderr.isatty()

    def start(self) -> None:
        if not self._enabled():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        i = 0
        while not self._stop.is_set():
            frame = self.FRAMES[i % len(self.FRAMES)]
            try:
                sys.stderr.write(f"\r{frame} {self.label}...")
                sys.stderr.flush()
            except (OSError, ValueError):
                # stderr can close mid-write under unusual teardown
                return
            self._stop.wait(self.INTERVAL_S)
            i += 1

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join(timeout=1.0)
        self._thread = None
        # Clear the spinner line (label + frame + dots + safety margin)
        clear_width = len(self.label) + 6
        try:
            sys.stderr.write("\r" + " " * clear_width + "\r")
            sys.stderr.flush()
        except (OSError, ValueError):
            pass

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.stop()
        return False
