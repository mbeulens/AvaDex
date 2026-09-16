import os
import pytest
from pathlib import Path

from avadex.cli import run_repl


@pytest.fixture
def restore_cwd():
    """run_repl chdirs; put the test process back where it started."""
    before = os.getcwd()
    yield
    os.chdir(before)


def _config(tmp_path, extra=""):
    config = tmp_path / "config.toml"
    config.write_text(
        'ava_url = "https://ava.test"\n'
        'ava_token = "tkn"\n'
        'default_model = "gemma4"\n' + extra
    )
    return config


def _fake_turn(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://ava.test/api/v1/messages",
        json={
            "content": [{"type": "text", "text": "ok"}],
            "model": "gemma4",
            "stop_reason": "end_turn",
            "usage": {},
        },
    )


def test_workdir_flag_chdirs_the_process(tmp_path, httpx_mock, restore_cwd):
    _fake_turn(httpx_mock)
    proj = tmp_path / "proj"
    proj.mkdir()
    seen = {}
    inputs = iter(["hello", "/exit"])

    def record(_):
        seen["cwd"] = os.getcwd()
        return next(inputs)

    rc = run_repl(
        config_path=_config(tmp_path),
        allowlist_path=tmp_path / "global.toml",
        workdir=proj,
        input_fn=record,
    )
    assert rc == 0
    assert Path(seen["cwd"]).resolve() == proj.resolve()


def test_config_workdir_used_when_no_flag(tmp_path, httpx_mock, restore_cwd):
    _fake_turn(httpx_mock)
    proj = tmp_path / "from_config"
    proj.mkdir()
    seen = {}
    inputs = iter(["hello", "/exit"])

    def record(_):
        seen["cwd"] = os.getcwd()
        return next(inputs)

    rc = run_repl(
        config_path=_config(tmp_path, f'workdir = "{proj}"\n'),
        allowlist_path=tmp_path / "global.toml",
        input_fn=record,
    )
    assert rc == 0
    assert Path(seen["cwd"]).resolve() == proj.resolve()


def test_missing_workdir_exits_2(tmp_path, capsys, restore_cwd):
    rc = run_repl(
        config_path=_config(tmp_path),
        allowlist_path=tmp_path / "global.toml",
        workdir=tmp_path / "does_not_exist",
    )
    assert rc == 2
    assert "does_not_exist" in capsys.readouterr().err


def test_allow_writes_to_workdir_allowlist(tmp_path, restore_cwd):
    proj = tmp_path / "proj"
    proj.mkdir()
    global_allowlist = tmp_path / "global.toml"
    inputs = iter(["/allow bash ls *", "/exit"])

    rc = run_repl(
        config_path=_config(tmp_path),
        allowlist_path=global_allowlist,
        workdir=proj,
        input_fn=lambda _: next(inputs),
    )
    assert rc == 0
    project_allowlist = proj / ".avadex" / "allowlist.toml"
    assert project_allowlist.exists()
    assert "ls *" in project_allowlist.read_text()
    assert not global_allowlist.exists()


def test_workdir_allowlist_is_read_when_present(tmp_path, restore_cwd):
    proj = tmp_path / "proj"
    (proj / ".avadex").mkdir(parents=True)
    (proj / ".avadex" / "allowlist.toml").write_text(
        '[[rules]]\ntool = "bash"\npattern = "npm test *"\n'
    )
    captured = {}
    inputs = iter(["/tools", "/exit"])

    import avadex.cli as cli
    real = cli.PermissionManager

    def spy(*args, **kwargs):
        pm = real(*args, **kwargs)
        captured["pm"] = pm
        return pm

    cli.PermissionManager = spy
    try:
        rc = run_repl(
            config_path=_config(tmp_path),
            allowlist_path=tmp_path / "global.toml",
            workdir=proj,
            input_fn=lambda _: next(inputs),
        )
    finally:
        cli.PermissionManager = real
    assert rc == 0
    from avadex.permissions import Decision
    pm = captured["pm"]
    assert pm.check("bash", {"command": "npm test -- x"}) == Decision.AUTO_ALLOW
