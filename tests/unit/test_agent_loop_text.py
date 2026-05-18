from avadex.renderer import RecordingRenderer
from avadex.tools.registry import ToolRegistry
from avadex.permissions import PermissionManager
from avadex.agent_loop import AgentLoop


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []
    def messages(self, system, messages, tools, max_tokens=2048, model="gemma4"):
        self.calls.append({"system": system, "messages": list(messages), "tools": tools})
        return self.response


def make_response(text):
    from avadex.types import AvaResponse, TextBlock
    return AvaResponse(
        content=[TextBlock(text=text)], model="gemma4", stop_reason="end_turn", usage={}
    )


def test_text_only_turn(tmp_path):
    client = FakeClient(make_response("Hello!"))
    renderer = RecordingRenderer()
    loop = AgentLoop(
        client=client,
        registry=ToolRegistry(),
        permissions=PermissionManager(tmp_path / "allow.toml"),
        system_prompt="be helpful",
        max_context_tokens=10000,
    )
    loop.run_turn("hi", renderer)

    assert renderer.events == [("assistant_text", "Hello!")]
    assert len(client.calls) == 1
    assert client.calls[0]["messages"] == [{"role": "user", "content": "hi"}]
    assert client.calls[0]["system"] == "be helpful"


def test_text_only_turn_appends_history(tmp_path):
    client = FakeClient(make_response("ok"))
    loop = AgentLoop(
        client=client,
        registry=ToolRegistry(),
        permissions=PermissionManager(tmp_path / "allow.toml"),
        system_prompt="",
        max_context_tokens=10000,
    )
    loop.run_turn("first", RecordingRenderer())
    loop.run_turn("second", RecordingRenderer())
    # Second call sees both turns of history
    assert client.calls[1]["messages"] == [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
        {"role": "user", "content": "second"},
    ]
