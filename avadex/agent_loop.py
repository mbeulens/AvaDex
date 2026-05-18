from __future__ import annotations

from avadex.types import (
    TextBlock, ToolUseBlock, AvaResponse,
    block_to_dict, iter_tool_use_blocks,
)
from avadex.tools.registry import ToolRegistry, ToolResult
from avadex.permissions import PermissionManager
from avadex.context import prune
from avadex.renderer import Renderer

MAX_ITERATIONS = 25


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

        for _ in range(MAX_ITERATIONS):
            response: AvaResponse = self.client.messages(
                system=self.system_prompt,
                messages=self.messages,
                tools=self.registry.schemas(),
                max_tokens=self.max_response_tokens,
                model=self.model,
            )

            # Render any text blocks immediately
            for block in response.content:
                if isinstance(block, TextBlock) and block.text:
                    renderer.assistant_text(block.text)

            # Persist assistant turn
            self.messages.append({
                "role": "assistant",
                "content": self._serialize_response_content(response.content),
            })

            if response.stop_reason != "tool_use":
                return

            # Execute tools (Task 11 fills this in)
            tool_results = self._execute_tools(response.content, renderer)
            self.messages.append({"role": "user", "content": tool_results})

        renderer.error("max iterations reached without end_turn")

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
