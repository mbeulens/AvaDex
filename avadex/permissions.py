from __future__ import annotations
import fnmatch
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

try:
    import tomllib as _tomli   # Python 3.11+
except ImportError:
    import tomli as _tomli

import tomli_w


class Decision(Enum):
    AUTO_ALLOW = "auto_allow"
    PROMPT = "prompt"
    AUTO_DENY = "auto_deny"


READ_ONLY_TOOLS = {"read_file", "load_skill", "attach_image"}


@dataclass
class Rule:
    tool: str
    pattern: str


def _tool_argument(tool_name: str, args: dict) -> str:
    """The 'subject' of the tool call that patterns match against."""
    if tool_name == "bash":
        return args.get("command", "")
    if tool_name in ("read_file", "write_file", "edit_file", "attach_image"):
        return args.get("path", "")
    # MCP tools: stringify args for matching
    return str(args)


class PermissionManager:
    def __init__(self, allowlist_path: Path):
        self.path = Path(allowlist_path)
        self.rules: list[Rule] = self._load()

    def _load(self) -> list[Rule]:
        if not self.path.exists():
            return []
        with open(self.path, "rb") as f:
            data = _tomli.load(f)
        return [Rule(tool=r["tool"], pattern=r["pattern"]) for r in data.get("rules", [])]

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"rules": [{"tool": r.tool, "pattern": r.pattern} for r in self.rules]}
        with open(self.path, "wb") as f:
            tomli_w.dump(payload, f)

    def add_rule(self, rule: Rule):
        self.rules.append(rule)
        self._save()

    def check(self, tool_name: str, args: dict) -> Decision:
        subject = _tool_argument(tool_name, args)
        for r in self.rules:
            if r.tool == tool_name and fnmatch.fnmatchcase(subject, r.pattern):
                return Decision.AUTO_ALLOW
        if tool_name in READ_ONLY_TOOLS:
            return Decision.AUTO_ALLOW
        return Decision.PROMPT
