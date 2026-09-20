"""Every request AvaDex sends carries a user text message.

Conductor hit an Ava 400 ("requires at least one user message with text") on a
long run at 1.2.0: something upstream had left the conversation with tool
results only. Whatever the cause, the agent loop must not send such a request.
"""
import contextlib
import logging

from avadex.agent_loop import AgentLoop
from avadex.context import _has_text
from avadex.permissions import PermissionManager, Rule
from avadex.renderer import RecordingRenderer
from avadex.tools.registry import ToolRegistry, ToolDefinition, ToolResult
from avadex.types import AvaResponse, TextBlock, ToolUseBlock


def _loop(tmp_path, client, **kw):
    reg = ToolRegistry()
    reg.register(ToolDefinition(name="f", description="", input_schema={},
                                handler=lambda a: ToolResult(content="r")))
    pm = PermissionManager(tmp_path / "a.toml")
    pm.add_rule(Rule(tool="f", pattern="*"))
    return AgentLoop(client=client, registry=reg, permissions=pm,
                     system_prompt="", max_context_tokens=100000, **kw)


class Recorder:
    def __init__(self):
        self.sent = []
    def messages(self, system, messages, tools, max_tokens=2048, model="m"):
        self.sent.append(list(messages))
        return AvaResponse(content=[TextBlock(text="ok")], model="m",
                           stop_reason="end_turn", usage={})


def test_request_is_re_anchored_when_the_task_went_missing(tmp_path, monkeypatch):
    client = Recorder()
    loop = _loop(tmp_path, client)
    # Simulate whatever upstream loss Conductor hit: context management hands
    # back a conversation whose user turns are tool_results only.
    monkeypatch.setattr(loop, "_fit", lambda: [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t0", "name": "f", "input": {}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t0", "content": "r"}]},
    ])
    renderer = RecordingRenderer()
    loop.run_turn("build the form set", renderer)
    sent = client.sent[0]
    assert any(m["role"] == "user" and _has_text(m) for m in sent)
    # The task itself comes back, not a placeholder.
    assert any("build the form set" in str(m["content"]) for m in sent)


def test_re_anchoring_is_reported_not_silent(tmp_path, monkeypatch):
    client = Recorder()
    loop = _loop(tmp_path, client)
    monkeypatch.setattr(loop, "_fit", lambda: [
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t0", "content": "r"}]},
    ])
    renderer = RecordingRenderer()
    loop.run_turn("the task", renderer)
    assert any(e[0] == "info" and "task" in e[1].lower() for e in renderer.events), renderer.events


def test_normal_runs_are_untouched(tmp_path):
    client = Recorder()
    loop = _loop(tmp_path, client)
    renderer = RecordingRenderer()
    loop.run_turn("hello", renderer)
    assert client.sent[0] == [{"role": "user", "content": "hello"}]


class _Capture(logging.Handler):
    """The avadex logger tree doesn't propagate to root, so capture directly."""
    def __init__(self, level):
        super().__init__(level)
        self.records = []
    def emit(self, record):
        self.records.append(record)
    def text(self, level=None):
        return "\n".join(r.getMessage() for r in self.records
                          if level is None or r.levelno == level)


@contextlib.contextmanager
def capture_at(level):
    logger = logging.getLogger("avadex")
    handler = _Capture(level)
    old = logger.level
    logger.setLevel(level)
    logger.addHandler(handler)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old)


def _loop_losing_the_task(tmp_path, monkeypatch, content):
    client = Recorder()
    loop = _loop(tmp_path, client)
    monkeypatch.setattr(loop, "_fit", lambda: [
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t0", "content": content}]},
    ])
    return loop


def test_debug_log_carries_the_full_messages(tmp_path, monkeypatch):
    # With --debug the dump may hold real content: it goes to the user's own
    # debug.log, and without it there is nothing to diagnose.
    loop = _loop_losing_the_task(tmp_path, monkeypatch, "SECRET-PAYLOAD")
    with capture_at(logging.DEBUG) as cap:
        loop.run_turn("the task", RecordingRenderer())
    assert "SECRET-PAYLOAD" in cap.text(logging.DEBUG)


def test_without_debug_no_content_is_logged(tmp_path, monkeypatch):
    loop = _loop_losing_the_task(tmp_path, monkeypatch, "SECRET-PAYLOAD")
    with capture_at(logging.WARNING) as cap:
        loop.run_turn("the task", RecordingRenderer())
    assert "SECRET-PAYLOAD" not in cap.text()
    assert "re-anchoring" in cap.text()      # the shape line still appears


def test_image_payloads_are_not_dumped(tmp_path, monkeypatch):
    loop = _loop_losing_the_task(tmp_path, monkeypatch, [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                     "data": "BASE64IMAGEDATA"}}])
    with capture_at(logging.DEBUG) as cap:
        loop.run_turn("the task", RecordingRenderer())
    assert "BASE64IMAGEDATA" not in cap.text()
