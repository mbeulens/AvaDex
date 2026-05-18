from pathlib import Path
from avadex.cli import login_command
from avadex.config import load_config


def test_login_persists_token(tmp_path, monkeypatch, httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://ava.test/login",
        json={"ok": True, "token": "deadbeef"},
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    inputs = iter(["https://ava.test", "martijn", "pw"])
    config_path = tmp_path / ".config" / "avadex" / "config.toml"

    login_command(input_fn=lambda _: next(inputs),
                  password_fn=lambda _: "pw",
                  config_path=config_path)

    cfg = load_config(config_path)
    assert cfg.ava_url == "https://ava.test"
    assert cfg.ava_token == "deadbeef"


def test_login_rejects_bad_credentials(tmp_path, monkeypatch, httpx_mock, capsys):
    httpx_mock.add_response(
        method="POST",
        url="https://ava.test/login",
        status_code=401,
        json={"error": "bad creds"},
    )
    inputs = iter(["https://ava.test", "x"])
    config_path = tmp_path / "config.toml"
    rc = login_command(input_fn=lambda _: next(inputs),
                       password_fn=lambda _: "x",
                       config_path=config_path)
    assert rc != 0
    assert not config_path.exists()
