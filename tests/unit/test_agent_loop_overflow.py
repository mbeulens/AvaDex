from avadex.renderer import RecordingRenderer
from avadex.tools.registry import ToolRegistry
from avadex.permissions import PermissionManager
from avadex.agent_loop import AgentLoop
from avadex.ava_client import AvaError, ContextOverflow, TokenExpired
from avadex.types import AvaResponse, TextBlock


class FlakyClient:
    """Raises ContextOverflow once, then succeeds."""
    def __init__(self):
        self.raised = False
        self.calls = []
    def messages(self, system, messages, tools, max_tokens=2048, model="gemma4"):
        self.calls.append(len(messages))
        if not self.raised:
            self.raised = True
            raise ContextOverflow("context length exceeded")
        return AvaResponse(content=[TextBlock(text="ok")], model="gemma4",
                           stop_reason="end_turn", usage={})


def test_context_overflow_drops_oldest_and_retries(tmp_path):
    client = FlakyClient()
    loop = AgentLoop(
        client=client, registry=ToolRegistry(),
        permissions=PermissionManager(tmp_path / "allow.toml"),
        system_prompt="", max_context_tokens=100000,
    )
    # Pre-load some history
    loop.messages = [
        {"role": "user", "content": "old1"},
        {"role": "assistant", "content": "old1r"},
        {"role": "user", "content": "old2"},
        {"role": "assistant", "content": "old2r"},
    ]
    renderer = RecordingRenderer()
    loop.run_turn("new", renderer)
    # First attempt had 5 messages (old + new user); after overflow, second attempt has fewer
    assert client.calls[0] == 5
    assert client.calls[1] < client.calls[0]
    assert ("assistant_text", "ok") in renderer.events


def test_persistent_overflow_aborts(tmp_path):
    class AlwaysOverflow:
        def messages(self, system, messages, tools, max_tokens=2048, model="gemma4"):
            raise ContextOverflow("nope")
    loop = AgentLoop(
        client=AlwaysOverflow(), registry=ToolRegistry(),
        permissions=PermissionManager(tmp_path / "allow.toml"),
        system_prompt="", max_context_tokens=100000,
    )
    renderer = RecordingRenderer()
    loop.run_turn("hi", renderer)
    assert any(e[0] == "error" and "context" in e[1].lower() for e in renderer.events)


class FailingClient:
    """Raises a given exception on every call."""
    def __init__(self, exc):
        self.exc = exc
    def messages(self, system, messages, tools, max_tokens=2048, model="gemma4"):
        raise self.exc


def test_ava_error_renders_error_and_returns(tmp_path):
    client = FailingClient(AvaError("HTTP 500: boom"))
    loop = AgentLoop(
        client=client, registry=ToolRegistry(),
        permissions=PermissionManager(tmp_path / "allow.toml"),
        system_prompt="", max_context_tokens=100000,
    )
    renderer = RecordingRenderer()
    loop.run_turn("hi", renderer)
    assert any(e[0] == "error" and "500" in e[1] for e in renderer.events)


def test_token_expired_renders_login_prompt(tmp_path):
    client = FailingClient(TokenExpired("token rejected"))
    loop = AgentLoop(
        client=client, registry=ToolRegistry(),
        permissions=PermissionManager(tmp_path / "allow.toml"),
        system_prompt="", max_context_tokens=100000,
    )
    renderer = RecordingRenderer()
    loop.run_turn("hi", renderer)
    assert any(e[0] == "error" and "login" in e[1].lower() for e in renderer.events)


def test_overflow_retry_keeps_the_task_and_tool_pairs(tmp_path):
    # An agent run: the task, then tool steps. The retry after an overflow must
    # keep the task (the only user text) and never split a tool_use from its
    # tool_result, or the retried request is invalid.
    client = FlakyClient()
    seen = []
    orig = client.messages
    def record(system, messages, tools, max_tokens=2048, model="gemma4"):
        seen.append([dict(m) for m in messages])
        return orig(system, messages, tools, max_tokens, model)
    client.messages = record
    loop = AgentLoop(
        client=client, registry=ToolRegistry(),
        permissions=PermissionManager(tmp_path / "allow.toml"),
        system_prompt="", max_context_tokens=100000,
    )
    steps = []
    for i in range(3):
        steps += [
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": f"t{i}", "name": "x", "input": {}}]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": f"t{i}", "content": "r"}]},
        ]
    loop.messages = [{"role": "user", "content": "the task"}] + steps
    # run_turn appends its own user text; drive the retry from a tool step instead
    loop.messages.append({"role": "assistant", "content": [
        {"type": "tool_use", "id": "t9", "name": "x", "input": {}}]})
    loop.messages.append({"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t9", "content": "r"}]})
    renderer = RecordingRenderer()
    loop.run_turn("continue", renderer)
    retried = seen[1]
    assert len(retried) < len(seen[0])
    assert any(m["role"] == "user" and m["content"] == "continue" for m in retried)
    uses = {b["id"] for m in retried if isinstance(m["content"], list)
            for b in m["content"] if b.get("type") == "tool_use"}
    results = {b["tool_use_id"] for m in retried if isinstance(m["content"], list)
               for b in m["content"] if b.get("type") == "tool_result"}
    assert uses == results


def test_overflow_retry_in_a_tool_loop_keeps_the_task(tmp_path):
    # Mid-run the newest message is a tool_result, and the task is the first
    # message. Dropping the first four messages would drop the task.
    from avadex.context import drop_oldest
    msgs = [{"role": "user", "content": "the task"}]
    for i in range(3):
        msgs += [
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": f"t{i}", "name": "x", "input": {}}]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": f"t{i}", "content": "r"}]},
        ]
    out = drop_oldest(msgs, 4)
    assert out[0] == {"role": "user", "content": "the task"}
    assert out[-1] == msgs[-1]
    assert len(out) == 3   # task + the last tool pair; two pairs dropped
