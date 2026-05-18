from __future__ import annotations
import argparse
import sys
from getpass import getpass
from pathlib import Path

from avadex.config import save_token, load_config, ConfigMissing
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


def _build_system_prompt(cfg) -> str:
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
        "USE BASH BOLDLY. For anything not covered by a dedicated tool — "
        "`gh` (GitHub CLI), `git`, `curl`, `find`, `pip`, `npm`, `systemctl`, "
        "etc. — use the bash tool. Don't say 'I cannot do X'; instead, plan "
        "a bash invocation that does X. Examples:\n"
        "- Create a GitHub repo: `gh repo create <name> --private --confirm`\n"
        "- Read a PR: `gh pr view <number>`\n"
        "- Check service status: `systemctl status <service>`\n\n"
        "Be concise. When a tool fails, read the error and adapt — don't "
        "repeat the same failing call. Prefer multi_edit over edit_file when "
        "you have several changes for one file. Use todo_write to plan "
        "multi-step work so the user can see progress."
    )


def run_repl(
    config_path: Path = DEFAULT_CONFIG,
    allowlist_path: Path = DEFAULT_ALLOWLIST,
    input_fn=None,
) -> int:
    try:
        cfg = load_config(config_path)
    except ConfigMissing as exc:
        print(str(exc), file=sys.stderr)
        return 2

    client = AvaClient(cfg.ava_url, cfg.ava_token)
    registry = ToolRegistry()
    for tool in ALL_BUILTINS:
        registry.register(tool)

    mcp_clients = []
    for entry in cfg.mcp_servers:
        mc = MCPClient(name=entry["name"], command=entry["command"], args=entry.get("args", []))
        try:
            mc.start()
            mcp_clients.append(mc)
        except Exception as exc:
            log.warning("MCP server '%s' failed to start: %s", entry["name"], exc)
    register_mcp_tools(mcp_clients, registry)

    permissions = PermissionManager(allowlist_path)
    initial_model = _resolve_initial_model(cfg, client)
    agent = AgentLoop(
        client=client, registry=registry, permissions=permissions,
        system_prompt=_build_system_prompt(cfg),
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
