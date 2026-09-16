from pathlib import Path
import pytest

from avadex.workdir import (
    WorkdirError,
    resolve_workdir,
    workdir_allowlist_path,
    WORKDIR_ALLOWLIST_RELPATH,
)


def test_defaults_to_base_when_nothing_set(tmp_path):
    assert resolve_workdir(base=tmp_path) == tmp_path.resolve()


def test_config_value_used_when_no_flag(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    assert resolve_workdir(config_value=str(proj), base=tmp_path) == proj.resolve()


def test_flag_wins_over_config_value(tmp_path):
    flagged = tmp_path / "flagged"
    configured = tmp_path / "configured"
    flagged.mkdir()
    configured.mkdir()
    result = resolve_workdir(flag=flagged, config_value=str(configured), base=tmp_path)
    assert result == flagged.resolve()


def test_relative_flag_resolves_against_base(tmp_path):
    nested = tmp_path / "nested"
    nested.mkdir()
    assert resolve_workdir(flag="nested", base=tmp_path) == nested.resolve()


def test_tilde_is_expanded(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "work").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    assert resolve_workdir(flag="~/work", base=tmp_path) == (home / "work").resolve()


def test_missing_directory_raises(tmp_path):
    with pytest.raises(WorkdirError) as exc:
        resolve_workdir(flag=tmp_path / "nope", base=tmp_path)
    assert "nope" in str(exc.value)


def test_file_instead_of_directory_raises(tmp_path):
    f = tmp_path / "afile.txt"
    f.write_text("x")
    with pytest.raises(WorkdirError) as exc:
        resolve_workdir(flag=f, base=tmp_path)
    assert "not a directory" in str(exc.value)


def test_empty_config_value_is_ignored(tmp_path):
    assert resolve_workdir(flag=None, config_value="", base=tmp_path) == tmp_path.resolve()


def test_allowlist_path_is_dot_avadex_inside_workdir(tmp_path):
    assert workdir_allowlist_path(tmp_path) == tmp_path / ".avadex" / "allowlist.toml"


def test_allowlist_relpath_constant():
    assert WORKDIR_ALLOWLIST_RELPATH == Path(".avadex") / "allowlist.toml"
