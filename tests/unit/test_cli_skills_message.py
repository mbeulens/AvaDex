from types import SimpleNamespace

from avadex.cli import _skills_message


def _skill(name, source):
    # Skill dataclass is non-trivial; for the message helper we only need .source
    return SimpleNamespace(source=source)


def test_no_skills_returns_none():
    assert _skills_message({}) is None


def test_only_global_skills():
    skills = {"a": _skill("a", "global"), "b": _skill("b", "global")}
    assert _skills_message(skills) == "Loaded 2 skill(s) from global"


def test_only_workdir_skills():
    skills = {"x": _skill("x", "workdir")}
    assert _skills_message(skills) == "Loaded 1 skill(s) from workdir"


def test_mixed_breakdown():
    skills = {
        "a": _skill("a", "global"),
        "b": _skill("b", "global"),
        "c": _skill("c", "workdir"),
    }
    assert _skills_message(skills) == "Loaded 3 skill(s) (2 global, 1 workdir)"
