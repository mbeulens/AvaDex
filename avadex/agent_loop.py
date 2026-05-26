from __future__ import annotations

from avadex.types import (
    TextBlock, ToolUseBlock, AvaResponse,
    block_to_dict, iter_tool_use_blocks,
)
from avadex.tools.registry import ToolRegistry, ToolResult
from avadex.permissions import PermissionManager
from avadex.context import prune
from avadex.ava_client import ContextOverflow, AvaError, TokenExpired
from avadex.renderer import Renderer
from avadex.spinner import Spinner

MAX_ITERATIONS = 25


def _unexecuted_tool_call_name(text: str, tool_names) -> "str | None":
    """If `text` is just a tool-call-shaped JSON object naming a known tool,
    return that tool name; otherwise None.

    Detects models that can't do native tool-calling and instead emit the call
    as plain text (e.g. `{"name": "write_file", "arguments": {...}}`), which
    never executes. Conservative: only fires when the text IS the JSON object,
    so it won't nag on normal answers."""
    import json
    s = text.strip()
    if s.startswith("```"):
        s = s.strip("`").strip()
        if s[:4].lower() == "json":
            s = s[4:].strip()
    if not (s.startswith("{") and s.endswith("}")):
        return None
    try:
        obj = json.loads(s)
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None
    name = obj.get("name")
    has_args = any(isinstance(obj.get(k), dict) for k in ("arguments", "parameters", "input"))
    if isinstance(name, str) and name in set(tool_names) and has_args:
        return name
    return None


class AgentLoop:
    def __init__(
        self,
        client,
        registry: ToolRegistry,
        permissions: PermissionManager,
        system_prompt: str,
        max_context_tokens: int = 3500,
        max_response_tokens: int = 2048,
        model: str = "gemma4",
        prompt_user=None,
    ):
        self.client = client
        self.registry = registry
        self.permissions = permissions
        self.system_prompt = system_prompt
        self.max_context_tokens = max_context_tokens
        self.max_response_tokens = max_response_tokens
        self.model = model
        self.messages: list[dict] = []
        self.prompt_user = prompt_user or (lambda tool, args: ("deny", None))

    def clear(self):
        self.messages = []

    def _serialize_response_content(self, content: list) -> list[dict]:
        return [block_to_dict(b) for b in content]

    def run_turn(self, user_text: str, renderer: Renderer) -> None:
        self.messages.append({"role": "user", "content": user_text})
        self.messages = prune(self.messages, max_tokens=self.max_context_tokens)
        recent_signatures: list[str] = []

        for _ in range(MAX_ITERATIONS):
            try:
                try:
                    with Spinner():
                        response: AvaResponse = self.client.messages(
                            system=self.system_prompt,
                            messages=self.messages,
                            tools=self.registry.schemas(),
                            max_tokens=self.max_response_tokens,
                            model=self.model,
                        )
                except ContextOverflow:
                    # Drop two oldest pairs (4 messages) and retry once
                    self.messages = self.messages[4:] if len(self.messages) > 4 else self.messages[-1:]
                    try:
                        with Spinner():
                            response = self.client.messages(
                                system=self.system_prompt,
                                messages=self.messages,
                                tools=self.registry.schemas(),
                                max_tokens=self.max_response_tokens,
                                model=self.model,
                            )
                    except ContextOverflow:
                        renderer.error("context too full even after pruning; run /clear")
                        return
            except TokenExpired:
                renderer.error("token rejected by Ava — run 'avadex login'")
                return
            except AvaError as exc:
                renderer.error(str(exc))
                return

            for block in response.content:
                if isinstance(block, TextBlock) and block.text:
                    renderer.assistant_text(block.text)

            serialized = self._serialize_response_content(response.content)
            self.messages.append({"role": "assistant", "content": serialized})

            if response.stop_reason != "tool_use":
                self._warn_if_tool_call_as_text(response.content, renderer)
                return

            # Detect 3-in-a-row identical assistant turns.
            # Strip volatile tool_use_id before comparing so different
            # incarnations of the same call still count as identical.
            signature = self._signature_for_repeat_detection(response.content)
            recent_signatures.append(signature)
            if len(recent_signatures) >= 3 and len(set(recent_signatures[-3:])) == 1:
                renderer.error("repeated output detected — aborting to avoid infinite loop")
                return

            tool_results = self._execute_tools(response.content, renderer)
            self.messages.append({"role": "user", "content": tool_results})

        renderer.error("max iterations reached without end_turn")

    def _warn_if_tool_call_as_text(self, content: list, renderer: Renderer) -> None:
        names = set(self.registry.names())
        for block in content:
            if isinstance(block, TextBlock) and block.text:
                tool = _unexecuted_tool_call_name(block.text, names)
                if tool is not None:
                    renderer.error(
                        f"model '{self.model}' returned a '{tool}' tool call as text "
                        f"— it was NOT executed. If this model should support tools, "
                        f"re-pull it (ollama pull) or update Ollama; otherwise switch "
                        f"with /model."
                    )
                    return

    def _signature_for_repeat_detection(self, content: list) -> str:
        """Build a stable string from response content for loop detection.
        Excludes tool_use_id (volatile across calls) but includes name+input."""
        import json
        parts = []
        for block in content:
            if isinstance(block, TextBlock):
                parts.append(("text", block.text))
            elif isinstance(block, ToolUseBlock):
                parts.append(("tool_use", block.name, json.dumps(block.input, sort_keys=True)))
        return json.dumps(parts, sort_keys=True)

    def _execute_tools(self, content: list, renderer: Renderer) -> list[dict]:
        from avadex.permissions import Decision, Rule
        results: list[dict] = []
        for block in iter_tool_use_blocks(content):
            renderer.tool_call(block.name, block.input)
            decision = self.permissions.check(block.name, block.input)
            if decision == Decision.PROMPT:
                answer, pattern = self.prompt_user(block.name, block.input)
                if answer == "yes":
                    decision = Decision.AUTO_ALLOW
                elif answer == "always":
                    self.permissions.add_rule(Rule(tool=block.name, pattern=pattern or "*"))
                    decision = Decision.AUTO_ALLOW
                else:
                    decision = Decision.AUTO_DENY

            if decision == Decision.AUTO_DENY:
                result = ToolResult(content="denied by user", is_error=True)
            else:
                result = self.registry.dispatch(block.name, block.input)

            renderer.tool_result(block.name, result)
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result.content,
                "is_error": result.is_error,
            })
        return results
