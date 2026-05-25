from avadex.agent_loop import _unexecuted_tool_call_name, AgentLoop
from avadex.renderer import RecordingRenderer
from avadex.tools.registry import ToolRegistry, ToolDefinition, ToolResult
from avadex.permissions import PermissionManager
from avadex.types import AvaResponse, TextBlock


def test_detects_plain_tool_call_json():
    text = '{"name": "write_file", "arguments": {"path": "x.php", "content": "..."}}'
    assert _unexecuted_tool_call_name(text, {"write_file", "read_file"}) == "write_file"


def test_detects_fenced_tool_call_json():
    text = '```json\n{"name": "write_file", "parameters": {"path": "x"}}\n```'
    assert _unexecuted_tool_call_name(text, {"write_file"}) == "write_file"


def test_detects_input_key_variant():
    text = '{"name": "write_file", "input": {"path": "x"}}'
    assert _unexecuted_tool_call_name(text, {"write_file"}) == "write_file"


def test_ignores_normal_prose():
    assert _unexecuted_tool_call_name("Here is your function.", {"write_file"}) is None


def test_ignores_unknown_tool_name():
    text = '{"name": "frobnicate", "arguments": {}}'
    assert _unexecuted_tool_call_name(text, {"write_file"}) is None


def test_ignores_json_without_args():
    text = '{"name": "write_file"}'
    assert _unexecuted_tool_call_name(text, {"write_file"}) is None


def test_ignores_non_json():
    assert _unexecuted_tool_call_name("{not valid json", {"write_file"}) is None


def test_ignores_json_with_trailing_prose():
    # Conservative: only fire when the text IS the tool call, not prose around it.
    text = '{"name": "write_file", "arguments": {}} and here is why...'
    assert _unexecuted_tool_call_name(text, {"write_file"}) is None


def test_run_turn_warns_when_tool_call_emitted_as_text(tmp_path):
    reg = ToolRegistry()
    reg.register(ToolDefinition(
        name="write_file", description="", input_schema={},
        handler=lambda a: ToolResult(content="ok"),
    ))
    text = '{"name": "write_file", "arguments": {"path": "coder.php", "content": "y"}}'
    resp = AvaResponse(content=[TextBlock(text=text)], model="qwen2.5-coder:32b",
                       stop_reason="end_turn", usage={})

    class FakeClient:
        def messages(self, **kw):
            return resp

    loop = AgentLoop(client=FakeClient(), registry=reg,
                     permissions=PermissionManager(tmp_path / "a.toml"),
                     system_prompt="", max_context_tokens=10000,
                     model="qwen2.5-coder:32b")
    renderer = RecordingRenderer()
    loop.run_turn("create a file", renderer)

    errors = [e for e in renderer.events if e[0] == "error"]
    assert errors, f"expected a warning event, got {renderer.events}"
    msg = errors[0][1]
    assert "tool" in msg.lower()
    assert "/model" in msg


def test_run_turn_no_warning_on_normal_text(tmp_path):
    reg = ToolRegistry()
    reg.register(ToolDefinition(
        name="write_file", description="", input_schema={},
        handler=lambda a: ToolResult(content="ok"),
    ))
    resp = AvaResponse(content=[TextBlock(text="Here is your answer.")],
                       model="gemma4", stop_reason="end_turn", usage={})

    class FakeClient:
        def messages(self, **kw):
            return resp

    loop = AgentLoop(client=FakeClient(), registry=reg,
                     permissions=PermissionManager(tmp_path / "a.toml"),
                     system_prompt="", max_context_tokens=10000, model="gemma4")
    renderer = RecordingRenderer()
    loop.run_turn("hi", renderer)

    assert [e for e in renderer.events if e[0] == "error"] == []
