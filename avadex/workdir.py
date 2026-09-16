from __future__ import annotations
from pathlib import Path

# Where a project-local allowlist lives, relative to the workdir. Hidden so it
# doesn't clutter a project root, and namespaced so future per-project state
# has somewhere to go.
WORKDIR_ALLOWLIST_RELPATH = Path(".avadex") / "allowlist.toml"


class WorkdirError(Exception):
    """The requested working directory can't be used."""


def workdir_allowlist_path(workdir: Path) -> Path:
    """The project-local allowlist file for `workdir` (may not exist)."""
    return Path(workdir) / WORKDIR_ALLOWLIST_RELPATH


def resolve_workdir(
    flag: str | Path | None = None,
    config_value: str = "",
    base: Path | None = None,
) -> Path:
    """Pick the directory AvaDex should work in.

    Precedence: `--workdir` flag, then `workdir` from config.toml, then `base`
    (the process cwd). `~` is expanded and relative paths resolve against
    `base`, so resolution must happen before any chdir.

    Raises WorkdirError if the chosen path isn't an existing directory.
    """
    base = Path.cwd() if base is None else Path(base)
    chosen = flag if flag else (config_value or None)
    if chosen is None:
        return base.resolve()
    path = Path(chosen).expanduser()
    if not path.is_absolute():
        path = base / path
    path = path.resolve()
    if not path.exists():
        raise WorkdirError(f"workdir {path} does not exist")
    if not path.is_dir():
        raise WorkdirError(f"workdir {path} is not a directory")
    return path
