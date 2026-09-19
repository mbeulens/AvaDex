"""HeadlessRenderer.transcript: every tool call and what it returned, verbatim."""
from avadex.renderer import HeadlessRenderer
from avadex.tools.registry import ToolResult


def test_empty_without_tool_calls():
    r = HeadlessRenderer()
    r.assistant_text("hi")
    assert r.transcript == []


def test_call_and_result_recorded_verbatim_in_order():
    big = "x" * 50_000   # no truncation: the caller parses this, not a person
    r = HeadlessRenderer()
    r.tool_call("read_file", {"path": "a"})
    r.tool_result("read_file", ToolResult(content=big))
    r.tool_call("glob", {"pattern": "*"})
    r.tool_result("glob", ToolResult(content="b\nc"))
    assert r.transcript == [
        {"tool": "read_file", "input": {"path": "a"}, "output": big,
         "is_error": False, "status": "ok"},
        {"tool": "glob", "input": {"pattern": "*"}, "output": "b\nc",
         "is_error": False, "status": "ok"},
    ]


def test_failed_call_is_flagged_not_dropped():
    r = HeadlessRenderer()
    r.tool_call("bash", {"command": "ls"})
    r.tool_result("bash", ToolResult(content="denied by user", is_error=True))
    assert r.transcript == [{"tool": "bash", "input": {"command": "ls"},
                             "output": "denied by user", "is_error": True,
                             "status": "error"}]


def test_call_without_result_has_null_output():
    r = HeadlessRenderer()
    r.tool_call("form_list", {})
    assert r.transcript == [{"tool": "form_list", "input": {}, "output": None,
                             "is_error": None, "status": "no_result"}]


def test_skipped_call_is_recorded_as_not_run():
    r = HeadlessRenderer()
    r.tool_skipped("loop", {"n": 1}, "repeated output detected")
    assert r.transcript == [{"tool": "loop", "input": {"n": 1}, "output": None,
                             "is_error": None, "status": "not_run",
                             "reason": "repeated output detected"}]


def test_image_blocks_are_summarised_text_kept():
    r = HeadlessRenderer()
    r.tool_call("attach_image", {"path": "g.png"})
    r.tool_result("attach_image", ToolResult(content=[
        {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                     "data": "QUJDRA=="}},
        {"type": "text", "text": "attached g.png"},
    ]))
    assert r.transcript[0]["output"] == [
        {"type": "image", "media_type": "image/png", "bytes": 4},
        {"type": "text", "text": "attached g.png"},
    ]


def test_transcript_is_a_snapshot():
    # Mutating the returned list or an input dict must not change the record.
    args = {"path": "a"}
    r = HeadlessRenderer()
    r.tool_call("read_file", args)
    args["path"] = "changed"
    r.transcript.clear()
    assert r.transcript[0]["input"] == {"path": "a"}
