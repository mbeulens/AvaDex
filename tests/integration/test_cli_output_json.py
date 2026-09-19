"""--output-format json: one machine-readable result envelope on stdout."""
import json
import os

import pytest

from avadex.cli import main


@pytest.fixture
def restore_cwd():
    before = os.getcwd()
    yield
    os.chdir(before)


def _config(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        'ava_url = "https://ava.test"\n'
        'ava_token = "tkn"\n'
        'default_model = "gemma4"\n'
    )
    return config


def _run(tmp_path, *extra):
    return main(["--config", str(_config(tmp_path)), "--workdir", str(tmp_path),
                 "--prompt", "hi", "--output-format", "json", *extra])


def test_success_envelope(tmp_path, httpx_mock, restore_cwd, capsys):
    httpx_mock.add_response(
        method="POST", url="https://ava.test/api/v1/messages",
        json={"content": [{"type": "text", "text": "the answer"}],
              "model": "gemma4", "stop_reason": "end_turn",
              "usage": {"input_tokens": 812, "output_tokens": 44}},
    )
    rc = _run(tmp_path, "--model", "qwen3:32b")
    assert rc == 0
    env = json.loads(capsys.readouterr().out)
    assert env["type"] == "result"
    assert env["is_error"] is False
    assert env["result"] == "the answer"
    assert env["usage"] == {"input_tokens": 812, "output_tokens": 44}
    assert env["usage_complete"] is True
    # Ava fell back to its default: the envelope says what actually ran.
    assert env["requested_model"] == "qwen3:32b"
    assert env["model"] == "gemma4"
    assert env["models_used"] == ["gemma4"]
    assert env["num_requests"] == 1
    assert env["permission_denials"] == []
    assert isinstance(env["duration_ms"], int)


def test_error_envelope_exits_1(tmp_path, httpx_mock, restore_cwd, capsys):
    httpx_mock.add_response(method="POST", url="https://ava.test/api/v1/messages",
                            status_code=500, text="boom")
    rc = _run(tmp_path)
    assert rc == 1
    env = json.loads(capsys.readouterr().out)
    assert env["is_error"] is True
    assert any("boom" in e for e in env["errors"])


def test_envelope_lists_refused_tools(tmp_path, httpx_mock, restore_cwd, capsys):
    httpx_mock.add_response(
        method="POST", url="https://ava.test/api/v1/messages",
        json={"content": [{"type": "tool_use", "id": "t1", "name": "bash",
                           "input": {"command": "ls"}}],
              "model": "gemma4", "stop_reason": "tool_use",
              "usage": {"input_tokens": 10, "output_tokens": 5}},
    )
    httpx_mock.add_response(
        method="POST", url="https://ava.test/api/v1/messages",
        json={"content": [{"type": "text", "text": "no bash for me"}],
              "model": "gemma4", "stop_reason": "end_turn",
              "usage": {"input_tokens": 20, "output_tokens": 6}},
    )
    rc = _run(tmp_path, "--allow-tools", "read_file")
    assert rc == 0
    env = json.loads(capsys.readouterr().out)
    assert env["permission_denials"] == [{"tool_name": "bash"}]
    assert env["usage"] == {"input_tokens": 30, "output_tokens": 11}
    assert env["num_requests"] == 2


def test_uncounted_usage_is_flagged(tmp_path, httpx_mock, restore_cwd, capsys):
    httpx_mock.add_response(
        method="POST", url="https://ava.test/api/v1/messages",
        json={"content": [{"type": "text", "text": "x"}], "model": "gemma4",
              "stop_reason": "end_turn", "usage": {"input_tokens": 0, "output_tokens": 0}},
    )
    _run(tmp_path)
    assert json.loads(capsys.readouterr().out)["usage_complete"] is False


def test_text_output_is_unchanged_by_default(tmp_path, httpx_mock, restore_cwd, capsys):
    httpx_mock.add_response(
        method="POST", url="https://ava.test/api/v1/messages",
        json={"content": [{"type": "text", "text": "plain"}], "model": "gemma4",
              "stop_reason": "end_turn", "usage": {}},
    )
    rc = main(["--config", str(_config(tmp_path)), "--workdir", str(tmp_path),
               "--prompt", "hi"])
    assert rc == 0
    assert capsys.readouterr().out == "plain\n"


def test_json_requires_prompt(tmp_path, capsys):
    rc = main(["--config", str(_config(tmp_path)), "--output-format", "json"])
    assert rc == 2
    assert "--prompt" in capsys.readouterr().err


def test_envelope_carries_the_tool_transcript(tmp_path, httpx_mock, restore_cwd, capsys):
    (tmp_path / "forms.txt").write_text("Aanhef\nOfferte\n")
    httpx_mock.add_response(
        method="POST", url="https://ava.test/api/v1/messages",
        json={"content": [{"type": "tool_use", "id": "t1", "name": "read_file",
                           "input": {"path": "forms.txt"}},
                          {"type": "tool_use", "id": "t2", "name": "bash",
                           "input": {"command": "ls"}}],
              "model": "gemma4", "stop_reason": "tool_use", "usage": {}},
    )
    httpx_mock.add_response(
        method="POST", url="https://ava.test/api/v1/messages",
        json={"content": [{"type": "text", "text": "2 forms"}], "model": "gemma4",
              "stop_reason": "end_turn", "usage": {}},
    )
    rc = _run(tmp_path, "--allow-tools", "read_file")
    assert rc == 0
    t = json.loads(capsys.readouterr().out)["transcript"]
    assert [e["tool"] for e in t] == ["read_file", "bash"]
    assert "Aanhef" in t[0]["output"] and "Offerte" in t[0]["output"]
    assert t[0]["is_error"] is False and t[0]["status"] == "ok"
    assert t[0]["server"] is None            # built-in tool
    assert t[1]["is_error"] is True and t[1]["status"] == "error"   # refused


def test_envelope_transcript_empty_without_tools(tmp_path, httpx_mock, restore_cwd, capsys):
    httpx_mock.add_response(
        method="POST", url="https://ava.test/api/v1/messages",
        json={"content": [{"type": "text", "text": "x"}], "model": "gemma4",
              "stop_reason": "end_turn", "usage": {}},
    )
    _run(tmp_path)
    assert json.loads(capsys.readouterr().out)["transcript"] == []
