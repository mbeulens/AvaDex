"""`avadex models`: enumerate the models Ava will accept."""
import json

from avadex.cli import main

MODELS = {"models": [{"id": "gemma4:latest", "size": "9.6GB"},
                     {"id": "qwen3:32b", "size": "20.2GB"}],
          "default": "gemma4:latest"}


def _config(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('ava_url = "https://ava.test"\nava_token = "tkn"\n')
    return config


def test_models_json(tmp_path, httpx_mock, capsys):
    httpx_mock.add_response(method="GET", url="https://ava.test/api/v1/models", json=MODELS)
    rc = main(["--config", str(_config(tmp_path)), "models", "--json"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == MODELS


def test_models_text_marks_default(tmp_path, httpx_mock, capsys):
    httpx_mock.add_response(method="GET", url="https://ava.test/api/v1/models", json=MODELS)
    rc = main(["--config", str(_config(tmp_path)), "models"])
    assert rc == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines == ["gemma4:latest  9.6GB  (default)", "qwen3:32b  20.2GB"]


def test_models_auth_failure_exits_1(tmp_path, httpx_mock, capsys):
    httpx_mock.add_response(method="GET", url="https://ava.test/api/v1/models", status_code=401)
    rc = main(["--config", str(_config(tmp_path)), "models", "--json"])
    assert rc == 1
    assert "rejected" in capsys.readouterr().err


def test_models_missing_config_exits_2(tmp_path, capsys):
    rc = main(["--config", str(tmp_path / "nope.toml"), "models"])
    assert rc == 2
