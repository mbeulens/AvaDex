"""Under --debug, every request records its shape — not just the failing ones.

Two of Conductor's 400s left nothing to diagnose because the shape line was
written only when the guard re-anchored. When the guard stays quiet and Ava
rejects the request anyway, the trail has to already be there.
"""
import contextlib
import logging

from avadex.agent_loop import AgentLoop
from avadex.permissions import PermissionManager, Rule
from avadex.renderer import RecordingRenderer
from avadex.tools.registry import ToolRegistry, ToolDefinition, ToolResult
from avadex.types import AvaResponse, TextBlock


class _Capture(logging.Handler):
    """The avadex logger tree doesn't propagate to root, so capture directly."""
    def __init__(self, level):
        super().__init__(level)
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def text(self):
        return "\n".join(r.getMessage() for r in self.records)


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


class Recorder:
    def messages(self, system, messages, tools, max_tokens=2048, model="m"):
        return AvaResponse(content=[TextBlock(text="ok")], model="m",
                           stop_reason="end_turn", usage={})


def _loop(tmp_path):
    reg = ToolRegistry()
    reg.register(ToolDefinition(name="f", description="", input_schema={},
                                handler=lambda a: ToolResult(content="r")))
    pm = PermissionManager(tmp_path / "a.toml")
    pm.add_rule(Rule(tool="f", pattern="*"))
    return AgentLoop(client=Recorder(), registry=reg, permissions=pm,
                     system_prompt="", max_context_tokens=100000)


def test_every_request_records_its_shape(tmp_path):
    loop = _loop(tmp_path)
    with capture_at(logging.DEBUG) as cap:
        loop.run_turn("build the form set", RecordingRenderer())
    assert "request shape" in cap.text()
    assert "('user', 'text')" in cap.text()


def test_the_task_length_is_recorded_at_the_start_of_a_turn(tmp_path):
    loop = _loop(tmp_path)
    with capture_at(logging.DEBUG) as cap:
        loop.run_turn("build the form set", RecordingRenderer())   # 18 chars
    assert "task 18 chars" in cap.text()


def test_the_shape_log_carries_no_content(tmp_path):
    # The re-anchor dump may hold content by design; this line never does, so
    # it is safe on every request rather than only on a failure.
    loop = _loop(tmp_path)
    with capture_at(logging.DEBUG) as cap:
        loop.run_turn("SECRET-TASK-TEXT", RecordingRenderer())
    assert "SECRET-TASK-TEXT" not in cap.text()
