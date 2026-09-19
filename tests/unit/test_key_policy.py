import pytest

from avadex.agent_loop import AgentLoop
from avadex.ava_client import AvaError
from avadex.key_policy import KeyNotPrivate, PolicyTracker, is_private
from avadex.permissions import PermissionManager
from avadex.renderer import RecordingRenderer
from avadex.tools.registry import ToolDefinition, ToolRegistry, ToolResult
from avadex.types import AvaResponse, TextBlock, ToolUseBlock, parse_response

PRIVATE = {"key": "c", "private": True, "rag": False, "retained": False}
SHARED = {"key": "c", "private": False, "rag": True, "retained": True}


def test_parse_response_keeps_ava_block():
    r = parse_response({"content": [], "model": "m", "stop_reason": "end_turn", "ava": PRIVATE})
    assert r.ava == PRIVATE
    assert parse_response({"content": []}).ava is None


def test_is_private_only_for_exact_true():
    assert is_private(PRIVATE)
    for block in (SHARED, None, {}, {"private": "true"}, {"private": 1}):
        assert not is_private(block)


def test_tracker_reports_last_block_and_no_change():
    t = PolicyTracker()
    t.record(PRIVATE)
    t.record(dict(PRIVATE))
    assert t.last == PRIVATE
    assert not t.changed


def test_tracker_flags_a_flip_mid_run():
    t = PolicyTracker()
    t.record(PRIVATE)
    t.record(SHARED)
    assert t.changed
    assert t.last == SHARED


def test_tracker_flags_a_block_that_disappears():
    t = PolicyTracker()
    t.record(PRIVATE)
    t.record(None)
    assert t.changed
    assert t.last is None


def test_key_not_private_is_an_ava_error():
    assert issubclass(KeyNotPrivate, AvaError)


# --- AgentLoop ------------------------------------------------------------

class SeqClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def messages(self, **kw):
        self.calls += 1
        return self.responses.pop(0)


def _resp(ava, content=None, stop="end_turn"):
    return AvaResponse(content=content or [TextBlock(text="ok")], model="m",
                       stop_reason=stop, usage={"input_tokens": 1, "output_tokens": 1}, ava=ava)


def _loop(tmp_path, client, ran, require_private):
    reg = ToolRegistry()
    reg.register(ToolDefinition(name="read_file", description="", input_schema={},
                                handler=lambda a: ran.append(a) or ToolResult(content="x")))
    return AgentLoop(client=client, registry=reg,
                     permissions=PermissionManager(tmp_path / "allow.toml"),
                     system_prompt="s", max_context_tokens=10000,
                     require_private=require_private)


def test_require_private_aborts_before_running_tools_of_a_shared_response(tmp_path):
    ran = []
    client = SeqClient([
        _resp(PRIVATE, stop="tool_use",
              content=[ToolUseBlock(id="t1", name="read_file", input={"path": "a"})]),
        _resp(SHARED, stop="tool_use",
              content=[ToolUseBlock(id="t2", name="read_file", input={"path": "b"})]),
        _resp(PRIVATE),
    ])
    loop = _loop(tmp_path, client, ran, require_private=True)
    renderer = RecordingRenderer()
    loop.run_turn("go", renderer)
    assert ran == [{"path": "a"}]          # the shared response's tool never ran
    assert client.calls == 2               # and no further request was sent
    errors = [e for e in renderer.events if e[0] == "error"]
    assert errors and "not private" in errors[0][1]
    assert loop.policy.changed


def test_without_require_private_a_flip_is_only_recorded(tmp_path):
    ran = []
    client = SeqClient([_resp(PRIVATE, stop="tool_use",
                              content=[ToolUseBlock(id="t1", name="read_file", input={"path": "a"})]),
                        _resp(SHARED)])
    loop = _loop(tmp_path, client, ran, require_private=False)
    loop.run_turn("go", RecordingRenderer())
    assert ran == [{"path": "a"}]
    assert loop.policy.changed
    assert loop.policy.last == SHARED


def test_require_private_rejects_a_missing_block(tmp_path):
    client = SeqClient([_resp(None)])
    loop = _loop(tmp_path, client, [], require_private=True)
    renderer = RecordingRenderer()
    loop.run_turn("go", renderer)
    assert any(e[0] == "error" for e in renderer.events)


def test_require_private_stops_at_a_shared_compaction_response(tmp_path):
    # Compaction is its own Ava request; a non-private answer to it must stop
    # the run before the main request is sent.
    from avadex.agent_loop import COMPACTION_INSTRUCTION

    class Client:
        def __init__(self):
            self.main_calls = 0

        def messages(self, system, messages, tools, max_tokens=2048, model="m"):
            if messages and messages[-1].get("content") == COMPACTION_INSTRUCTION:
                return _resp(SHARED, content=[TextBlock(text="SUMMARY")])
            self.main_calls += 1
            return _resp(PRIVATE)

    client = Client()
    loop = AgentLoop(client=client, registry=ToolRegistry(),
                     permissions=PermissionManager(tmp_path / "allow.toml"),
                     system_prompt="", max_context_tokens=2000,
                     compaction_threshold=0.5, keep_recent=2, require_private=True)
    loop.messages = [{"role": "user", "content": "x" * 4000} for _ in range(6)]
    renderer = RecordingRenderer()
    loop.run_turn("new question", renderer)
    assert client.main_calls == 0
    assert any(e[0] == "error" and "not private" in e[1] for e in renderer.events)
