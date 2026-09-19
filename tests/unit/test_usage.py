from avadex.agent_loop import AgentLoop
from avadex.permissions import PermissionManager
from avadex.renderer import RecordingRenderer
from avadex.tools.registry import ToolDefinition, ToolRegistry, ToolResult
from avadex.types import AvaResponse, TextBlock, ToolUseBlock
from avadex.usage import UsageTotals


def _resp(usage, model="gemma4", content=None, stop="end_turn"):
    return AvaResponse(content=content or [TextBlock(text="ok")], model=model,
                       stop_reason=stop, usage=usage)


# --- UsageTotals ---------------------------------------------------------

def test_sums_tokens_across_requests():
    u = UsageTotals()
    u.record(_resp({"input_tokens": 100, "output_tokens": 20}))
    u.record(_resp({"input_tokens": 150, "output_tokens": 30}))
    assert (u.input_tokens, u.output_tokens, u.requests) == (250, 50, 2)
    assert u.complete


def test_records_models_actually_used_in_order():
    u = UsageTotals()
    for m in ("gemma4", "qwen3:32b", "gemma4"):
        u.record(_resp({"input_tokens": 1, "output_tokens": 1}, model=m))
    assert u.models == ["gemma4", "qwen3:32b"]
    assert u.last_model == "gemma4"


def test_missing_or_zero_input_counts_mark_usage_incomplete():
    # A real request always has a system prompt, so input_tokens == 0 means
    # the server didn't count — don't let that masquerade as a free run.
    u = UsageTotals()
    u.record(_resp({"input_tokens": 10, "output_tokens": 5}))
    u.record(_resp({"input_tokens": 0, "output_tokens": 0}))
    assert not u.complete
    u2 = UsageTotals()
    u2.record(_resp({}))
    assert not u2.complete


def test_empty_totals_are_not_complete():
    assert not UsageTotals().complete


def test_as_dict_shape():
    u = UsageTotals()
    u.record(_resp({"input_tokens": 7, "output_tokens": 3}))
    assert u.as_dict() == {"input_tokens": 7, "output_tokens": 3}


# --- AgentLoop integration ------------------------------------------------

class SeqClient:
    def __init__(self, responses):
        self.responses = list(responses)

    def messages(self, **kw):
        return self.responses.pop(0)


def test_agent_loop_accumulates_usage_over_tool_round_trips(tmp_path):
    reg = ToolRegistry()
    reg.register(ToolDefinition(name="read_file", description="", input_schema={},
                                handler=lambda a: ToolResult(content="x")))
    client = SeqClient([
        _resp({"input_tokens": 100, "output_tokens": 10}, stop="tool_use",
              content=[ToolUseBlock(id="t1", name="read_file", input={"path": "a"})]),
        _resp({"input_tokens": 120, "output_tokens": 15}, model="qwen3:32b"),
    ])
    loop = AgentLoop(client=client, registry=reg,
                     permissions=PermissionManager(tmp_path / "allow.toml"),
                     system_prompt="s", max_context_tokens=10000)
    loop.run_turn("go", RecordingRenderer())
    assert loop.usage.input_tokens == 220
    assert loop.usage.output_tokens == 25
    assert loop.usage.requests == 2
    assert loop.usage.models == ["gemma4", "qwen3:32b"]
