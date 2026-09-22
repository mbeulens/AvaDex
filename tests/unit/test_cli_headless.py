import avadex.cli as cli
from avadex.cli import _auto_approve_prompter, _select_prompter


def test_auto_approve_returns_yes_for_any_tool():
    # In headless mode there's no human to ask; every tool call is approved
    # for THIS invocation only (no allowlist mutation — pattern is None).
    assert _auto_approve_prompter("bash", {"cmd": "rm -rf /"}) == ("yes", None)
    assert _auto_approve_prompter("write_file", {"path": "x", "content": "y"}) == ("yes", None)
    assert _auto_approve_prompter("anything", {}) == ("yes", None)


def test_headless_prompt_selects_auto_approve():
    # --prompt (headless) always auto-approves, regardless of auto_approve.
    assert _select_prompter("do a thing", False) is _auto_approve_prompter


def test_yes_flag_selects_auto_approve_in_repl():
    # --yes makes an interactive REPL (prompt is None) autonomous.
    assert _select_prompter(None, True) is _auto_approve_prompter


def test_plain_repl_uses_interactive_prompter():
    # No --prompt and no --yes → the human is asked per non-read tool.
    prompter = _select_prompter(None, False)
    assert prompter is not _auto_approve_prompter
    assert callable(prompter)


def test_an_empty_prompt_is_refused(monkeypatch, capsys):
    """A run with no task cannot state what it is doing.

    The task message is also the anchor every request needs; an empty one is
    not one, so context management is free to drop it and the run dies later
    with an Ava 400 instead of here, immediately, with a reason.
    """
    monkeypatch.setattr(cli, "run_repl", lambda **kw: 0)
    assert cli.main(["--prompt", ""]) == 2
    assert "empty" in capsys.readouterr().err.lower()


def test_a_whitespace_only_prompt_is_refused(monkeypatch):
    # Whitespace is no more of an anchor than "" — _has_text strips first.
    monkeypatch.setattr(cli, "run_repl", lambda **kw: 0)
    assert cli.main(["--prompt", "   \n"]) == 2


def test_a_real_prompt_still_runs(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "run_repl", lambda **kw: seen.update(kw) or 0)
    assert cli.main(["--prompt", "build the form set"]) == 0
    assert seen["prompt"] == "build the form set"
