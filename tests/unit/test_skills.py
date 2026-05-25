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


def test_discover_global_only(tmp_path, monkeypatch):
    import avadex.skills as skills_mod
    global_dir = tmp_path / "global"
    _write_skill(global_dir, "alpha", "name: alpha\ndescription: Alpha skill.")
    monkeypatch.setattr(skills_mod, "GLOBAL_SKILLS_DIR", global_dir)
    cwd = tmp_path / "work"
    cwd.mkdir()  # no skills/ subdir
    result = skills_mod.discover_skills(cwd)
    assert set(result) == {"alpha"}
    assert result["alpha"].source == "global"


def test_discover_workdir_overrides_global(tmp_path, monkeypatch):
    import avadex.skills as skills_mod
    global_dir = tmp_path / "global"
    _write_skill(global_dir, "dup", "name: dup\ndescription: Global version.", "GLOBAL BODY")
    monkeypatch.setattr(skills_mod, "GLOBAL_SKILLS_DIR", global_dir)
    cwd = tmp_path / "work"
    _write_skill(cwd / "skills", "dup", "name: dup\ndescription: Workdir version.", "WORKDIR BODY")
    result = skills_mod.discover_skills(cwd)
    assert set(result) == {"dup"}
    assert result["dup"].source == "workdir"
    assert result["dup"].body == "WORKDIR BODY"


def test_discover_malformed_skipped_valid_still_loads(tmp_path, monkeypatch):
    import avadex.skills as skills_mod
    global_dir = tmp_path / "global"
    _write_skill(global_dir, "good", "name: good\ndescription: Good one.")
    bad = global_dir / "bad"
    bad.mkdir()
    (bad / "SKILL.md").write_text("---\nname: bad\n---\nbody\n")  # missing description
    monkeypatch.setattr(skills_mod, "GLOBAL_SKILLS_DIR", global_dir)
    cwd = tmp_path / "work"
    cwd.mkdir()
    result = skills_mod.discover_skills(cwd)
    assert set(result) == {"good"}


def test_discover_missing_dirs_returns_empty(tmp_path, monkeypatch):
    import avadex.skills as skills_mod
    monkeypatch.setattr(skills_mod, "GLOBAL_SKILLS_DIR", tmp_path / "nonexistent")
    cwd = tmp_path / "work"
    cwd.mkdir()
    assert skills_mod.discover_skills(cwd) == {}


def test_render_skill_index_empty():
    from avadex.skills import render_skill_index
    assert render_skill_index({}) == ""


def test_render_skill_index_lists_skills_sorted():
    from avadex.skills import render_skill_index, Skill
    skills = {
        "beta": Skill("beta", "Beta does things.", "b", Path("/x"), "global"),
        "alpha": Skill("alpha", "Alpha does stuff.", "a", Path("/y"), "workdir"),
    }
    out = render_skill_index(skills)
    assert "load_skill" in out
    assert "- alpha: Alpha does stuff." in out
    assert "- beta: Beta does things." in out
    assert out.index("alpha") < out.index("beta")  # sorted by name


def test_load_skill_returns_body():
    from avadex.skills import make_load_skill_tool, Skill
    skills = {"demo": Skill("demo", "d", "THE BODY", Path("/x"), "global")}
    tool = make_load_skill_tool(skills)
    assert tool.name == "load_skill"
    result = tool.handler({"name": "demo"})
    assert result.content == "THE BODY"
    assert result.is_error is False


def test_load_skill_unknown_name_errors():
    from avadex.skills import make_load_skill_tool, Skill
    skills = {"demo": Skill("demo", "d", "b", Path("/x"), "global")}
    tool = make_load_skill_tool(skills)
    result = tool.handler({"name": "nope"})
    assert result.is_error is True
    assert "demo" in result.content  # lists available names


def test_load_skill_missing_name_errors():
    from avadex.skills import make_load_skill_tool
    tool = make_load_skill_tool({})
    result = tool.handler({})
    assert result.is_error is True


def test_load_skill_is_auto_allowed(tmp_path):
    from avadex.permissions import PermissionManager, Decision
    pm = PermissionManager(tmp_path / "allowlist.toml")
    assert pm.check("load_skill", {}) == Decision.AUTO_ALLOW
