from avadex.repl import build_terminal_prompter


def test_yes_answer_returns_yes():
    prompter = build_terminal_prompter(input_fn=lambda _: "y")
    answer, pattern = prompter("bash", {"command": "ls"})
    assert answer == "yes"
    assert pattern is None


def test_no_answer_returns_deny():
    prompter = build_terminal_prompter(input_fn=lambda _: "n")
    answer, _ = prompter("bash", {"command": "rm"})
    assert answer == "deny"


def test_always_answer_collects_pattern():
    answers = iter(["a", "ls *"])
    prompter = build_terminal_prompter(input_fn=lambda _: next(answers))
    answer, pattern = prompter("bash", {"command": "ls -la"})
    assert answer == "always"
    assert pattern == "ls *"


def test_unknown_answer_defaults_to_deny():
    prompter = build_terminal_prompter(input_fn=lambda _: "x")
    answer, _ = prompter("bash", {"command": "ls"})
    assert answer == "deny"
