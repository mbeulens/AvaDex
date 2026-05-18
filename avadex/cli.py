from __future__ import annotations
import argparse
import sys
from getpass import getpass
from pathlib import Path

import httpx

from avadex.config import save_token


DEFAULT_CONFIG = Path.home() / ".config" / "avadex" / "config.toml"


def login_command(
    input_fn=input,
    password_fn=getpass,
    config_path: Path = DEFAULT_CONFIG,
) -> int:
    url = input_fn("Ava URL (e.g. https://ava.example.com): ").strip().rstrip("/")
    username = input_fn("Username: ").strip()
    password = password_fn("Password: ")
    try:
        r = httpx.post(f"{url}/login", json={"username": username, "password": password}, timeout=30)
    except httpx.RequestError as exc:
        print(f"network error: {exc}", file=sys.stderr)
        return 2
    if r.status_code != 200:
        print(f"login failed: HTTP {r.status_code}", file=sys.stderr)
        return 1
    data = r.json()
    token = data.get("token")
    if not data.get("ok") or not token:
        print(f"login failed: {data}", file=sys.stderr)
        return 1
    save_token(config_path, url, token)
    print(f"logged in. config saved to {config_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="avadex")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--debug", action="store_true")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("login")
    sub.add_parser("repl")  # also the default

    args = parser.parse_args(argv)
    if args.cmd == "login":
        return login_command(config_path=args.config)
    # Default to REPL — wired in Task 18
    print("REPL not yet wired in this task.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
