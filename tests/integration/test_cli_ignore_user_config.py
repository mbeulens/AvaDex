"""--ignore-user-config: use exactly the caller's config, nothing from ~."""
import json
import os

import pytest

from avadex import skills as skills_mod
from avadex.cli import main
from avadex.permissions import PermissionManager, Rule, Decision
from avadex.skills import discover_skills


@pytest.fixture
def restore_cwd():
    before = os.getcwd()
    yield
    os.chdir(before)


@pytest.fixture
def user_skill(tmp_path, monkeypatch):
    """A skill in the (fake) invoking user's global skills dir."""
    gdir = tmp_path / "home_skills"
    (gdir / "leaky").mkdir(parents=True)
    (gdir / "leaky" / "SKILL.md").write_text(
        "---\nname: leaky\ndescription: from the user's home\n---\nbody\n")
    monkeypatch.setattr(skills_mod, "GLOBAL_SKILLS_DIR", gdir)
    return gdir


def _config(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('ava_url = "https://ava.test"\nava_token = "tkn"\n'
                      'default_model = "gemma4"\n')
    return config


def _ok(httpx_mock):
    httpx_mock.add_response(
        method="POST", url="https://ava.test/api/v1/messages",
        json={"content": [{"type": "text", "text": "ok"}], "model": "gemma4",
              "stop_reason": "end_turn", "usage": {}})


def _system_sent(httpx_mock):
    return json.loads(httpx_mock.get_requests()[0].content)["system"]


def test_discover_skills_can_skip_global(tmp_path, user_skill):
    assert "leaky" in discover_skills(tmp_path)
    assert discover_skills(tmp_path, include_global=False) == {}


def test_permission_manager_without_global_file(tmp_path):
    project = tmp_path / ".avadex" / "allowlist.toml"
    pm = PermissionManager(None, project)
    assert pm.check("bash", {"command": "ls"}) == Decision.PROMPT
    pm.add_rule(Rule(tool="bash", pattern="ls"))
    assert project.exists()
    assert pm.check("bash", {"command": "ls"}) == Decision.AUTO_ALLOW


def test_permission_manager_with_no_files_keeps_rules_in_memory(tmp_path):
    pm = PermissionManager(None, None)
    pm.add_rule(Rule(tool="bash", pattern="ls"))
    assert pm.check("bash", {"command": "ls"}) == Decision.AUTO_ALLOW
    assert list(tmp_path.iterdir()) == []


def test_user_skills_load_by_default(tmp_path, httpx_mock, user_skill, restore_cwd):
    _ok(httpx_mock)
    main(["--config", str(_config(tmp_path)), "--workdir", str(tmp_path), "--prompt", "hi"])
    assert "leaky" in _system_sent(httpx_mock)


def test_flag_drops_user_skills(tmp_path, httpx_mock, user_skill, restore_cwd):
    _ok(httpx_mock)
    rc = main(["--config", str(_config(tmp_path)), "--workdir", str(tmp_path),
               "--prompt", "hi", "--ignore-user-config"])
    assert rc == 0
    assert "leaky" not in _system_sent(httpx_mock)


def test_flag_keeps_workdir_skills(tmp_path, httpx_mock, user_skill, restore_cwd):
    proj = tmp_path / "proj"
    (proj / "skills" / "mine").mkdir(parents=True)
    (proj / "skills" / "mine" / "SKILL.md").write_text(
        "---\nname: mine\ndescription: project skill\n---\nbody\n")
    _ok(httpx_mock)
    main(["--config", str(_config(tmp_path)), "--workdir", str(proj),
          "--prompt", "hi", "--ignore-user-config"])
    system = _system_sent(httpx_mock)
    assert "mine" in system and "leaky" not in system


def test_flag_requires_explicit_config(capsys):
    # The default config lives in the user's home, so the flag is meaningless
    # (and misleading) without --config.
    rc = main(["--prompt", "hi", "--ignore-user-config"])
    assert rc == 2
    assert "--config" in capsys.readouterr().err
