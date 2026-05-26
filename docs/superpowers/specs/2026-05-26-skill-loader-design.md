# Skill loader for AvaDex — Design

**Date:** 2026-05-26
**Status:** Approved, ready for implementation plan

## Problem

The user wants to run AvaDex as a task-scoped agent that pairs MCP tools with a
curated set of **skills** — focused markdown playbooks (e.g. `create-partner`,
which drives the Syntec partner MCP servers). AvaDex has no skill mechanism yet.
A `create-partner/SKILL.md` already exists at `~/.config/avadex/skills/`, written
to a known format, waiting for a loader.

Goal: at startup, discover skills from a global dir AND the working directory,
advertise them in the system prompt, and let the agent pull a skill's full
instructions on demand via a tool.

## Decisions

1. **Lazy loading.** The system prompt lists each skill's `name` + one-line
   `description`; the agent calls a `load_skill` tool to read the full body only
   when a request matches. Token-efficient, scales to many skills.
2. **Two discovery roots.** Global `~/.config/avadex/skills/<name>/SKILL.md` and
   workdir `<cwd>/skills/<name>/SKILL.md` (lowercase `skills`, visible folder).
3. **Workdir wins** on a name clash (a task folder can override a global skill).
4. **Independent of MCP.** Skills and the workdir `.mcp.json` (existing feature)
   load via separate mechanisms; a skill does not bundle or start MCP servers.
   For a partner task the user drops both a skill and a `.mcp.json` in the folder.
5. **`load_skill` is auto-allowed** (no permission prompt). It only reads local
   skill files; blast radius is "the agent reads a skill body it was told about."
   Explicitly signed off by the user.
6. **No YAML dependency.** Frontmatter is parsed by hand, line-by-line, the same
   way `mcp_workdir.load_dotenv` parses `.env`.

## Skill file format (already in use)

`<skills-dir>/<name>/SKILL.md`:

```
---
name: create-partner
description: Use when the user asks to create ... (one line, may be long)
---

<markdown body>
```

Only `name` and `description` matter; both are single-line scalars.

## Components

### `avadex/skills.py` (new)

```python
GLOBAL_SKILLS_DIR = Path.home() / ".config" / "avadex" / "skills"
WORKDIR_SKILLS_DIRNAME = "skills"   # <cwd>/skills/<name>/SKILL.md


@dataclass
class Skill:
    name: str
    description: str
    body: str
    path: Path
    source: str   # "global" | "workdir"
```

**`_parse_skill_file(path: Path, source: str) -> Skill | None`** — read the file;
return `None` (and `log.warning`) on any malformation, never raise:
- unreadable file (`OSError`)
- no leading `---` (no frontmatter)
- frontmatter not closed (fewer than 2 `---` delimiters)
- missing `name` or `description`

Parse: split the text on `---` with `maxsplit=2` → `["", frontmatter, body]`.
For each frontmatter line, skip blanks and lines without `:`, then
`key, _, val = line.partition(":")` and store `meta[key.strip()] = val.strip()`.
Body is `parts[2].strip()`. (maxsplit=2 means any `---` inside the body is
preserved.)

**`discover_skills(cwd: Path) -> dict[str, Skill]`** — iterate
`((GLOBAL_SKILLS_DIR, "global"), (cwd / WORKDIR_SKILLS_DIRNAME, "workdir"))`; for
each existing dir, `sorted(base.glob("*/SKILL.md"))`, parse, and store by
`skill.name`. Global first, workdir last → workdir overwrites on clash. Missing
dirs skipped.

**`render_skill_index(skills: dict[str, Skill]) -> str`** — `""` if empty;
otherwise a lead line instructing the model to call `load_skill` before acting
when a request matches a skill, followed by one `- {name}: {description}` line
per skill, sorted by name.

**`make_load_skill_tool(skills: dict[str, Skill]) -> ToolDefinition`** — a factory
closing over the discovered dict (mirrors `register_mcp_tools` closing over
clients). Tool `load_skill`, input schema `{name: string}` (required). Handler:
- missing/empty `name` → `ToolResult(is_error=True, "missing 'name' argument")`
- unknown name → `ToolResult(is_error=True, "unknown skill '<name>'. Available: <sorted names or (none)>")`
- known → `ToolResult(content=skill.body)`

### `avadex/permissions.py`

```python
READ_ONLY_TOOLS = {"read_file", "load_skill"}
```

`check()` already returns `Decision.AUTO_ALLOW` for tools in this set
(permissions.py:67-68). No other change.

### `avadex/cli.py`

Three edits in `run_repl` / the prompt builder:

1. After `cwd = Path.cwd()` and the `ALL_BUILTINS` registration loop:
   ```python
   skills = discover_skills(cwd)
   registry.register(make_load_skill_tool(skills))
   ```
   (Import `from avadex.skills import discover_skills, render_skill_index, make_load_skill_tool`.)

2. Refactor `_build_system_prompt(cfg)` → `_build_system_prompt(cfg, skill_index: str = "")`.
   Today the custom-`system_prompt_path` branch returns early and the default is a
   second `return`. Restructure to compute a `base` string from either branch,
   then:
   ```python
   if skill_index:
       base = base + "\n\n" + skill_index
   return base
   ```
   so the index is appended whichever prompt is in effect. Default prompt text
   otherwise unchanged.

3. Call site (currently `system_prompt=_build_system_prompt(cfg)`):
   ```python
   system_prompt=_build_system_prompt(cfg, render_skill_index(skills)),
   ```

## Data flow

```
startup (cwd)
  -> discover_skills(cwd): global SKILL.md's + cwd/skills SKILL.md's (workdir wins)
       -> dict[name -> Skill]
  -> register make_load_skill_tool(skills)        (auto-allowed)
  -> render_skill_index(skills) appended to system prompt

runtime
  user request matches a skill's description
  -> model calls load_skill(name)
  -> tool returns skill.body (no permission prompt)
  -> model follows the playbook (using whatever MCP/builtin tools it lists)
```

## Error handling

- Malformed/unreadable `SKILL.md` → skipped with `log.warning`; startup survives
  one bad skill; valid siblings still load.
- `load_skill` unknown/missing name → `is_error` ToolResult listing available
  names; the model self-corrects (no crash, no prompt).
- Missing global or `skills/` dir → silently skipped; empty index, no tool noise.

## Testing (`tests/unit/test_skills.py`)

Monkeypatch `skills.GLOBAL_SKILLS_DIR` to a `tmp_path` for global cases; use a
separate `tmp_path` as `cwd` with a `skills/` subdir for workdir cases.

1. Discovery global-only: well-formed `SKILL.md` → correct name/description/body,
   `source == "global"`.
2. Workdir overrides global: same `name` in both → workdir wins, `source == "workdir"`.
3. Malformed skipped, never raise: no frontmatter / unclosed frontmatter /
   missing `name` / missing `description` → absent from result, no exception, and
   a valid skill in the same dir still loads.
4. `render_skill_index`: empty dict → `""`; non-empty → contains each
   `name: description` line and the `load_skill` instruction.
5. `load_skill` dispatch: known name → body; unknown name → `is_error` listing
   names; missing `name` arg → `is_error`.
6. Permission: `PermissionManager(<tmp allowlist>).check("load_skill", {})` is
   `Decision.AUTO_ALLOW`.

## Docs & release

- **README:** a "Skills" subsection under Configuration — global + `./skills/`
  discovery, the `SKILL.md` format, lazy `load_skill`, workdir-wins precedence.
- **CHANGELOG:** entry for the skill loader.
- **Version:** patch bump to 0.2.5.

## Out of scope (YAGNI)

- Coupling skills to MCP servers (decision: independent).
- A `/skill` REPL slash command (decision: agent-driven tool).
- Eagerly inlining skill bodies into the prompt (decision: lazy).
- Recursive/upward skill discovery — only the immediate global dir and `cwd/skills`.
- Frontmatter beyond `name`/`description` (e.g. lists, multiline) — single-line
  scalars only.
- A YAML parser dependency.
