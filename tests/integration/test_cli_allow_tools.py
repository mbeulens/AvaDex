"""--allow-tools: the caller states the permitted tool set; headless enforces it."""
import json
import os

import pytest
# Import before any test's capsys is active: stdio_client binds
# `errlog=sys.stderr` as a default at import time, and capsys's stand-in has
# no fileno(), which would break every later stdio MCP spawn in the session.
import mcp.client.stdio  # noqa: F401

from avadex.cli import main, run_repl


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


def _respond(httpx_mock, content, stop_reason):
    httpx_mock.add_response(
        method="POST", url="https://ava.test/api/v1/messages",
        json={"content": content, "model": "gemma4",
              "stop_reason": stop_reason, "usage": {}},
    )


def _tool_names_sent(request):
    return sorted(t["name"] for t in json.loads(request.content)["tools"])


def test_only_allowed_tools_are_sent_to_the_model(tmp_path, httpx_mock, restore_cwd):
    _respond(httpx_mock, [{"type": "text", "text": "done"}], "end_turn")
    rc = run_repl(
        config_path=_config(tmp_path), allowlist_path=tmp_path / "allow.toml",
        workdir=tmp_path, prompt="hi", allow_tools="read_file,grep_files",
    )
    assert rc == 0
    [req] = httpx_mock.get_requests()
    assert _tool_names_sent(req) == ["grep_files", "read_file"]


def test_system_prompt_names_the_restriction(tmp_path, httpx_mock, restore_cwd):
    _respond(httpx_mock, [{"type": "text", "text": "done"}], "end_turn")
    run_repl(
        config_path=_config(tmp_path), allowlist_path=tmp_path / "allow.toml",
        workdir=tmp_path, prompt="hi", allow_tools="read_file",
    )
    system = json.loads(httpx_mock.get_requests()[0].content)["system"]
    assert "only use these tools: read_file" in system


def test_disallowed_tool_call_is_refused_and_reported(tmp_path, httpx_mock, restore_cwd, capsys):
    # Conductor's probe: the model tries bash anyway; the file must survive.
    probe = tmp_path / "probe"
    probe.mkdir()
    _respond(httpx_mock, [{"type": "tool_use", "id": "tu1", "name": "bash",
                           "input": {"command": f"rm -rf {probe}"}}], "tool_use")
    _respond(httpx_mock, [{"type": "text", "text": "I was not allowed."}], "end_turn")
    rc = run_repl(
        config_path=_config(tmp_path), allowlist_path=tmp_path / "allow.toml",
        workdir=tmp_path, prompt="run: rm -rf probe", allow_tools="read_file",
    )
    assert probe.exists()
    second = json.loads(httpx_mock.get_requests()[1].content)
    tool_result = second["messages"][-1]["content"][0]
    assert tool_result["is_error"] is True
    assert "not permitted" in tool_result["content"]
    assert "refused tool 'bash'" in capsys.readouterr().err
    assert rc == 0


def test_unknown_entry_exits_2_before_calling_ava(tmp_path, httpx_mock, restore_cwd, capsys):
    rc = run_repl(
        config_path=_config(tmp_path), allowlist_path=tmp_path / "allow.toml",
        workdir=tmp_path, prompt="hi", allow_tools="read_file,mcp__syntec-forms",
    )
    assert rc == 2
    assert "mcp__syntec-forms" in capsys.readouterr().err
    assert httpx_mock.get_requests() == []


def test_allow_tools_flag_is_wired_through_main(tmp_path, httpx_mock, restore_cwd):
    _respond(httpx_mock, [{"type": "text", "text": "done"}], "end_turn")
    rc = main(["--config", str(_config(tmp_path)), "--workdir", str(tmp_path),
               "--prompt", "hi", "--allow-tools", "glob"])
    assert rc == 0
    assert _tool_names_sent(httpx_mock.get_requests()[0]) == ["glob"]


def test_without_flag_all_tools_are_sent(tmp_path, httpx_mock, restore_cwd):
    _respond(httpx_mock, [{"type": "text", "text": "done"}], "end_turn")
    run_repl(
        config_path=_config(tmp_path), allowlist_path=tmp_path / "allow.toml",
        workdir=tmp_path, prompt="hi",
    )
    names = _tool_names_sent(httpx_mock.get_requests()[0])
    assert "bash" in names and "write_file" in names


def test_mcp_server_that_fails_to_start_exits_2_and_sends_nothing(
        tmp_path, httpx_mock, restore_cwd, capsys):
    # A broken MCP server must not turn into an unrestricted run, nor a run
    # with no tools: its tools are never registered, so the allow entry
    # matches nothing and AvaDex refuses before calling Ava.
    (tmp_path / ".mcp.json").write_text(json.dumps(
        {"mcpServers": {"broken": {"command": str(tmp_path / "no-such-binary")}}}))
    rc = run_repl(
        config_path=_config(tmp_path), allowlist_path=tmp_path / "allow.toml",
        workdir=tmp_path, prompt="hi", allow_tools="mcp__broken",
    )
    err = capsys.readouterr().err
    assert rc == 2
    assert "mcp__broken" in err
    assert httpx_mock.get_requests() == []
