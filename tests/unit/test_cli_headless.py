from avadex.cli import _auto_approve_prompter


def test_auto_approve_returns_yes_for_any_tool():
    # In headless mode there's no human to ask; every tool call is approved
    # for THIS invocation only (no allowlist mutation — pattern is None).
    assert _auto_approve_prompter("bash", {"cmd": "rm -rf /"}) == ("yes", None)
    assert _auto_approve_prompter("write_file", {"path": "x", "content": "y"}) == ("yes", None)
    assert _auto_approve_prompter("anything", {}) == ("yes", None)
