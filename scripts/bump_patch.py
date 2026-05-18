#!/usr/bin/env python3
"""Increment the patch version in pyproject.toml. Prints the new version.

Usage: python3 scripts/bump_patch.py
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"
VERSION_RE = re.compile(r'^(version\s*=\s*")(\d+)\.(\d+)\.(\d+)("\s*)$', re.MULTILINE)


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
    print(new_version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
