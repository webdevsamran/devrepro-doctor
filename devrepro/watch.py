"""Re-check when the environment contract changes, and not otherwise.

A watcher that re-runs on every file change is a watcher people turn off. This
one is narrow on purpose: it watches the files that declare *what the machine
must provide* -- lockfiles, manifests, toolchain pins, CI workflows, container
definitions, policy -- the same set `devrepro guard --scope changed` gates on.
Editing a function body changes nothing about what the machine needs, and a
scan triggered by it is five seconds of nothing.

Polling, not inotify. Two reasons, and the second is the real one:

- The watched set is dozens of files, not thousands, so a stat loop costs
  nothing measurable.
- Every cross-platform filesystem-notification library is a dependency, and
  the three platforms this supports have three different mechanisms with three
  different failure modes -- inotify watch limits on Linux (which this project
  *diagnoses* as a problem elsewhere), FSEvents coalescing on macOS, and a
  Windows API that misses changes on network shares. Polling is worse in
  theory and behaves the same everywhere.

Debounced, because editors do not write files the way people imagine. A single
save is routinely a truncate, a write and a rename, and a watcher without a
quiet period fires three scans for one edit.

The loop is written with its clock, its sleep and its iteration count injected
so a test drives it to completion instead of waiting on wall-clock seconds.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from typing import TYPE_CHECKING

from devrepro.project.contract import CONTRACT_PATTERNS

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from pathlib import Path

__all__ = [
    "DEFAULT_INTERVAL",
    "DEFAULT_QUIET_PERIOD",
    "Change",
    "fingerprint",
    "watch",
    "watched_paths",
]

#: How often the watched set is stat-ed. A second is imperceptible to a person
#: and inconsequential for a few dozen files.
DEFAULT_INTERVAL = 1.0

#: How long the tree must sit still before a scan starts. One save is often
#: three filesystem operations; this collapses them.
DEFAULT_QUIET_PERIOD = 1.5

#: Directories never descended into. Walking `node_modules` to find a
#: `package.json` would take longer than the scan it triggers -- and every
#: `package.json` in there belongs to a dependency, not to this project.
_SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        "target",
        "dist",
        "build",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        "vendor",
    }
)

#: How deep to look. Contract files live at a repository root or one workspace
#: down; nothing useful is nine directories deep, and a bounded walk is what
#: keeps this cheap on a large tree.
_MAX_DEPTH = 4


def _matches_contract(relative: str) -> bool:
    for pattern, _kind in CONTRACT_PATTERNS:
        if fnmatch.fnmatch(relative, pattern) or fnmatch.fnmatch(relative, f"**/{pattern}"):
            return True
        if pattern.startswith("**/") and fnmatch.fnmatch(relative, pattern[3:]):
            return True
    return False


def watched_paths(root: Path) -> tuple[Path, ...]:
    """Every environment-contract file under `root`, bounded in depth and breadth.

    Recomputed on each poll rather than cached, because a *new* lockfile is
    itself a contract change and a cached list would never see it.
    """
    found: list[Path] = []
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        directory, depth = stack.pop()
        try:
            entries = list(directory.iterdir())
        except OSError:  # pragma: no cover - permission denied mid-walk
            continue
        for entry in entries:
            if entry.is_dir():
                if depth < _MAX_DEPTH and entry.name not in _SKIP_DIRS:
                    stack.append((entry, depth + 1))
                continue
            try:
                relative = entry.relative_to(root).as_posix()
            except ValueError:  # pragma: no cover - symlink out of the tree
                continue
            if _matches_contract(relative):
                found.append(entry)
    return tuple(sorted(found))


def fingerprint(paths: Iterable[Path], root: Path) -> dict[str, tuple[float, int]]:
    """Modification time and size per watched file.

    Size as well as mtime because a filesystem with one-second mtime
    granularity -- which several network filesystems still have -- loses an
    edit made within a second of the previous one. Size catches most of those
    and costs nothing, since both come from the same `stat`.
    """
    out: dict[str, tuple[float, int]] = {}
    for path in paths:
        try:
            info = path.stat()
        except OSError:  # pragma: no cover - deleted between listing and stat
            continue
        out[path.relative_to(root).as_posix()] = (info.st_mtime, info.st_size)
    return out


@dataclass(frozen=True)
class Change:
    """What moved between two polls."""

    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    modified: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.added or self.removed or self.modified)

    def describe(self) -> str:
        parts = []
        for label, names in (
            ("added", self.added),
            ("changed", self.modified),
            ("removed", self.removed),
        ):
            if names:
                parts.append(f"{label}: {', '.join(names)}")
        return "; ".join(parts)


def _diff(before: dict[str, tuple[float, int]], after: dict[str, tuple[float, int]]) -> Change:
    return Change(
        added=tuple(sorted(set(after) - set(before))),
        removed=tuple(sorted(set(before) - set(after))),
        modified=tuple(sorted(k for k in set(before) & set(after) if before[k] != after[k])),
    )


def watch(
    root: Path,
    on_change: Callable[[Change], None],
    *,
    interval: float = DEFAULT_INTERVAL,
    quiet_period: float = DEFAULT_QUIET_PERIOD,
    clock: Callable[[], float],
    sleeper: Callable[[float], None],
    max_polls: int | None = None,
) -> int:
    """Poll until interrupted, calling `on_change` once per settled change.

    Returns the number of times `on_change` fired, which is what a test asserts
    on and what the command reports on exit.

    `max_polls` bounds the loop. Without it a test of a watcher is a test that
    either hangs or races; with it the loop is an ordinary function that
    returns.
    """
    baseline = fingerprint(watched_paths(root), root)
    pending: Change | None = None
    settled_at = 0.0
    fired = 0
    polls = 0

    while max_polls is None or polls < max_polls:
        polls += 1
        sleeper(interval)
        current = fingerprint(watched_paths(root), root)
        change = _diff(baseline, current)

        if change:
            # Restart the quiet period on every new movement: a save in
            # progress must not trigger a scan of a half-written file.
            pending = change if pending is None else _merge(pending, change)
            settled_at = clock() + quiet_period
            baseline = current
        elif pending is not None and clock() >= settled_at:
            on_change(pending)
            fired += 1
            pending = None

    return fired


def _merge(first: Change, second: Change) -> Change:
    return Change(
        added=tuple(sorted(set(first.added) | set(second.added))),
        removed=tuple(sorted(set(first.removed) | set(second.removed))),
        modified=tuple(sorted(set(first.modified) | set(second.modified))),
    )
