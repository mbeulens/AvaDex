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
