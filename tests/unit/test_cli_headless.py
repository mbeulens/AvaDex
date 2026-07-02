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
