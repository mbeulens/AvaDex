from __future__ import annotations
import argparse
import sys
from getpass import getpass
from pathlib import Path

from avadex.config import save_token, load_config, ConfigMissing
from avadex.mcp_workdir import resolve_mcp_servers
from avadex.skills import discover_skills, render_skill_index, make_load_skill_tool
from avadex.ava_client import AvaClient, AvaError, TokenExpired
from avadex.permissions import PermissionManager
from avadex.tools.registry import ToolRegistry
from avadex.tools.builtin import ALL_BUILTINS
from avadex.tools.mcp import MCPClient, register_mcp_tools
from avadex.agent_loop import AgentLoop
from avadex.repl import Repl, build_terminal_prompter
from avadex.log import setup as setup_logging, get_logger

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
        "- Task tracking: todo_write, todo_read (persisted across turns within the session)\n\n"
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
        "Don't ask 'should I proceed?' after presenting a plan — just "
        "proceed. The user will interrupt if they disagree. Be concise. "
        "When a tool fails, read the error and adapt — don't repeat the same "
        "failing call. Prefer multi_edit over edit_file when you have "
        "several changes for one file. Use todo_write to plan multi-step "
        "work so the user can see progress."
    )


def _build_system_prompt(cfg, skill_index: str = "") -> str:
    base = _default_or_custom_prompt(cfg)
    if skill_index:
        base = base + "\n\n" + skill_index
    return base


def run_repl(
    config_path: Path = DEFAULT_CONFIG,
    allowlist_path: Path = DEFAULT_ALLOWLIST,
    input_fn=None,
) -> int:
    # Sanity check the current working directory up front. If the shell is
    # sitting in a deleted/unreachable dir, every relative-path tool (bash,
    # glob, write_file with a relative path, ...) would surprise-fail.
    # Bail with a clear message instead.
    try:
        import os as _os
        _os.getcwd()
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

    client = AvaClient(cfg.ava_url, cfg.ava_token)
    registry = ToolRegistry()
    for tool in ALL_BUILTINS:
        registry.register(tool)

    cwd = Path.cwd()
    skills = discover_skills(cwd)
    registry.register(make_load_skill_tool(skills))
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

    permissions = PermissionManager(allowlist_path)
    initial_model = _resolve_initial_model(cfg, client)
    agent = AgentLoop(
        client=client, registry=registry, permissions=permissions,
        system_prompt=_build_system_prompt(cfg, render_skill_index(skills)),
        max_context_tokens=cfg.max_context_tokens,
        model=initial_model,
        prompt_user=build_terminal_prompter(),
    )
    # Expose registry + permissions on agent for /tools and /allow slash commands
    agent.registry = registry
    agent.permissions = permissions
    repl = Repl(agent=agent, input_fn=input_fn)
    try:
        repl.run()
        return 0
    finally:
        for mc in mcp_clients:
            try:
                mc.stop()
            except Exception:
                pass
        client.close()


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
    # Default: REPL
    return run_repl(config_path=args.config)


if __name__ == "__main__":
    sys.exit(main())
