"""The `ava` key-policy block in the JSON envelope, and --require-private."""
import json
import os

import pytest

from avadex.cli import main

PRIVATE = {"key": "c", "private": True, "rag": False, "retained": False}
SHARED = {"key": "c", "private": False, "rag": True, "retained": True}
URL = "https://ava.test/api/v1/messages"
MODELS_URL = "https://ava.test/api/v1/models"


@pytest.fixture
def restore_cwd():
    before = os.getcwd()
    yield
    os.chdir(before)


def _config(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('ava_url = "https://ava.test"\nava_token = "tkn"\n'
                      'default_model = "gemma4"\n')
    return config


def _msg(httpx_mock, ava, content=None, stop="end_turn"):
    body = {"content": content or [{"type": "text", "text": "ok"}], "model": "gemma4",
            "stop_reason": stop, "usage": {"input_tokens": 5, "output_tokens": 1}}
    if ava is not None:
        body["ava"] = ava
    httpx_mock.add_response(method="POST", url=URL, json=body)


def _models(httpx_mock, ava):
    body = {"models": [{"id": "gemma4", "size": "1GB"}], "default": "gemma4"}
    if ava is not None:
        body["ava"] = ava
    httpx_mock.add_response(method="GET", url=MODELS_URL, json=body)


def _run(tmp_path, *extra):
    return main(["--config", str(_config(tmp_path)), "--workdir", str(tmp_path),
                 "--prompt", "hi", "--output-format", "json", *extra])


def test_envelope_carries_ava_block(tmp_path, httpx_mock, restore_cwd, capsys):
    _msg(httpx_mock, PRIVATE)
    assert _run(tmp_path) == 0
    env = json.loads(capsys.readouterr().out)
    assert env["ava"] == PRIVATE
    assert env["ava_changed"] is False


def test_envelope_ava_is_null_against_older_ava(tmp_path, httpx_mock, restore_cwd, capsys):
    _msg(httpx_mock, None)
    _run(tmp_path)
    env = json.loads(capsys.readouterr().out)
    assert env["ava"] is None


def test_require_private_preflight_refuses_a_shared_key(tmp_path, httpx_mock, restore_cwd, capsys):
    _models(httpx_mock, SHARED)
    rc = _run(tmp_path, "--require-private")
    out = capsys.readouterr()
    assert rc == 1
    assert "not private" in out.err
    # Nothing was sent to /messages: the prompt never left the machine.
    assert [r.method for r in httpx_mock.get_requests()] == ["GET"]
    env = json.loads(out.out)
    assert env["is_error"] is True and env["ava"] == SHARED


def test_require_private_preflight_refuses_a_server_without_the_block(tmp_path, httpx_mock, restore_cwd, capsys):
    _models(httpx_mock, None)
    assert _run(tmp_path, "--require-private") == 1
    assert [r.method for r in httpx_mock.get_requests()] == ["GET"]


def test_require_private_passes_when_private(tmp_path, httpx_mock, restore_cwd, capsys):
    _models(httpx_mock, PRIVATE)
    _msg(httpx_mock, PRIVATE)
    assert _run(tmp_path, "--require-private") == 0
    assert json.loads(capsys.readouterr().out)["is_error"] is False


def test_require_private_aborts_on_mid_run_flip(tmp_path, httpx_mock, restore_cwd, capsys):
    _models(httpx_mock, PRIVATE)
    _msg(httpx_mock, SHARED, stop="tool_use",
         content=[{"type": "tool_use", "id": "t1", "name": "read_file", "input": {"path": "x"}}])
    rc = _run(tmp_path, "--require-private")
    env = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert env["is_error"] is True
    assert env["ava"] == SHARED
    assert env["ava_changed"] is True   # preflight said private, the response didn't
    assert len([r for r in httpx_mock.get_requests() if r.method == "POST"]) == 1


def test_models_json_includes_ava_block_when_present(tmp_path, httpx_mock, capsys):
    _models(httpx_mock, PRIVATE)
    main(["--config", str(_config(tmp_path)), "models", "--json"])
    assert json.loads(capsys.readouterr().out)["ava"] == PRIVATE
