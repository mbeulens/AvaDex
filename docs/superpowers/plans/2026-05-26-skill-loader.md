# Skill Loader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** At startup, discover skill playbooks (`SKILL.md` files) from a global dir and the working directory, advertise them in the system prompt, and let the agent pull a skill's full body on demand via an auto-allowed `load_skill` tool.

**Architecture:** A new `avadex/skills.py` module with a `Skill` dataclass, a hand-rolled frontmatter parser (no YAML dep), `discover_skills(cwd)` (global `~/.config/avadex/skills/*/SKILL.md` then `<cwd>/skills/*/SKILL.md`, workdir wins on name clash), `render_skill_index()` (system-prompt blurb), and `make_load_skill_tool()` (factory closing over the discovered skills, mirroring `register_mcp_tools`). `load_skill` is added to `permissions.READ_ONLY_TOOLS` (auto-allowed). `cli.run_repl` discovers skills, registers the tool, and feeds the index into the system prompt. Skills are independent of MCP.

**Tech Stack:** Python 3.11+, stdlib only, pytest. Tests run with `.venv/bin/python -m pytest`.

---

## File Structure

- `avadex/skills.py` — NEW. `Skill`, `_parse_skill_file`, `discover_skills`, `render_skill_index`, `make_load_skill_tool`, constants.
- `avadex/permissions.py` — add `load_skill` to `READ_ONLY_TOOLS`.
- `avadex/cli.py` — discover/register skills; refactor `_build_system_prompt` to append the index.
- `tests/unit/test_skills.py` — NEW. Covers parse, discovery, index, tool dispatch, permission.
- `README.md`, `CHANGELOG.md`, `pyproject.toml`, `avadex/__init__.py` — docs + version bump.

---

### Task 1: `Skill` dataclass + `_parse_skill_file`

**Files:**
- Create: `avadex/skills.py`
- Test: `tests/unit/test_skills.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_skills.py`:

```python
import pytest
from pathlib import Path


def _write_skill(dir_path: Path, name: str, frontmatter: str, body: str = "Body here.") -> Path:
    d = dir_path / name
    d.mkdir(parents=True)
    f = d / "SKILL.md"
    f.write_text(f"---\n{frontmatter}\n---\n{body}\n")
    return f


def test_parse_skill_file_valid(tmp_path):
    from avadex.skills import _parse_skill_file
    f = _write_skill(tmp_path, "demo",
                     "name: demo\ndescription: A demo skill.",
                     "Step one.\nStep two.")
    skill = _parse_skill_file(f, "global")
    assert skill is not None
    assert skill.name == "demo"
    assert skill.description == "A demo skill."
    assert skill.body == "Step one.\nStep two."
    assert skill.source == "global"
    assert skill.path == f


def test_parse_skill_file_no_frontmatter(tmp_path):
    from avadex.skills import _parse_skill_file
    f = tmp_path / "SKILL.md"
    f.write_text("Just a body, no frontmatter.\n")
    assert _parse_skill_file(f, "global") is None


def test_parse_skill_file_unclosed_frontmatter(tmp_path):
    from avadex.skills import _parse_skill_file
    f = tmp_path / "SKILL.md"
    f.write_text("---\nname: x\ndescription: y\n")  # no closing ---
    assert _parse_skill_file(f, "global") is None


def test_parse_skill_file_missing_name(tmp_path):
    from avadex.skills import _parse_skill_file
    f = tmp_path / "SKILL.md"
    f.write_text("---\ndescription: only desc\n---\nbody\n")
    assert _parse_skill_file(f, "global") is None


def test_parse_skill_file_missing_description(tmp_path):
    from avadex.skills import _parse_skill_file
    f = tmp_path / "SKILL.md"
    f.write_text("---\nname: only-name\n---\nbody\n")
    assert _parse_skill_file(f, "global") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_skills.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'avadex.skills'`.

- [ ] **Step 3: Create the module**

Create `avadex/skills.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_skills.py -v`
Expected: all 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add avadex/skills.py tests/unit/test_skills.py
git commit -m "Add Skill dataclass and SKILL.md frontmatter parser"
```

---

### Task 2: `discover_skills`

**Files:**
- Modify: `avadex/skills.py`
- Test: `tests/unit/test_skills.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_skills.py` (reuses the `_write_skill` helper):

```python
def test_discover_global_only(tmp_path, monkeypatch):
    import avadex.skills as skills_mod
    global_dir = tmp_path / "global"
    _write_skill(global_dir, "alpha", "name: alpha\ndescription: Alpha skill.")
    monkeypatch.setattr(skills_mod, "GLOBAL_SKILLS_DIR", global_dir)
    cwd = tmp_path / "work"
    cwd.mkdir()  # no skills/ subdir
    result = skills_mod.discover_skills(cwd)
    assert set(result) == {"alpha"}
    assert result["alpha"].source == "global"


def test_discover_workdir_overrides_global(tmp_path, monkeypatch):
    import avadex.skills as skills_mod
    global_dir = tmp_path / "global"
    _write_skill(global_dir, "dup", "name: dup\ndescription: Global version.", "GLOBAL BODY")
    monkeypatch.setattr(skills_mod, "GLOBAL_SKILLS_DIR", global_dir)
    cwd = tmp_path / "work"
    _write_skill(cwd / "skills", "dup", "name: dup\ndescription: Workdir version.", "WORKDIR BODY")
    result = skills_mod.discover_skills(cwd)
    assert set(result) == {"dup"}
    assert result["dup"].source == "workdir"
    assert result["dup"].body == "WORKDIR BODY"


def test_discover_malformed_skipped_valid_still_loads(tmp_path, monkeypatch):
    import avadex.skills as skills_mod
    global_dir = tmp_path / "global"
    _write_skill(global_dir, "good", "name: good\ndescription: Good one.")
    bad = global_dir / "bad"
    bad.mkdir()
    (bad / "SKILL.md").write_text("---\nname: bad\n---\nbody\n")  # missing description
    monkeypatch.setattr(skills_mod, "GLOBAL_SKILLS_DIR", global_dir)
    cwd = tmp_path / "work"
    cwd.mkdir()
    result = skills_mod.discover_skills(cwd)
    assert set(result) == {"good"}


def test_discover_missing_dirs_returns_empty(tmp_path, monkeypatch):
    import avadex.skills as skills_mod
    monkeypatch.setattr(skills_mod, "GLOBAL_SKILLS_DIR", tmp_path / "nonexistent")
    cwd = tmp_path / "work"
    cwd.mkdir()
    assert skills_mod.discover_skills(cwd) == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_skills.py -k discover -v`
Expected: FAIL — `AttributeError: module 'avadex.skills' has no attribute 'discover_skills'`.

- [ ] **Step 3: Add `discover_skills`**

Append to `avadex/skills.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_skills.py -k discover -v`
Expected: all 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add avadex/skills.py tests/unit/test_skills.py
git commit -m "Add discover_skills: global + workdir, workdir wins"
```

---

### Task 3: `render_skill_index`

**Files:**
- Modify: `avadex/skills.py`
- Test: `tests/unit/test_skills.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_skills.py`:

```python
def test_render_skill_index_empty():
    from avadex.skills import render_skill_index
    assert render_skill_index({}) == ""


def test_render_skill_index_lists_skills_sorted():
    from avadex.skills import render_skill_index, Skill
    skills = {
        "beta": Skill("beta", "Beta does things.", "b", Path("/x"), "global"),
        "alpha": Skill("alpha", "Alpha does stuff.", "a", Path("/y"), "workdir"),
    }
    out = render_skill_index(skills)
    assert "load_skill" in out
    assert "- alpha: Alpha does stuff." in out
    assert "- beta: Beta does things." in out
    assert out.index("alpha") < out.index("beta")  # sorted by name
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_skills.py -k render -v`
Expected: FAIL — `ImportError: cannot import name 'render_skill_index'`.

- [ ] **Step 3: Add `render_skill_index`**

Append to `avadex/skills.py`:

```python
def render_skill_index(skills: dict[str, Skill]) -> str:
    """One-line-per-skill index for the system prompt. Empty string if none."""
    if not skills:
        return ""
    lines = ["You have these SKILLS — focused playbooks for specific tasks. "
             "When the user's request matches one, call the `load_skill` tool "
             "with its name to read the full instructions BEFORE acting:"]
    for s in sorted(skills.values(), key=lambda s: s.name):
        lines.append(f"- {s.name}: {s.description}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_skills.py -k render -v`
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add avadex/skills.py tests/unit/test_skills.py
git commit -m "Add render_skill_index for the system prompt"
```

---

### Task 4: `make_load_skill_tool`

**Files:**
- Modify: `avadex/skills.py`
- Test: `tests/unit/test_skills.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_skills.py`:

```python
def test_load_skill_returns_body():
    from avadex.skills import make_load_skill_tool, Skill
    skills = {"demo": Skill("demo", "d", "THE BODY", Path("/x"), "global")}
    tool = make_load_skill_tool(skills)
    assert tool.name == "load_skill"
    result = tool.handler({"name": "demo"})
    assert result.content == "THE BODY"
    assert result.is_error is False


def test_load_skill_unknown_name_errors():
    from avadex.skills import make_load_skill_tool, Skill
    skills = {"demo": Skill("demo", "d", "b", Path("/x"), "global")}
    tool = make_load_skill_tool(skills)
    result = tool.handler({"name": "nope"})
    assert result.is_error is True
    assert "demo" in result.content  # lists available names


def test_load_skill_missing_name_errors():
    from avadex.skills import make_load_skill_tool
    tool = make_load_skill_tool({})
    result = tool.handler({})
    assert result.is_error is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_skills.py -k load_skill -v`
Expected: FAIL — `ImportError: cannot import name 'make_load_skill_tool'`.

- [ ] **Step 3: Add the import and the factory**

In `avadex/skills.py`, add this import directly below the existing `from avadex.log import get_logger` line:

```python
from avadex.tools.registry import ToolDefinition, ToolResult
```

Then append at the end of the file:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_skills.py -q`
Expected: all PASS (parse + discover + render + load_skill).

- [ ] **Step 5: Commit**

```bash
git add avadex/skills.py tests/unit/test_skills.py
git commit -m "Add load_skill tool factory"
```

---

### Task 5: Auto-allow `load_skill` in permissions

**Files:**
- Modify: `avadex/permissions.py:21`
- Test: `tests/unit/test_skills.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_skills.py`:

```python
def test_load_skill_is_auto_allowed(tmp_path):
    from avadex.permissions import PermissionManager, Decision
    pm = PermissionManager(tmp_path / "allowlist.toml")
    assert pm.check("load_skill", {}) == Decision.AUTO_ALLOW
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_skills.py -k auto_allowed -v`
Expected: FAIL — returns `Decision.PROMPT` (load_skill not yet in READ_ONLY_TOOLS).

- [ ] **Step 3: Add `load_skill` to `READ_ONLY_TOOLS`**

In `avadex/permissions.py`, change line 21 from:

```python
READ_ONLY_TOOLS = {"read_file"}
```
to:
```python
READ_ONLY_TOOLS = {"read_file", "load_skill"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_skills.py -k auto_allowed -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add avadex/permissions.py tests/unit/test_skills.py
git commit -m "Auto-allow load_skill (read-only tool)"
```

---

### Task 6: Wire skills into `cli.py`

**Files:**
- Modify: `avadex/cli.py` (import region ~line 8; `_build_system_prompt` ~line 48; `run_repl` ~lines 123 and 148)

- [ ] **Step 1: Add the import**

In `avadex/cli.py`, directly below the line:

```python
from avadex.mcp_workdir import resolve_mcp_servers
```
add:
```python
from avadex.skills import discover_skills, render_skill_index, make_load_skill_tool
```

- [ ] **Step 2: Refactor `_build_system_prompt` (extract + thin wrapper)**

In `avadex/cli.py`, the function currently starts:

```python
def _build_system_prompt(cfg) -> str:
    if cfg.system_prompt_path:
        try:
            return Path(cfg.system_prompt_path).read_text()
        except FileNotFoundError:
            pass
    return (
        "You are AvaDex, a local CLI coding agent. You assist with software "
```

Rename ONLY that signature line (line 48) — change `def _build_system_prompt(cfg) -> str:` to:

```python
def _default_or_custom_prompt(cfg) -> str:
```

Leave the entire body (the `if cfg.system_prompt_path` block and the big `return (...)` literal) UNCHANGED. Then, immediately after that function's closing `)` and before `def run_repl(`, add a new wrapper:

```python
def _build_system_prompt(cfg, skill_index: str = "") -> str:
    base = _default_or_custom_prompt(cfg)
    if skill_index:
        base = base + "\n\n" + skill_index
    return base
```

- [ ] **Step 3: Discover skills + register the tool in `run_repl`**

In `avadex/cli.py`, the startup currently reads:

```python
    cwd = Path.cwd()
    try:
        mcp_specs = resolve_mcp_servers(cfg, cwd)
```

Insert two lines after `cwd = Path.cwd()`:

```python
    cwd = Path.cwd()
    skills = discover_skills(cwd)
    registry.register(make_load_skill_tool(skills))
    try:
        mcp_specs = resolve_mcp_servers(cfg, cwd)
```

- [ ] **Step 4: Feed the index into the system prompt**

In `avadex/cli.py`, change the call site (currently `system_prompt=_build_system_prompt(cfg),`) to:

```python
        system_prompt=_build_system_prompt(cfg, render_skill_index(skills)),
```

- [ ] **Step 5: Verify no regressions + wiring present**

Run the full suite:
`.venv/bin/python -m pytest -q`
Expected: all PASS.

Confirm import is clean (no circular import) and wiring is present:
`.venv/bin/python -c "import avadex.cli"`
`grep -n "discover_skills\|make_load_skill_tool\|render_skill_index\|_default_or_custom_prompt" avadex/cli.py`
Expected: import line, `skills = discover_skills(cwd)`, `registry.register(make_load_skill_tool(skills))`, `_default_or_custom_prompt`, and the `render_skill_index(skills)` call site all appear.

Note: `run_repl` is not unit-tested directly (it builds the live client/REPL); the delegated functions are fully covered by `tests/unit/test_skills.py`, and the full-suite run + import check guard against wiring/import regressions.

- [ ] **Step 6: Commit**

```bash
git add avadex/cli.py
git commit -m "Discover skills, register load_skill, advertise in system prompt"
```

---

### Task 7: Docs, CHANGELOG, version bump

**Files:**
- Modify: `README.md`, `CHANGELOG.md`, `pyproject.toml`, `avadex/__init__.py`

- [ ] **Step 1: Add a README section**

In `README.md`, find the "Per-directory MCP servers (`.mcp.json`)" subsection added previously (search for `Per-directory MCP servers`). Immediately AFTER that subsection (before the next `##`-level heading), insert:

````markdown
### Skills

Skills are focused markdown playbooks AvaDex can load on demand. At startup it
discovers them from two places:

- **Global:** `~/.config/avadex/skills/<name>/SKILL.md`
- **Workdir:** `<cwd>/skills/<name>/SKILL.md` (a workdir skill overrides a
  global one with the same name)

Each `SKILL.md` has simple frontmatter plus a markdown body:

```
---
name: create-partner
description: Use when the user asks to create or onboard a partner in Syntec.
---

<the full playbook the agent should follow>
```

AvaDex lists each skill's `name` and `description` in the system prompt and
exposes a `load_skill` tool. When a request matches a skill, the agent calls
`load_skill` to read the full body before acting (the tool is read-only and
runs without a permission prompt). Skills are independent of MCP servers —
pair a skill with a `.mcp.json` in the same directory when it needs specific
tools.
````

- [ ] **Step 2: Add a CHANGELOG entry**

At the top of `CHANGELOG.md` (above the `## [0.2.4]` entry), matching the existing `## [x.y.z] — date` + `### Added` style:

```markdown
## [0.2.5] — 2026-05-26

### Added
- Skill loader: AvaDex discovers `SKILL.md` playbooks from `~/.config/avadex/skills/`
  and the working directory's `./skills/` (workdir wins on name clash), lists them
  in the system prompt, and exposes an auto-allowed `load_skill` tool the agent
  calls on demand. Independent of MCP server loading.
```

- [ ] **Step 3: Bump the version**

In `pyproject.toml` change `version = "0.2.4"` to `version = "0.2.5"`.
In `avadex/__init__.py` change `__version__ = "0.2.4"` to `__version__ = "0.2.5"`.

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add README.md CHANGELOG.md pyproject.toml avadex/__init__.py
git commit -m "Document skill loader; bump to 0.2.5"
```

---

## Self-Review

**Spec coverage:**
- Lazy loading (advertise + `load_skill`) → Tasks 3 (index), 4 (tool), 6 (wiring).
- Two discovery roots, global + `<cwd>/skills` → Task 2.
- Workdir wins on clash → Task 2 (global iterated first, workdir last).
- Independent of MCP → no MCP code touched; README states it (Task 7).
- `load_skill` auto-allowed → Task 5.
- No YAML dep → Task 1 hand parser.
- Skill file format / frontmatter parse → Task 1.
- Error handling: malformed skipped never raises (Task 1 + Task 2 tests), unknown/missing name → is_error (Task 4), missing dirs → empty (Task 2).
- Testing items 1-6 from the spec → Tasks 1-5 tests.
- Docs + release → Task 7.

**Placeholder scan:** No TBD/TODO; every code step has full code; every command states expected output.

**Type consistency:** `Skill(name, description, body, path, source)` constructed identically in Tasks 1, 3, 4 tests and `_parse_skill_file`. `source` values are exactly `"global"`/`"workdir"` throughout (Task 2 sets them; tests assert them). `_parse_skill_file(path, source)`, `discover_skills(cwd) -> dict[str,Skill]`, `render_skill_index(skills) -> str`, `make_load_skill_tool(skills) -> ToolDefinition` signatures match across definition (skills.py) and call sites (cli.py Task 6). `ToolDefinition`/`ToolResult` fields match `avadex/tools/registry.py` (name, description, input_schema, handler; content, is_error). cli.py uses the renamed `_default_or_custom_prompt` (existing body) + new `_build_system_prompt(cfg, skill_index="")` consistently with the call site.
