from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

from avadex.log import get_logger
from avadex.tools.registry import ToolDefinition, ToolResult

log = get_logger("skills")

GLOBAL_SKILLS_DIR = Path.home() / ".config" / "avadex" / "skills"
WORKDIR_SKILLS_DIRNAME = "skills"   # <cwd>/skills/<name>/SKILL.md


@dataclass
class Skill:
    name: str
    description: str
    body: str
    path: Path
    source: str   # "global" | "workdir"


def _parse_skill_file(path: Path, source: str) -> Skill | None:
    """Parse a SKILL.md. Returns None (and logs a warning) if malformed —
    never raises, so one bad file can't crash startup."""
    try:
        text = path.read_text()
    except OSError as exc:
        log.warning("could not read skill %s: %s", path, exc)
        return None
    if not text.startswith("---"):
        log.warning("skill %s has no frontmatter; skipping", path)
        return None
    parts = text.split("---", 2)  # ["", frontmatter, body]
    if len(parts) < 3:
        log.warning("skill %s frontmatter not closed; skipping", path)
        return None
    front, body = parts[1], parts[2]
    meta: dict[str, str] = {}
    for line in front.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, val = line.partition(":")
        meta[key.strip()] = val.strip()
    name = meta.get("name")
    desc = meta.get("description")
    if not name or not desc:
        log.warning("skill %s missing name/description; skipping", path)
        return None
    return Skill(name=name, description=desc, body=body.strip(),
                 path=path, source=source)


def discover_skills(cwd: Path) -> dict[str, Skill]:
    """Discover skills from the global dir then the workdir dir. Workdir skills
    override global ones on name clash. Keyed by skill name."""
    skills: dict[str, Skill] = {}
    for base, source in ((GLOBAL_SKILLS_DIR, "global"),
                         (cwd / WORKDIR_SKILLS_DIRNAME, "workdir")):
        if not base.is_dir():
            continue
        for skill_md in sorted(base.glob("*/SKILL.md")):
            parsed = _parse_skill_file(skill_md, source)
            if parsed is not None:
                skills[parsed.name] = parsed   # workdir iterated last -> wins
    return skills


def render_skill_index(skills: dict[str, Skill]) -> str:
    """One-line-per-skill index for the system prompt. Empty string if none."""
    if not skills:
        return ""
    lines = [
        "You have these SKILLS — focused playbooks for specific tasks. "
        "**When the user's request matches a skill below, you MUST call "
        "`load_skill` FIRST, before any other tool — including MCP tools "
        "that look like a direct shortcut.** The skill body holds rules "
        "the raw tool schemas do NOT enforce (correct argument shapes, "
        "valid keys, anti-patterns); skipping load_skill is how you "
        "produce malformed tool calls. After load_skill returns, follow "
        "its body exactly.",
        "",
        "Skills:",
    ]
    for s in sorted(skills.values(), key=lambda s: s.name):
        lines.append(f"- {s.name}: {s.description}")
    return "\n".join(lines)


def make_load_skill_tool(skills: dict[str, Skill]) -> ToolDefinition:
    """Build the `load_skill` tool, closing over the discovered skills (mirrors
    register_mcp_tools closing over clients)."""
    def handler(args: dict) -> ToolResult:
        name = args.get("name", "")
        if not name:
            return ToolResult(content="missing 'name' argument", is_error=True)
        skill = skills.get(name)
        if skill is None:
            available = ", ".join(sorted(skills)) or "(none)"
            return ToolResult(
                content=f"unknown skill '{name}'. Available: {available}",
                is_error=True,
            )
        return ToolResult(content=skill.body)
    return ToolDefinition(
        name="load_skill",
        description=(
            "Load the full instructions for a named skill (see the SKILLS list "
            "in your system prompt). Call this before doing work that matches a "
            "skill's description."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string",
                         "description": "Skill name, e.g. 'create-partner'"}
            },
            "required": ["name"],
        },
        handler=handler,
    )
