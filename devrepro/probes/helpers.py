"""Shared helpers for probes: version extraction, PATH resolution, safe IO."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from devrepro.core.runner import CommandRunner

__all__ = [
    "extract_version",
    "file_exists_safe",
    "first_line",
    "read_text_safe",
    "resolve_all_on_path",
]

_VERSION_PATTERNS = [
    re.compile(r"(?:version\s+|v)?(\d+\.\d+(?:\.\d+)*(?:[-+][0-9A-Za-z.-]+)?)", re.IGNORECASE),
]


def first_line(text: str) -> str:
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped:
            return stripped
    return ""


def extract_version(text: str) -> str | None:
    """Best-effort semantic-ish version extraction from tool output."""
    for pattern in _VERSION_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(1)
    return None


def resolve_all_on_path(name: str, *, path_env: str | None = None) -> list[str]:
    """All executables matching ``name`` across PATH, in precedence order.

    Unlike ``shutil.which`` this returns *every* match so duplicates and
    shadowing can be reported.
    """
    matches: list[str] = []
    exts: list[str]
    if os.name == "nt":
        exts = [
            e.strip().lower()
            for e in os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";")
            if e.strip()
        ]
        base = name.lower()
        candidates = [base] + [base + e for e in exts]
    else:
        candidates = [name]
    seen: set[str] = set()
    for directory in _path_entries(path_env):
        if not directory:
            continue
        for cand in candidates:
            full = str(Path(directory) / cand)
            real = os.path.normcase(str(Path(full).resolve()))
            if real in seen:
                continue
            is_exec = os.access(full, os.X_OK) or os.name == "nt"
            if Path(full).is_file() and is_exec:
                seen.add(real)
                matches.append(full)
    return matches


def _path_entries(path_env: str | None) -> list[str]:
    raw = path_env if path_env is not None else os.environ.get("PATH", "")
    return raw.split(os.pathsep)


def read_text_safe(path: Path, *, limit: int = 200_000) -> str | None:
    """Read a text file defensively; returns None on any problem."""
    try:
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return None


def file_exists_safe(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def which_first(name: str, runner: CommandRunner | None = None) -> str | None:
    found = resolve_all_on_path(name)
    return found[0] if found else None
