import pytest
from avadex.cli import set_key_command, login_redirect_command
from avadex.config import load_config, ConfigMissing


def test_set_key_persists_url_and_key(tmp_path):
    inputs = iter(["https://ava.test/", ])  # trailing slash should be stripped
    config = tmp_path / "config.toml"
    rc = set_key_command(
        input_fn=lambda _: next(inputs),
        password_fn=lambda _: "my-api-key",
        config_path=config,
    )
    assert rc == 0
    cfg = load_config(config)
    assert cfg.ava_url == "https://ava.test"   # trailing slash stripped
    assert cfg.ava_token == "my-api-key"


def test_set_key_rejects_empty_url(tmp_path, capsys):
    config = tmp_path / "config.toml"
    rc = set_key_command(
        input_fn=lambda _: "",
        password_fn=lambda _: "k",
        config_path=config,
    )
    assert rc == 1
    assert not config.exists()
    assert "url" in capsys.readouterr().err.lower()


def test_set_key_rejects_empty_key(tmp_path, capsys):
    config = tmp_path / "config.toml"
    rc = set_key_command(
        input_fn=lambda _: "https://x.test",
        password_fn=lambda _: "",
        config_path=config,
    )
    assert rc == 1
    assert not config.exists()
    assert "key" in capsys.readouterr().err.lower()


def test_login_redirect_returns_2_and_explains(capsys):
    rc = login_redirect_command()
    assert rc == 2
    err = capsys.readouterr().err
    assert "set-key" in err
