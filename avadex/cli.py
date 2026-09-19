from __future__ import annotations
import argparse
import json
import os
import sys
import time
from getpass import getpass
from pathlib import Path

from avadex.allow_tools import AllowToolsError, parse_allow_tools, resolve_allowed
from avadex.config import save_token, load_config, ConfigMissing
from avadex.mcp_workdir import resolve_mcp_servers
from avadex.workdir import resolve_workdir, workdir_allowlist_path, WorkdirError
from avadex.skills import discover_skills, render_skill_index, make_load_skill_tool
from avadex.ava_client import AvaClient, AvaError, TokenExpired
from avadex.permissions import PermissionManager
from avadex.tools.registry import ToolRegistry
from avadex.tools.builtin import ALL_BUILTINS
from avadex.tools.mcp import MCPClient, register_mcp_tools
from avadex.agent_loop import AgentLoop
from avadex.repl import Repl, build_terminal_prompter
from avadex.renderer import HeadlessRenderer
from avadex.log import setup as setup_logging, get_logger


def _auto_approve_prompter(tool, args):
    """Headless prompter: every tool call is approved for this invocation only.

    No human is available to answer the normal permission prompt; the pattern
    is None so nothing is added to the persistent allowlist.
    """
    return ("yes", None)


def _select_prompter(prompt, auto_approve):
    """Choose the tool-approval prompter.

    Headless (`--prompt`) and autonomous (`--yes`) modes both auto-approve every
    tool call for this invocation only (no allowlist mutation). An interactive
    REPL without `--yes` asks the human per non-read tool.
    """
    if prompt is not None or auto_approve:
        return _auto_approve_prompter
    return build_terminal_prompter()


def _skills_message(skills: dict) -> str | None:
    """Format the startup line for loaded skills, mirroring the MCP line.

    Returns None when no skills are loaded (mirrors how the MCP line is only
    printed when `.mcp.json` exists). Splits the count by source when both
    global and workdir skills are present.
    """
    if not skills:
        return None
    workdir_n = sum(1 for s in skills.values() if s.source == "workdir")
    global_n = len(skills) - workdir_n
    if workdir_n and global_n:
        return f"Loaded {len(skills)} skill(s) ({global_n} global, {workdir_n} workdir)"
    if workdir_n:
        return f"Loaded {workdir_n} skill(s) from workdir"
    return f"Loaded {global_n} skill(s) from global"

log = get_logger("cli")

DEFAULT_CONFIG = Path.home() / ".config" / "avadex" / "config.toml"
DEFAULT_ALLOWLIST = Path.home() / ".config" / "avadex" / "allowlist.toml"


FALLBACK_MODEL = "gemma4"


def _resolve_initial_model(cfg, client) -> str:
    """Pick the model to start the REPL with.

    Resolution order:
      1. cfg.default_model if explicitly set in config.toml (user override)
      2. The `default` field from Ava's GET /api/v1/models
      3. FALLBACK_MODEL as last resort, with a warning to stderr
    """
    if cfg.default_model:
        return cfg.default_model
    try:
        info = client.list_models()
    except (AvaError, TokenExpired, Exception) as exc:
        log.warning(
            "could not fetch Ava's default model (%s); using fallback '%s'",
            exc, FALLBACK_MODEL,
        )
        return FALLBACK_MODEL
    return info.get("default") or FALLBACK_MODEL


def _describe_exc(exc: BaseException) -> str:
    """Readable cause(s) of an exception. Unwraps ExceptionGroups and falls back
    to repr when str() is empty (e.g. a bare TimeoutError() from a connect
    timeout), so MCP start failures never log a blank message."""
    sub = getattr(exc, "exceptions", None)
    if sub:
        return "; ".join(_describe_exc(e) for e in sub)
    text = str(exc).strip()
    return text or repr(exc)


def _default_or_custom_prompt(cfg) -> str:
    if cfg.system_prompt_path:
        try:
            return Path(cfg.system_prompt_path).read_text()
        except FileNotFoundError:
            pass
    return (
        "You are AvaDex, a local CLI coding agent. You assist with software "
        "development, system administration, and any task the user throws at "
        "you on this machine.\n\n"
        "You have these tools:\n"
        "- File operations: read_file, write_file, edit_file, multi_edit, glob, grep_files\n"
        "- Shell: bash (synchronous, default 30s timeout); bash_bg / bash_output / kill_bash / bash_list (background processes)\n"
        "- Web: web_fetch (GET a URL, returns up to 100KB of text)\n"
        "- Vision: attach_image (attach a local image file — jpg/png/etc — so you can visually read gauges, dials, screenshots, text; use it whenever the user points you at an image path)\n"
        "- Task tracking: todo_write, todo_read (persisted across turns within the session)\n\n"
        "KNOWLEDGE VS. LOCAL FILES. Ava augments your context with curated "
        "company/domain knowledge under a '## Relevant knowledge from Ava' "
        "heading. For questions about Syntec, the platform, or the business "
        "domain (e.g. 'what do you know about X'), answer from that injected "
        "knowledge plus what you already know — do NOT grep_files/glob the "
        "working directory looking for it. The working directory is the user's "
        "local project, not the knowledge base; the file tools (grep_files, "
        "glob, read_file) are for working on the local codebase, not for "
        "answering company/domain questions.\n\n"
        "ACT, DON'T NARRATE. When the user asks you to build, create, or "
        "make something — a file, a script, a website, a project — actually "
        "USE write_file (and bash for mkdir, etc.) to put the bytes on disk "
        "in the user's current working directory. Do NOT paste file contents "
        "into the chat as markdown code blocks describing what you would do. "
        "Examples:\n"
        "- 'create a small website' → mkdir a sensibly named folder, "
        "write_file index.html / style.css / script.js into it, then report "
        "what you created and where (don't dump the HTML in chat).\n"
        "- 'add a healthcheck endpoint to server.py' → read_file, edit_file "
        "to insert the route, run the tests with bash.\n"
        "Only show code in chat when the user explicitly asks you to explain "
        "or review something — not when they ask you to build.\n\n"
        "USE BASH BOLDLY. For anything not covered by a dedicated tool — "
        "`gh` (GitHub CLI), `git`, `curl`, `find`, `pip`, `npm`, `systemctl`, "
        "`mkdir`, etc. — use the bash tool. Don't say 'I cannot do X'; "
        "instead, plan a bash invocation that does X. Examples:\n"
        "- Create a GitHub repo: `gh repo create <name> --public --confirm`\n"
        "- Read a PR: `gh pr view <number>`\n"
        "- Check service status: `systemctl status <service>`\n\n"
        "USE TOOL RESULTS FAITHFULLY. When a tool returns data, answer from "
        "that data directly — don't just describe its shape or give a vague "
        "summary. If the user asks for a table or list, render the actual rows "
        "as a Markdown table. If a tool result is paginated (it has page / "
        "limit / offset fields and more rows remain), call the tool again for "
        "the next pages before answering 'all'. Always reply in the same "
        "language the user wrote in.\n\n"
        "Don't ask 'should I proceed?' after presenting a plan — just "
        "proceed. The user will interrupt if they disagree. Be concise. "
        "When a tool fails, read the error and adapt — don't repeat the same "
        "failing call. Prefer multi_edit over edit_file when you have "
        "several changes for one file. Use todo_write to plan multi-step "
        "work so the user can see progress."
    )


def _build_system_prompt(cfg, skill_index: str = "", allowed: list[str] | None = None) -> str:
    base = _default_or_custom_prompt(cfg)
    if skill_index:
        base = base + "\n\n" + skill_index
    if allowed is not None:
        base = base + (
            "\n\nTOOL RESTRICTION: in this run you can only use these tools: "
            f"{', '.join(sorted(allowed))}. Any other tool mentioned above is "
            "unavailable and will be refused — don't try it; work with what you "
            "have or say what you couldn't do."
        )
    return base


def run_repl(
    config_path: Path = DEFAULT_CONFIG,
    allowlist_path: Path = DEFAULT_ALLOWLIST,
    input_fn=None,
    prompt: str | None = None,
    model: str | None = None,
    auto_approve: bool = False,
    workdir: Path | None = None,
    allow_tools: str | None = None,
    output_format: str = "text",
) -> int:
    # Sanity check the current working directory up front. If the shell is
    # sitting in a deleted/unreachable dir, every relative-path tool (bash,
    # glob, write_file with a relative path, ...) would surprise-fail.
    # Bail with a clear message instead.
    try:
        os.getcwd()
    except (FileNotFoundError, OSError) as exc:
        print(
            f"current working directory is unavailable ({exc}); "
            "cd into a valid directory and try again.",
            file=sys.stderr,
        )
        return 2

    try:
        cfg = load_config(config_path)
    except ConfigMissing as exc:
        print(str(exc), file=sys.stderr)
        return 2

    # Resolve the working directory before chdir'ing, so a relative
    # --workdir is interpreted against the shell's cwd. Everything downstream
    # reads Path.cwd(), so skills, .mcp.json/.env, bash and relative file
    # paths all follow along.
    try:
        target = resolve_workdir(flag=workdir, config_value=cfg.workdir)
    except WorkdirError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    workdir_was_set = bool(workdir or cfg.workdir)
    os.chdir(target)

    client = AvaClient(cfg.ava_url, cfg.ava_token)
    registry = ToolRegistry()
    for tool in ALL_BUILTINS:
        registry.register(tool)

    cwd = Path.cwd()
    skills = discover_skills(cwd)
    registry.register(make_load_skill_tool(skills))
    _skills_msg = _skills_message(skills)
    if _skills_msg is not None:
        print(_skills_msg, file=sys.stderr)
    try:
        mcp_specs = resolve_mcp_servers(cfg, cwd)
    except ConfigMissing as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if (cwd / ".mcp.json").exists():
        print(f"Loaded {len(mcp_specs)} MCP server(s) from ./.mcp.json",
              file=sys.stderr)

    mcp_clients = []
    for s in mcp_specs:
        mc = MCPClient(name=s.name, transport=s.transport, command=s.command,
                       args=s.args, url=s.url, headers=s.headers)
        try:
            mc.start()
            mcp_clients.append(mc)
        except Exception as exc:
            log.warning("MCP server '%s' failed to start: %s", s.name, _describe_exc(exc))
    register_mcp_tools(mcp_clients, registry)

    allowed: set[str] | None = None
    if allow_tools is not None:
        try:
            allowed = resolve_allowed(parse_allow_tools(allow_tools), registry)
        except AllowToolsError as exc:
            print(str(exc), file=sys.stderr)
            _stop_mcp(mcp_clients)
            client.close()
            return 2
        registry.restrict(allowed)

    # A project allowlist is honored when it already exists, or when the user
    # explicitly chose this workdir (so the first /allow lands in the project).
    project_allowlist = workdir_allowlist_path(cwd)
    permissions = PermissionManager(
        allowlist_path,
        project_allowlist if (workdir_was_set or project_allowlist.exists()) else None,
    )
    initial_model = _resolve_initial_model(cfg, client)
    agent = AgentLoop(
        client=client, registry=registry, permissions=permissions,
        system_prompt=_build_system_prompt(cfg, render_skill_index(skills), allowed),
        max_context_tokens=cfg.max_context_tokens,
        max_response_tokens=cfg.max_response_tokens,
        model=model or initial_model,
        prompt_user=_select_prompter(prompt, auto_approve),
        max_iterations=cfg.max_iterations,
        compaction_threshold=cfg.context_compaction_threshold,
        large_output_tokens=cfg.context_large_output_tokens,
        keep_recent=cfg.context_keep_recent,
    )
    # Expose registry + permissions on agent for /tools and /allow slash commands
    agent.registry = registry
    agent.permissions = permissions
    try:
        if prompt is not None:
            # Headless agent: one user turn, clean stdout, exit 0 on end_turn.
            # The agent's internal tool-use loop still runs as normal (up to
            # max_iterations) — MCP servers and built-in tools are all in play.
            renderer = HeadlessRenderer()
            started = time.monotonic()
            agent.run_turn(prompt, renderer)
            for name in registry.refused:
                print(f"avadex: refused tool '{name}' (not in --allow-tools)",
                      file=sys.stderr)
            if output_format == "json":
                envelope = _result_envelope(
                    agent, renderer, registry, requested_model=agent.model,
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
                sys.stdout.write(json.dumps(envelope) + "\n")
            else:
                sys.stdout.write(renderer.text)
                if renderer.text and not renderer.text.endswith("\n"):
                    sys.stdout.write("\n")
            return 1 if renderer.errored else 0
        repl = Repl(agent=agent, input_fn=input_fn)
        repl.run()
        return 0
    finally:
        _stop_mcp(mcp_clients)
        client.close()


def _result_envelope(agent, renderer, registry, requested_model: str,
                     duration_ms: int) -> dict:
    """The --output-format json result: final answer plus token accounting.

    Shaped after Claude Code's result envelope so callers can treat both alike.
    `model` is what Ava actually ran (it falls back to its default when the
    requested model isn't installed); `usage_complete` is false when any
    response came back without real token counts.
    """
    usage = agent.usage
    return {
        "type": "result",
        "subtype": "error" if renderer.errored else "success",
        "is_error": renderer.errored,
        "result": renderer.text,
        "errors": list(renderer.errors),
        "requested_model": requested_model,
        "model": usage.last_model or requested_model,
        "models_used": list(usage.models),
        "usage": usage.as_dict(),
        "usage_complete": usage.complete,
        "num_requests": usage.requests,
        "duration_ms": duration_ms,
        "permission_denials": [{"tool_name": n} for n in registry.refused],
    }


def _stop_mcp(mcp_clients) -> None:
    for mc in mcp_clients:
        try:
            mc.stop()
        except Exception:
            pass


def set_key_command(
    input_fn=input,
    password_fn=getpass,
    config_path: Path = DEFAULT_CONFIG,
) -> int:
    url = input_fn("Ava URL (e.g. https://ava.example.com): ").strip().rstrip("/")
    if not url:
        print("URL is required", file=sys.stderr)
        return 1
    key = password_fn("Ava API key (AVA_SYNTEC_API_KEY): ").strip()
    if not key:
        print("API key is required", file=sys.stderr)
        return 1
    save_token(config_path, url, key)
    print(f"saved {config_path}")
    return 0


def login_redirect_command() -> int:
    print(
        "'avadex login' is no longer supported — Ava's API uses a static "
        "API key, not session login. Use 'avadex set-key' instead.",
        file=sys.stderr,
    )
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="avadex")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument(
        "--prompt",
        default=None,
        metavar="TEXT",
        help="Headless: run one agent turn with this prompt and exit. "
             "The agent's tool-use loop still iterates as normal (MCP "
             "servers, file/bash tools); only the final assistant answer "
             "is written to stdout. Tool prompts auto-approve.",
    )
    parser.add_argument(
        "--model",
        default=None,
        metavar="NAME",
        help="Override the model (works in both headless and REPL mode).",
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Autonomous: auto-approve every tool call, including writes, in "
             "the REPL (no per-action confirmation). Headless --prompt already "
             "auto-approves regardless of this flag.",
    )
    parser.add_argument(
        "--workdir",
        type=Path,
        default=None,
        metavar="PATH",
        help="Directory to work in. AvaDex chdirs here, so skills/, .mcp.json, "
             ".env, bash and relative file paths all resolve against it, and "
             "<PATH>/.avadex/allowlist.toml is merged into the allowlist. "
             "Overrides 'workdir' in config.toml; defaults to the current "
             "directory.",
    )
    parser.add_argument(
        "--allow-tools",
        default=None,
        metavar="LIST",
        help="Comma-separated tools this run may use; every other tool is "
             "hidden from the model and refused if called. Entries: a tool "
             "name (read_file), mcp__<server> (all tools of an MCP server) or "
             "mcp__<server>__<tool>. An entry that matches no available tool "
             "exits 2. Omit to allow every tool.",
    )
    parser.add_argument(
        "--output-format",
        choices=("text", "json"),
        default="text",
        help="Headless output. 'text' (default) prints the final answer; "
             "'json' prints one result object with the answer, token usage, "
             "the model(s) actually used and any refused tools.",
    )
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("set-key")
    sub.add_parser("login")   # legacy alias → redirect
    sub.add_parser("repl")    # also the default

    args = parser.parse_args(argv)
    setup_logging(debug=args.debug)
    if args.cmd == "set-key":
        return set_key_command(config_path=args.config)
    if args.cmd == "login":
        return login_redirect_command()
    if args.output_format == "json" and args.prompt is None:
        print("--output-format json requires --prompt", file=sys.stderr)
        return 2
    # Default: REPL (or headless agent if --prompt is given).
    return run_repl(config_path=args.config, prompt=args.prompt, model=args.model,
                    auto_approve=args.yes, workdir=args.workdir,
                    allow_tools=args.allow_tools,
                    output_format=args.output_format)


if __name__ == "__main__":
    sys.exit(main())
