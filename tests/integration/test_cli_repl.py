import json
import json as _json
from pathlib import Path
from avadex.cli import run_repl
from avadex.agent_loop import MAX_ITERATIONS


def test_repl_full_turn_against_fake_ava(tmp_path, httpx_mock):
    # Single-turn fake Ava: returns text
    httpx_mock.add_response(
        method="POST",
        url="https://ava.test/api/v1/messages",
        json={
            "content": [{"type": "text", "text": "hi user"}],
            "model": "gemma4",
            "stop_reason": "end_turn",
            "usage": {},
        },
    )
    config = tmp_path / "config.toml"
    config.write_text('''
ava_url = "https://ava.test"
ava_token = "tkn"
''')
    allowlist = tmp_path / "allowlist.toml"

    inputs = iter(["hello", "/exit"])
    rc = run_repl(
        config_path=config,
        allowlist_path=allowlist,
        input_fn=lambda _: next(inputs),
    )
    assert rc == 0
    request_body = json.loads(httpx_mock.get_request().content)
    assert request_body["messages"][-1]["content"] == "hello"


def test_repl_tool_loop_against_fake_ava(tmp_path, httpx_mock):
    # First Ava response: tool_use; second: end_turn
    httpx_mock.add_response(
        method="POST",
        url="https://ava.test/api/v1/messages",
        json={
            "content": [
                {"type": "tool_use", "id": "tu1", "name": "read_file",
                 "input": {"path": str(tmp_path / "target.txt")}}
            ],
            "model": "gemma4",
            "stop_reason": "tool_use",
            "usage": {},
        },
    )
    httpx_mock.add_response(
        method="POST",
        url="https://ava.test/api/v1/messages",
        json={
            "content": [{"type": "text", "text": "file says: hello"}],
            "model": "gemma4",
            "stop_reason": "end_turn",
            "usage": {},
        },
    )

    (tmp_path / "target.txt").write_text("hello")
    config = tmp_path / "config.toml"
    config.write_text('''
ava_url = "https://ava.test"
ava_token = "tkn"
''')
    allowlist = tmp_path / "allowlist.toml"

    inputs = iter(["read the file", "/exit"])
    rc = run_repl(
        config_path=config, allowlist_path=allowlist,
        input_fn=lambda _: next(inputs),
    )
    assert rc == 0
    # Second request must include tool_result
    requests = httpx_mock.get_requests()
    assert len(requests) == 2
    second = json.loads(requests[1].content)
    last_msg = second["messages"][-1]
    assert last_msg["content"][0]["type"] == "tool_result"
    assert "hello" in last_msg["content"][0]["content"]


def test_repl_iteration_cap_with_real_stack(tmp_path, httpx_mock):
    """Ava returns tool_use forever; CLI must abort at MAX_ITERATIONS."""
    # Auto-allow bash for the test
    allowlist = tmp_path / "allowlist.toml"
    allowlist.write_text('[[rules]]\ntool = "bash"\npattern = "*"\n')

    # Each returned tool_use has a unique input so the repeated-output
    # detector doesn't trip before the iteration cap.
    for i in range(MAX_ITERATIONS):
        httpx_mock.add_response(
            method="POST",
            url="https://ava.test/api/v1/messages",
            json={
                "content": [{"type": "tool_use", "id": f"tu{i}", "name": "bash",
                             "input": {"command": f"echo loop_{i}"}}],
                "model": "gemma4",
                "stop_reason": "tool_use",
                "usage": {},
            },
        )

    config = tmp_path / "config.toml"
    config.write_text('ava_url = "https://ava.test"\nava_token = "t"\n')

    inputs = iter(["spin", "/exit"])
    rc = run_repl(
        config_path=config, allowlist_path=allowlist,
        input_fn=lambda _: next(inputs),
    )
    assert rc == 0
    # Exactly MAX_ITERATIONS requests made (not the +1 we registered)
    assert len(httpx_mock.get_requests()) == MAX_ITERATIONS
