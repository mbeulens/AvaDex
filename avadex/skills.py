from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

from avadex.log import get_logger

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
