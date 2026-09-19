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
    """Allowlist rules from a global file, optionally widened by a
    project-local one.

    Both files are read and their rules concatenated (global first), so a
    workdir allowlist can only widen what is permitted, never shadow a global
    rule. The two rule lists are kept apart on purpose: a save rewrites only
    the file it came from, so appending a project rule can never flatten the
    global rules into the project file, or vice versa.

    allowlist_path=None drops the global file (--ignore-user-config); with no
    file at all, added rules live in memory for the session only.
    """

    def __init__(self, allowlist_path: Path | None, workdir_path: Path | None = None):
        self.path = Path(allowlist_path) if allowlist_path is not None else None
        self.workdir_path = Path(workdir_path) if workdir_path is not None else None
        self._global_rules: list[Rule] = (
            self._load(self.path) if self.path is not None else []
        )
        self._workdir_rules: list[Rule] = (
            self._load(self.workdir_path) if self.workdir_path is not None else []
        )

    @property
    def rules(self) -> list[Rule]:
        """All active rules, global first then workdir."""
        return self._global_rules + self._workdir_rules

    @property
    def write_path(self) -> Path | None:
        """Where a newly added rule is persisted."""
        return self.workdir_path if self.workdir_path is not None else self.path

    @staticmethod
    def _load(path: Path) -> list[Rule]:
        if not path.exists():
            return []
        with open(path, "rb") as f:
            data = _tomli.load(f)
        return [Rule(tool=r["tool"], pattern=r["pattern"]) for r in data.get("rules", [])]

    def _save(self):
        target = self.write_path
        if target is None:
            return
        owned = (
            self._workdir_rules if self.workdir_path is not None else self._global_rules
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {"rules": [{"tool": r.tool, "pattern": r.pattern} for r in owned]}
        with open(target, "wb") as f:
            tomli_w.dump(payload, f)

    def add_rule(self, rule: Rule):
        if self.workdir_path is not None:
            self._workdir_rules.append(rule)
        else:
            self._global_rules.append(rule)
        self._save()

    def check(self, tool_name: str, args: dict) -> Decision:
        subject = _tool_argument(tool_name, args)
        for r in self.rules:
            if r.tool == tool_name and fnmatch.fnmatchcase(subject, r.pattern):
                return Decision.AUTO_ALLOW
        if tool_name in READ_ONLY_TOOLS:
            return Decision.AUTO_ALLOW
        return Decision.PROMPT
