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


class StubAgentWithModels:
    def __init__(self, current="gemma4"):
        self.model = current
        self.turns = []
        self.messages = []
        self.client = self._FakeClient()

    def run_turn(self, text, renderer):
        pass

    def clear(self):
        pass

    class _FakeClient:
        def __init__(self):
            self.calls = 0

        def list_models(self):
            self.calls += 1
            return {
                "models": [
                    {"id": "gemma4:26b", "size": "16.2GB"},
                    {"id": "llama3.1:70b", "size": "42.1GB"},
                ],
                "default": "gemma4:26b",
            }


def test_model_no_arg_prints_current(capsys):
    agent = StubAgentWithModels(current="gemma4:26b")
    inputs = iter(["/model", "/exit"])
    repl = Repl(agent=agent, input_fn=lambda _: next(inputs))
    repl.run()
    out = capsys.readouterr().out
    assert "gemma4:26b" in out


def test_model_list_shows_all_with_marker(capsys):
    agent = StubAgentWithModels(current="llama3.1:70b")
    inputs = iter(["/model list", "/exit"])
    repl = Repl(agent=agent, input_fn=lambda _: next(inputs))
    repl.run()
    out = capsys.readouterr().out
    assert "gemma4:26b" in out
    assert "llama3.1:70b" in out
    # Marker on current model
    assert "* llama3.1:70b" in out


def test_model_switch_changes_agent_model(capsys):
    agent = StubAgentWithModels(current="gemma4:26b")
    inputs = iter(["/model llama3.1:70b", "/exit"])
    repl = Repl(agent=agent, input_fn=lambda _: next(inputs))
    repl.run()
    assert agent.model == "llama3.1:70b"


def test_model_unknown_shows_error_and_list(capsys):
    agent = StubAgentWithModels(current="gemma4:26b")
    inputs = iter(["/model nonexistent", "/exit"])
    repl = Repl(agent=agent, input_fn=lambda _: next(inputs))
    repl.run()
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "nonexistent" in combined.lower() or "no such" in combined.lower()


def test_model_pick_by_number_switches(capsys):
    agent = StubAgentWithModels(current="gemma4:26b")
    inputs = iter(["/model 2", "/exit"])
    repl = Repl(agent=agent, input_fn=lambda _: next(inputs))
    repl.run()
    # Position 2 in StubAgentWithModels' list is llama3.1:70b
    assert agent.model == "llama3.1:70b"


def test_model_pick_by_number_out_of_range(capsys):
    agent = StubAgentWithModels(current="gemma4:26b")
    inputs = iter(["/model 9", "/exit"])
    repl = Repl(agent=agent, input_fn=lambda _: next(inputs))
    repl.run()
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "position 9" in combined.lower() or "valid" in combined.lower()
    # Did NOT switch
    assert agent.model == "gemma4:26b"


def test_model_list_shows_numbered_entries(capsys):
    agent = StubAgentWithModels(current="gemma4:26b")
    inputs = iter(["/model list", "/exit"])
    repl = Repl(agent=agent, input_fn=lambda _: next(inputs))
    repl.run()
    out = capsys.readouterr().out
    assert "[1]" in out
    assert "[2]" in out
