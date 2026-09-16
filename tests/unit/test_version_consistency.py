"""The banner is the only place users see the version, so it must never drift
from the packaged version. These tests fail a release that bumps one and not
the other."""
import re
import tomllib
from pathlib import Path

import avadex
from avadex.repl import Repl


PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_pyproject_version_matches_package_version():
    with open(PYPROJECT, "rb") as f:
        packaged = tomllib.load(f)["project"]["version"]
    assert packaged == avadex.__version__, (
        "pyproject.toml and avadex/__init__.py disagree on the version"
    )


def test_welcome_banner_shows_the_current_version(capsys):
    class FakeAgent:
        model = "gemma4"

    Repl(agent=FakeAgent(), input_fn=lambda _: "/exit")._print_welcome()
    out = capsys.readouterr().out
    assert f"AvaDex {avadex.__version__}" in out


def test_banner_version_is_not_hardcoded(monkeypatch, capsys):
    """Bumping __version__ alone must change what the UI prints."""
    class FakeAgent:
        model = "gemma4"

    monkeypatch.setattr(avadex, "__version__", "9.9.9")
    Repl(agent=FakeAgent(), input_fn=lambda _: "/exit")._print_welcome()
    assert "AvaDex 9.9.9" in capsys.readouterr().out
