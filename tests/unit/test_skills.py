import pytest
from pathlib import Path


def _write_skill(dir_path: Path, name: str, frontmatter: str, body: str = "Body here.") -> Path:
    d = dir_path / name
    d.mkdir(parents=True)
    f = d / "SKILL.md"
    f.write_text(f"---\n{frontmatter}\n---\n{body}\n")
    return f


def test_parse_skill_file_valid(tmp_path):
    from avadex.skills import _parse_skill_file
    f = _write_skill(tmp_path, "demo",
                     "name: demo\ndescription: A demo skill.",
                     "Step one.\nStep two.")
    skill = _parse_skill_file(f, "global")
    assert skill is not None
    assert skill.name == "demo"
    assert skill.description == "A demo skill."
    assert skill.body == "Step one.\nStep two."
    assert skill.source == "global"
    assert skill.path == f


def test_parse_skill_file_no_frontmatter(tmp_path):
    from avadex.skills import _parse_skill_file
    f = tmp_path / "SKILL.md"
    f.write_text("Just a body, no frontmatter.\n")
    assert _parse_skill_file(f, "global") is None


def test_parse_skill_file_unclosed_frontmatter(tmp_path):
    from avadex.skills import _parse_skill_file
    f = tmp_path / "SKILL.md"
    f.write_text("---\nname: x\ndescription: y\n")  # no closing ---
    assert _parse_skill_file(f, "global") is None


def test_parse_skill_file_missing_name(tmp_path):
    from avadex.skills import _parse_skill_file
    f = tmp_path / "SKILL.md"
    f.write_text("---\ndescription: only desc\n---\nbody\n")
    assert _parse_skill_file(f, "global") is None


def test_parse_skill_file_missing_description(tmp_path):
    from avadex.skills import _parse_skill_file
    f = tmp_path / "SKILL.md"
    f.write_text("---\nname: only-name\n---\nbody\n")
    assert _parse_skill_file(f, "global") is None
