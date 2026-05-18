from avadex.renderer import RecordingRenderer
from avadex.tools.registry import ToolRegistry, ToolDefinition, ToolResult
from avadex.permissions import PermissionManager
from avadex.agent_loop import AgentLoop
from avadex.types import AvaResponse, TextBlock, ToolUseBlock


class ScriptedClient:
    """Returns the responses in order, one per call."""
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
    def messages(self, system, messages, tools, max_tokens=2048, model="gemma4"):
        self.calls.append(list(messages))
        return self.responses.pop(0)


def echo_tool(args):
    return ToolResult(content=f"echoed {args['x']}")


def make_registry():
    reg = ToolRegistry()
    reg.register(ToolDefinition(
        name="echo", description="", input_schema={}, handler=echo_tool,
    ))
    return reg


def test_tool_use_dispatched_and_result_appended(tmp_path):
    responses = [
        AvaResponse(
            content=[ToolUseBlock(id="tu1", name="echo", input={"x": "hi"})],
            model="gemma4", stop_reason="tool_use", usage={},
        ),
        AvaResponse(
            content=[TextBlock(text="ok done")],
            model="gemma4", stop_reason="end_turn", usage={},
        ),
    ]
    client = ScriptedClient(responses)
    pm = PermissionManager(tmp_path / "allow.toml")
    # Auto-allow echo for the test
    from avadex.permissions import Rule
    pm.add_rule(Rule(tool="echo", pattern="*"))

    loop = AgentLoop(
        client=client, registry=make_registry(), permissions=pm,
        system_prompt="", max_context_tokens=10000,
    )
    renderer = RecordingRenderer()
    loop.run_turn("please echo", renderer)

    # Second call must include the tool_result
    second_messages = client.calls[1]
    last = second_messages[-1]
    assert last["role"] == "user"
    assert last["content"][0]["type"] == "tool_result"
    assert last["content"][0]["tool_use_id"] == "tu1"
    assert "echoed hi" in last["content"][0]["content"]


def test_permission_denial_yields_error_result(tmp_path):
    responses = [
        AvaResponse(
            content=[ToolUseBlock(id="tu1", name="echo", input={"x": "denied"})],
            model="gemma4", stop_reason="tool_use", usage={},
        ),
        AvaResponse(
            content=[TextBlock(text="ok stopping")],
            model="gemma4", stop_reason="end_turn", usage={},
        ),
    ]
    client = ScriptedClient(responses)
    pm = PermissionManager(tmp_path / "allow.toml")
    # No allowlist; echo will prompt. Use a denying prompter.
    loop = AgentLoop(
        client=client, registry=make_registry(), permissions=pm,
        system_prompt="", max_context_tokens=10000,
        prompt_user=lambda tool, args: ("deny", None),
    )
    loop.run_turn("try", RecordingRenderer())
    result_msg = client.calls[1][-1]
    assert result_msg["content"][0]["is_error"] is True
    assert "denied" in result_msg["content"][0]["content"].lower()


def test_always_response_persists_rule(tmp_path):
    responses = [
        AvaResponse(
            content=[ToolUseBlock(id="tu1", name="echo", input={"x": "first"})],
            model="gemma4", stop_reason="tool_use", usage={},
        ),
        AvaResponse(
            content=[TextBlock(text="ok")],
            model="gemma4", stop_reason="end_turn", usage={},
        ),
    ]
    client = ScriptedClient(responses)
    pm = PermissionManager(tmp_path / "allow.toml")
    loop = AgentLoop(
        client=client, registry=make_registry(), permissions=pm,
        system_prompt="", max_context_tokens=10000,
        prompt_user=lambda tool, args: ("always", "*"),
    )
    loop.run_turn("go", RecordingRenderer())

    # Rule must be persisted
    from avadex.permissions import PermissionManager as PM2, Decision
    pm2 = PM2(tmp_path / "allow.toml")
    assert pm2.check("echo", {"x": "second"}) == Decision.AUTO_ALLOW
