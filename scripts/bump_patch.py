#!/usr/bin/env python3
"""Increment the patch version in pyproject.toml and avadex/__init__.py. Prints the new version.

Usage: python3 scripts/bump_patch.py
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"
INIT_FILE = Path(__file__).resolve().parent.parent / "avadex" / "__init__.py"
VERSION_RE = re.compile(r'^(version\s*=\s*")(\d+)\.(\d+)\.(\d+)("\s*)$', re.MULTILINE)
INIT_VERSION_RE = re.compile(r'^(__version__\s*=\s*")(\d+)\.(\d+)\.(\d+)("\s*)$', re.MULTILINE)


def main() -> int:
    if not PYPROJECT.exists():
        print(f"no pyproject.toml at {PYPROJECT}", file=sys.stderr)
        return 1
    text = PYPROJECT.read_text()
    m = VERSION_RE.search(text)
    if not m:
        print("no version line found in pyproject.toml", file=sys.stderr)
        return 1
    prefix, major, minor, patch, suffix = m.groups()
    new_version = f"{major}.{minor}.{int(patch) + 1}"
    new_text = VERSION_RE.sub(f"{prefix}{new_version}{suffix}", text, count=1)
    PYPROJECT.write_text(new_text)

    # Also update avadex/__init__.py if it exists
    if INIT_FILE.exists():
        init_text = INIT_FILE.read_text()
        if INIT_VERSION_RE.search(init_text):
            new_init_text = INIT_VERSION_RE.sub(lambda m: m.group(1) + new_version + m.group(5), init_text, count=1)
            INIT_FILE.write_text(new_init_text)

    print(new_version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
