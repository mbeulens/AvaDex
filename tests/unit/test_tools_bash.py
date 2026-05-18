import pytest
from avadex.tools.builtin import bash_tool


def test_bash_captures_stdout():
    result = bash_tool({"command": "echo hello"})
    assert not result.is_error
    assert "hello" in result.content


def test_bash_captures_stderr():
    result = bash_tool({"command": "echo err 1>&2"})
    # stderr should appear in the combined output
    assert "err" in result.content


def test_bash_nonzero_exit_is_error():
    result = bash_tool({"command": "exit 3"})
    assert result.is_error
    assert "exit code 3" in result.content or "code: 3" in result.content


def test_bash_timeout():
    result = bash_tool({"command": "sleep 5", "timeout": 1})
    assert result.is_error
    assert "timed out" in result.content.lower()


def test_bash_missing_command():
    result = bash_tool({})
    assert result.is_error


def test_bash_timeout_clamped_to_max(monkeypatch):
    """An absurd timeout value is clamped to MAX_BASH_TIMEOUT (600s) so the
    model can't accidentally block AvaDex for hours."""
    from avadex.tools import builtin
    captured = {}

    def fake_run(*args, **kwargs):
        captured["timeout"] = kwargs.get("timeout")
        # Mimic a fast success
        class P:
            returncode = 0
            stdout = "ok"
            stderr = ""
        return P()

    monkeypatch.setattr(builtin.subprocess, "run", fake_run)
    result = bash_tool({"command": "echo hi", "timeout": 99999})
    assert not result.is_error
    assert captured["timeout"] == builtin.MAX_BASH_TIMEOUT
