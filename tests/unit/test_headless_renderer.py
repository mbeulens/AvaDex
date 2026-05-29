from avadex.renderer import HeadlessRenderer
from avadex.tools.registry import ToolResult


def test_text_accumulates_when_no_tools():
    r = HeadlessRenderer()
    r.assistant_text("hello ")
    r.assistant_text("world")
    assert r.text == "hello world"
    assert not r.errored


def test_only_final_answer_after_last_tool_call():
    # The agent narrates, calls a tool, then gives the final answer.
    # HeadlessRenderer drops the intermediate narration so the caller gets
    # only the final answer (= text emitted after the LAST tool call).
    r = HeadlessRenderer()
    r.assistant_text("Let me search.")
    r.tool_call("bash", {"cmd": "ls"})
    r.tool_result("bash", ToolResult(content="ok", is_error=False))
    r.assistant_text("Done. ")
    r.assistant_text("The answer is 42.")
    assert r.text == "Done. The answer is 42."


def test_tool_and_info_events_produce_no_stdout(capsys):
    r = HeadlessRenderer()
    r.tool_call("read_file", {"path": "x"})
    r.tool_result("read_file", ToolResult(content="contents", is_error=False))
    r.info("loading model...")
    out = capsys.readouterr()
    assert out.out == ""
    assert out.err == ""


def test_error_marks_errored_and_goes_to_stderr(capsys):
    r = HeadlessRenderer()
    r.error("max iterations reached without end_turn")
    out = capsys.readouterr()
    assert r.errored
    assert "max iterations" in out.err
    assert out.out == ""
