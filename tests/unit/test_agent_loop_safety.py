from avadex.renderer import RecordingRenderer
from avadex.tools.registry import ToolRegistry, ToolDefinition, ToolResult
from avadex.permissions import PermissionManager, Rule
from avadex.agent_loop import AgentLoop, MAX_ITERATIONS
from avadex.types import AvaResponse, TextBlock, ToolUseBlock


def looping_tool(args):
    return ToolResult(content="loop")


def make_registry():
    reg = ToolRegistry()
    reg.register(ToolDefinition(
        name="loop", description="", input_schema={}, handler=looping_tool,
    ))
    return reg


class LoopingClient:
    """Always returns a tool_use with a unique input; never end_turn."""
    def __init__(self):
        self.call_count = 0
    def messages(self, system, messages, tools, max_tokens=2048, model="gemma4"):
        self.call_count += 1
        # Vary input each call so repeat-detection doesn't fire before the cap
        return AvaResponse(
            content=[ToolUseBlock(id=f"tu{self.call_count}", name="loop",
                                  input={"n": self.call_count})],
            model="gemma4", stop_reason="tool_use", usage={},
        )


def test_iteration_cap_aborts(tmp_path):
    client = LoopingClient()
    pm = PermissionManager(tmp_path / "allow.toml")
    pm.add_rule(Rule(tool="loop", pattern="*"))
    loop = AgentLoop(
        client=client, registry=make_registry(), permissions=pm,
        system_prompt="", max_context_tokens=100000,
    )
    renderer = RecordingRenderer()
    loop.run_turn("go", renderer)
    assert client.call_count == MAX_ITERATIONS
    assert any(e[0] == "error" and "iteration" in e[1].lower() for e in renderer.events)


class RepeatingTextClient:
    """Returns the same text three turns in a row (between tool calls)."""
    def __init__(self):
        self.n = 0
    def messages(self, system, messages, tools, max_tokens=2048, model="gemma4"):
        self.n += 1
        if self.n <= 3:
            return AvaResponse(
                content=[
                    TextBlock(text="thinking..."),
                    ToolUseBlock(id=f"tu{self.n}", name="loop", input={}),
                ],
                model="gemma4", stop_reason="tool_use", usage={},
            )
        return AvaResponse(content=[TextBlock(text="done")], model="gemma4",
                           stop_reason="end_turn", usage={})


def test_repeated_output_detection(tmp_path):
    client = RepeatingTextClient()
    pm = PermissionManager(tmp_path / "allow.toml")
    pm.add_rule(Rule(tool="loop", pattern="*"))
    loop = AgentLoop(
        client=client, registry=make_registry(), permissions=pm,
        system_prompt="", max_context_tokens=100000,
    )
    renderer = RecordingRenderer()
    loop.run_turn("go", renderer)
    # Should abort after 3 identical text+tool combos, never reaching call 4
    assert client.n == 3
    assert any(e[0] == "error" and "repeated" in e[1].lower() for e in renderer.events)


def test_repeat_abort_reports_the_unrun_calls(tmp_path):
    # The third identical response's tool call is never executed. It must be
    # reported, so a transcript can't look complete when it isn't.
    client = RepeatingTextClient()
    pm = PermissionManager(tmp_path / "allow.toml")
    pm.add_rule(Rule(tool="loop", pattern="*"))
    loop = AgentLoop(
        client=client, registry=make_registry(), permissions=pm,
        system_prompt="", max_context_tokens=100000,
    )
    renderer = RecordingRenderer()
    loop.run_turn("go", renderer)
    skipped = [e for e in renderer.events if e[0] == "tool_skipped"]
    assert skipped == [("tool_skipped", "loop", {}, "repeated output detected")]
    assert sum(1 for e in renderer.events if e[0] == "tool_call") == 2
