import sys
import os
import time
import pytest
from avadex.spinner import Spinner


def test_spinner_no_op_when_not_tty(capsys, monkeypatch):
    """In test capsys (not a TTY) the spinner does nothing visible."""
    monkeypatch.setattr(sys.stderr, "isatty", lambda: False)
    sp = Spinner(label="test")
    sp.start()
    time.sleep(0.2)
    sp.stop()
    captured = capsys.readouterr()
    # No spinner frames written
    assert "|" not in captured.err
    assert "thinking" not in captured.err


def test_spinner_no_op_when_no_color(capsys, monkeypatch):
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    monkeypatch.setenv("NO_COLOR", "1")
    sp = Spinner(label="x")
    sp.start()
    time.sleep(0.2)
    sp.stop()
    captured = capsys.readouterr()
    assert "|" not in captured.err


def test_spinner_runs_when_tty(capsys, monkeypatch):
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    monkeypatch.delenv("NO_COLOR", raising=False)
    sp = Spinner(label="thinking")
    sp.start()
    # Give the daemon thread time to write at least one frame
    time.sleep(0.25)
    sp.stop()
    captured = capsys.readouterr()
    assert "thinking" in captured.err
    # Final stop should have written the clear sequence
    assert "\r" in captured.err


def test_spinner_context_manager(capsys, monkeypatch):
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    monkeypatch.delenv("NO_COLOR", raising=False)
    with Spinner(label="work"):
        time.sleep(0.15)
    captured = capsys.readouterr()
    assert "work" in captured.err


def test_spinner_stop_without_start_is_safe():
    """Calling stop() without start() should not raise."""
    sp = Spinner()
    sp.stop()  # no thread to join — should be fine


def test_spinner_double_stop_is_safe(monkeypatch):
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    monkeypatch.delenv("NO_COLOR", raising=False)
    sp = Spinner()
    sp.start()
    sp.stop()
    sp.stop()  # should be a no-op, not raise
