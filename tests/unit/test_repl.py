from avadex.repl import Repl, AnsiRenderer
from avadex.tools.registry import ToolResult


class StubAgent:
    def __init__(self):
        self.turns = []
        self.messages = []
    def run_turn(self, text, renderer):
        self.turns.append(text)
        renderer.assistant_text(f"echo: {text}")
    def clear(self):
        self.turns.clear()


def test_repl_runs_until_quit():
    agent = StubAgent()
    inputs = iter(["hello", "world", "/exit"])
    repl = Repl(agent=agent, input_fn=lambda prompt: next(inputs))
    repl.run()
    assert agent.turns == ["hello", "world"]


def test_repl_clear_command_resets_agent():
    agent = StubAgent()
    agent.run_turn("seed", AnsiRenderer())
    inputs = iter(["/clear", "/exit"])
    repl = Repl(agent=agent, input_fn=lambda prompt: next(inputs))
    repl.run()
    assert agent.turns == []


def test_repl_tools_command_prints_tool_names(capsys):
    agent = StubAgent()
    # Stand-in registry; we'll attach to the agent for the test
    class Reg:
        def names(self):
            return ["read_file", "bash"]
    agent.registry = Reg()
    inputs = iter(["/tools", "/exit"])
    repl = Repl(agent=agent, input_fn=lambda prompt: next(inputs))
    repl.run()
    captured = capsys.readouterr().out
    assert "read_file" in captured
    assert "bash" in captured


def test_ansi_renderer_prints_assistant_text(capsys):
    r = AnsiRenderer()
    r.assistant_text("hi")
    out = capsys.readouterr().out
    assert "hi" in out


def test_ansi_renderer_tool_call_has_marker(capsys):
    r = AnsiRenderer()
    r.tool_call("bash", {"command": "ls"})
    out = capsys.readouterr().out
    assert "●" in out
    assert "bash" in out


def test_ansi_renderer_error_prefix(capsys):
    r = AnsiRenderer()
    r.error("boom")
    captured = capsys.readouterr()
    # error goes to stderr; check via capsys
    assert "boom" in captured.out.lower() or "boom" in captured.err.lower()
