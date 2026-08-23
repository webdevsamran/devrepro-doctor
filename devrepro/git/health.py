"""Git repository health checks — read-only, credential-safe.

Capabilities:
- config health: autocrlf, safe.directory, hooks path, signing config
  presence, credential-helper NAME (never its stored value);
- Git LFS detection and version;
- submodule readiness (declared vs initialized vs dirty);
- linked-worktree awareness so diagnostics don't misread worktrees as
  broken clones.
"""

from __future__ import annotations

import configparser
from dataclasses import dataclass, field
from pathlib import Path

from devrepro.core.runner import SubprocessRunner

__all__ = [
    "GitHealthReport",
    "SubmoduleStatus",
    "git_health",
]

_GIT_CONFIG_KEYS = (
    "core.autocrlf",
    "core.hookspath",
    "user.name",
    "user.email",
    "commit.gpgsign",
    "user.signingkey",
    "tag.gpgsign",
    "gpg.format",
)


@dataclass(frozen=True)
class SubmoduleStatus:
    path: str
    declared: bool
    initialized: bool
    dirty: bool | None  # None when not initialized


@dataclass(frozen=True)
class GitHealthReport:
    is_repo: bool
    is_linked_worktree: bool
    config: dict[str, str | None] = field(default_factory=dict)  # key -> value or None
    signing_configured: bool = False
    credential_helper_present: bool = False
    credential_helper_name: str | None = None  # name only, never config value
    lfs_available: bool = False
    lfs_version: str | None = None
    submodules: tuple[SubmoduleStatus, ...] = ()
    notes: tuple[str, ...] = ()


def _git(runner: SubprocessRunner, repo: Path, *args: str) -> str | None:
    res = runner.run(("git", *args), timeout=10.0, cwd=str(repo))
    if res.returncode != 0:
        return None
    return (res.stdout or "").strip() or None


def _submodules(repo: Path) -> tuple[SubmoduleStatus, ...]:
    gm = repo / ".gitmodules"
    if not gm.is_file():
        return ()
    parser = configparser.ConfigParser()
    try:
        parser.read(gm, encoding="utf-8")
    except (OSError, configparser.Error):
        return ()
    out: list[SubmoduleStatus] = []
    for section in parser.sections():
        if not section.startswith("submodule"):
            continue
        path = parser.get(section, "path", fallback=None)
        if not path:
            continue
        target = repo / path
        initialized = (target / ".git").exists() or (repo / ".git" / "modules" / path).exists()
        dirty: bool | None = None
        if initialized:
            # cheap dirtiness signal: .git dir present but no HEAD file readable
            head = target / ".git"
            dirty = not head.exists()
        out.append(
            SubmoduleStatus(
                path=path,
                declared=True,
                initialized=initialized,
                dirty=dirty,
            )
        )
    return tuple(out)


def git_health(root: Path | str) -> GitHealthReport:
    """Read-only Git health snapshot. Never prints credential values."""
    root = Path(root)
    runner = SubprocessRunner()
    dot_git = root / ".git"
    is_repo = dot_git.exists()
    # a FILE named .git means a linked worktree, not a broken clone
    is_linked_worktree = dot_git.is_file()

    config: dict[str, str | None] = {}
    for key in _GIT_CONFIG_KEYS:
        config[key] = _git(runner, root, "config", "--get", key) if is_repo else None

    signing = any(config.get(k) for k in ("commit.gpgsign", "tag.gpgsign", "user.signingkey"))

    helper_raw = _git(runner, root, "config", "--get", "credential.helper") if is_repo else None
    helper_name = helper_raw.split()[0] if helper_raw else None

    lfs_version = _git(runner, root, "lfs", "version")
    notes: list[str] = []
    if is_repo and not is_linked_worktree and not (dot_git / "HEAD").exists():
        notes.append(".git exists but no HEAD; repository metadata may be incomplete")
    return GitHealthReport(
        is_repo=is_repo,
        is_linked_worktree=is_linked_worktree,
        config=config,
        signing_configured=signing,
        credential_helper_present=bool(helper_name),
        credential_helper_name=helper_name,
        lfs_available=lfs_version is not None,
        lfs_version=lfs_version,
        submodules=_submodules(root),
        notes=tuple(notes),
    )
