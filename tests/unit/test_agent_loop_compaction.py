from avadex.renderer import RecordingRenderer
from avadex.tools.registry import ToolRegistry
from avadex.permissions import PermissionManager
from avadex.agent_loop import AgentLoop, COMPACTION_INSTRUCTION
from avadex.ava_client import AvaError
from avadex.types import AvaResponse, TextBlock


class SummClient:
    def messages(self, system, messages, tools, max_tokens=2048, model="gemma4"):
        return AvaResponse(content=[TextBlock(text="THE SUMMARY")],
                           model="gemma4", stop_reason="end_turn", usage={})


class BoomClient:
    def messages(self, system, messages, tools, max_tokens=2048, model="gemma4"):
        raise AvaError("boom")


def _loop(client, tmp_path, **kw):
    return AgentLoop(
        client=client, registry=ToolRegistry(),
        permissions=PermissionManager(tmp_path / "allow.toml"),
        system_prompt="", **kw,
    )


def test_summarize_extracts_text(tmp_path):
    loop = _loop(SummClient(), tmp_path, max_context_tokens=1000)
    assert loop._summarize([{"role": "user", "content": "x"}]) == "THE SUMMARY"


def test_summarize_returns_none_on_error(tmp_path):
    loop = _loop(BoomClient(), tmp_path, max_context_tokens=1000)
    assert loop._summarize([{"role": "user", "content": "x"}]) is None


def test_run_turn_compacts_long_history(tmp_path):
    class Client:
        def __init__(self):
            self.saw_summary_call = False
        def messages(self, system, messages, tools, max_tokens=2048, model="gemma4"):
            if messages and messages[-1].get("content") == COMPACTION_INSTRUCTION:
                self.saw_summary_call = True
                return AvaResponse(content=[TextBlock(text="SUMMARY")],
                                   model="gemma4", stop_reason="end_turn", usage={})
            return AvaResponse(content=[TextBlock(text="ok")],
                               model="gemma4", stop_reason="end_turn", usage={})

    client = Client()
    loop = _loop(client, tmp_path, max_context_tokens=2000,
                 compaction_threshold=0.5, keep_recent=2)
    loop.messages = [{"role": "user", "content": "x" * 4000} for _ in range(6)]
    loop.run_turn("new question", RecordingRenderer())
    assert client.saw_summary_call
