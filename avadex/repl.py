from __future__ import annotations
import sys
from typing import Callable, Optional

from avadex.tools.registry import ToolResult


class AnsiRenderer:
    """Bare-ANSI renderer used by the REPL. Keeps stdout clean (one
    line per event) so it's easy to test with capsys."""
    BULLET = "●"

    def assistant_text(self, text: str):
        print(text)

    def tool_call(self, name: str, args: dict):
        summary = ", ".join(f"{k}={self._brief(v)}" for k, v in args.items())
        print(f"{self.BULLET} {name}({summary})")

    def tool_result(self, name: str, result: ToolResult):
        if result.is_error:
            print(f"  ✗ {result.content}")
        else:
            preview = result.content.splitlines()[0][:80] if result.content else "(empty)"
            print(f"  → {preview}")

    def info(self, text: str):
        print(f"[info] {text}")

    def error(self, text: str):
        print(f"[error] {text}", file=sys.stderr)

    @staticmethod
    def _brief(v):
        s = str(v)
        return s if len(s) <= 60 else s[:57] + "..."


class Repl:
    PROMPT = "Ava> "

    def __init__(
        self,
        agent,
        input_fn: Optional[Callable[[str], str]] = None,
        prompt_user: Optional[Callable[[str, dict], tuple]] = None,
    ):
        self.agent = agent
        self.renderer = AnsiRenderer()
        self.input_fn = input_fn or self._default_input
        # If the agent supports prompt_user, wire it
        if prompt_user is not None and hasattr(agent, "prompt_user"):
            agent.prompt_user = prompt_user

    @staticmethod
    def _default_input(prompt: str) -> str:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import FileHistory
        from pathlib import Path
        hist_path = Path.home() / ".local/state/avadex/history"
        hist_path.parent.mkdir(parents=True, exist_ok=True)
        session = PromptSession(history=FileHistory(str(hist_path)))
        return session.prompt(prompt, multiline=False)

    def run(self):
        while True:
            try:
                line = self.input_fn(self.PROMPT).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return
            if not line:
                continue
            if line.startswith("/"):
                if self._handle_slash(line):
                    return
                continue
            try:
                self.agent.run_turn(line, self.renderer)
            except KeyboardInterrupt:
                self.renderer.info("interrupted")

    def _handle_slash(self, line: str) -> bool:
        cmd, _, _arg = line[1:].partition(" ")
        if cmd in ("exit", "quit"):
            return True
        if cmd == "clear":
            self.agent.clear()
            self.renderer.info("conversation cleared")
            return False
        if cmd == "tools":
            registry = getattr(self.agent, "registry", None)
            names = registry.names() if registry else []
            self.renderer.info("tools: " + ", ".join(names) if names else "no tools")
            return False
        if cmd == "allow":
            arg = _arg.strip()
            if " " not in arg:
                self.renderer.error("usage: /allow <tool> <pattern>")
                return False
            tool, _, pattern = arg.partition(" ")
            permissions = getattr(self.agent, "permissions", None)
            if permissions is None:
                self.renderer.error("no permission manager wired")
                return False
            from avadex.permissions import Rule
            permissions.add_rule(Rule(tool=tool, pattern=pattern.strip()))
            self.renderer.info(f"added: {tool} {pattern}")
            return False
        self.renderer.error(f"unknown command: /{cmd}")
        return False


def build_terminal_prompter(input_fn=None):
    """Return a callable(tool_name, args) -> (answer, pattern_or_None).

    answer ∈ {'yes', 'always', 'deny'}; pattern is set only for 'always'.
    """
    _input = input_fn or input
    def prompter(tool_name: str, args: dict):
        subject = args.get("command") or args.get("path") or str(args)
        print(f"  Run: {tool_name}({subject})")
        choice = _input("  [y]es / [n]o / [a]lways ? ").strip().lower()
        if choice in ("y", "yes"):
            return ("yes", None)
        if choice in ("a", "always"):
            pattern = _input(f"  Pattern for {tool_name} (glob): ").strip() or "*"
            return ("always", pattern)
        if choice in ("n", "no"):
            return ("deny", None)
        return ("deny", None)
    return prompter
