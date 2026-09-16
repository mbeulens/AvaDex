from pathlib import Path
import avadex.cli as cli


def test_main_forwards_workdir_flag_to_run_repl(monkeypatch):
    seen = {}

    def fake_run_repl(**kwargs):
        seen.update(kwargs)
        return 0

    monkeypatch.setattr(cli, "run_repl", fake_run_repl)
    assert cli.main(["--workdir", "/srv/projects/testsite"]) == 0
    assert seen["workdir"] == Path("/srv/projects/testsite")


def test_main_defaults_workdir_to_none(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "run_repl", lambda **kw: seen.update(kw) or 0)
    assert cli.main([]) == 0
    assert seen["workdir"] is None
