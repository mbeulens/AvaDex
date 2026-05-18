from __future__ import annotations
import argparse
import sys
from getpass import getpass
from pathlib import Path

from avadex.config import save_token, load_config, ConfigMissing
from avadex.ava_client import AvaClient
from avadex.permissions import PermissionManager
from avadex.tools.registry import ToolRegistry
from avadex.tools.builtin import ALL_BUILTINS
from avadex.tools.mcp import MCPClient, register_mcp_tools
from avadex.agent_loop import AgentLoop
from avadex.repl import Repl, build_terminal_prompter


DEFAULT_CONFIG = Path.home() / ".config" / "avadex" / "config.toml"
DEFAULT_ALLOWLIST = Path.home() / ".config" / "avadex" / "allowlist.toml"


def _build_system_prompt(cfg) -> str:
    if cfg.system_prompt_path:
        try:
            return Path(cfg.system_prompt_path).read_text()
        except FileNotFoundError:
            pass
    return (
        "You are AvaDex, a local CLI agent. You have tools to read, write, "
        "and edit files, run shell commands, and call MCP-provided tools. "
        "Be concise. When a tool fails, read the error and adapt."
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
            print(f"[warn] MCP server '{entry['name']}' failed to start: {exc}", file=sys.stderr)
    register_mcp_tools(mcp_clients, registry)

    permissions = PermissionManager(allowlist_path)
    agent = AgentLoop(
        client=client, registry=registry, permissions=permissions,
        system_prompt=_build_system_prompt(cfg),
        max_context_tokens=cfg.max_context_tokens,
        model=cfg.default_model,
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
    if args.cmd == "set-key":
        return set_key_command(config_path=args.config)
    if args.cmd == "login":
        return login_redirect_command()
    # Default: REPL
    return run_repl(config_path=args.config)


if __name__ == "__main__":
    sys.exit(main())
