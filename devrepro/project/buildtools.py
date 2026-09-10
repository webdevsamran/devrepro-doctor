"""Monorepo build tooling: which orchestrator, and where its cache actually is.

Nx, Turborepo and Bazel all solve the same problem the same way -- hash the
inputs, skip the work if the hash is known -- and all three have the same two
failure modes that nothing reports.

**A remote cache that is configured and unreachable costs more than no cache.**
Every task pays a lookup, times out or fails auth, and then runs anyway. The
tools handle this gracefully, which is the problem: the build succeeds, slower,
with a warning nobody reads in a log nobody opens. What is detectable offline
is whether a remote cache is *configured at all* -- because if it is, its health
is worth knowing, and if it is not, a team that believes it has one is wrong
about why their CI is slow.

**A cache token committed to the repository.** `nx.json` has an
`nxCloudAccessToken` field, `turbo.json` had `remoteCache.signature`, and
`.bazelrc` takes `--remote_header=Authorization=...`. These are configuration
files people commit without thinking, and a read-write cache token is a
supply-chain credential: whoever holds it can poison build outputs that every
developer and every CI run then trusts. This reports the field's presence and
**never its value** -- the finding is that a secret-shaped field is in a
committed file, which is exactly as much as anybody needs to know to act.

Everything here reads files already on disk. No orchestrator is invoked: `nx
show projects` and `bazel info` both start a daemon, and a diagnostic that
leaves a JVM running is not read-only in any sense that matters.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "BUILD_TOOLS",
    "BuildTool",
    "CacheConfig",
    "detect_build_tools",
    "read_bazelrc",
    "read_nx",
    "read_turbo",
]

#: (config file, tool name). Order matters only for reporting.
BUILD_TOOLS: tuple[tuple[str, str], ...] = (
    ("nx.json", "nx"),
    ("turbo.json", "turborepo"),
    ("MODULE.bazel", "bazel"),
    ("WORKSPACE", "bazel"),
    ("WORKSPACE.bazel", "bazel"),
    ("lerna.json", "lerna"),
    ("rush.json", "rush"),
    ("moon.yml", "moon"),
)


@dataclass(frozen=True)
class CacheConfig:
    """What a build tool's configuration says about caching."""

    remote_configured: bool = False
    #: The field that looks like a credential, by name only. The value is never
    #: read, never stored and never rendered.
    credential_field: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class BuildTool:
    """One orchestrator found in this repository."""

    name: str
    config_path: str
    cache: CacheConfig


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def read_nx(path: Path) -> CacheConfig:
    """Nx cache configuration.

    `nxCloudAccessToken` in a committed `nx.json` is the finding. A read-write
    Nx Cloud token lets its holder write cache entries that every developer and
    every CI run will then treat as trusted build output -- so it belongs in an
    environment variable, not in a file with a git history.
    """
    payload = _load_json(path)
    if not payload:
        return CacheConfig(detail="nx.json could not be parsed.")

    for field in ("nxCloudAccessToken", "accessToken"):
        if payload.get(field):
            return CacheConfig(
                remote_configured=True,
                credential_field=field,
                detail=(
                    f"nx.json sets `{field}`, which is a cache credential in a committed file."
                ),
            )
    if payload.get("nxCloudId") or payload.get("nxCloudUrl"):
        return CacheConfig(
            remote_configured=True,
            detail="Nx Cloud is configured; the token comes from the environment.",
        )
    return CacheConfig(detail="Local cache only.")


def read_turbo(path: Path) -> CacheConfig:
    """Turborepo cache configuration."""
    payload = _load_json(path)
    if not payload:
        return CacheConfig(detail="turbo.json could not be parsed.")

    remote = payload.get("remoteCache")
    if isinstance(remote, dict):
        if remote.get("signature"):
            return CacheConfig(
                remote_configured=True,
                credential_field="remoteCache.signature",
                detail="turbo.json enables remote-cache signing.",
            )
        if remote.get("enabled") is not False:
            return CacheConfig(
                remote_configured=True,
                detail="A remote cache is configured; credentials come from the environment.",
            )
    return CacheConfig(detail="Local cache only.")


_BAZEL_REMOTE = re.compile(r"^\s*(?:build|common)?[^#\n]*--remote_cache=", re.MULTILINE)
_BAZEL_HEADER = re.compile(r"--remote_header=\s*[Aa]uthorization", re.MULTILINE)


def read_bazelrc(path: Path) -> CacheConfig:
    """Bazel remote-cache configuration, from `.bazelrc`.

    `--remote_header=Authorization=...` in a committed `.bazelrc` is the same
    class of problem as an Nx token, and more common, because `.bazelrc` reads
    like a flags file rather than like a secret.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return CacheConfig(detail=".bazelrc could not be read.")

    if _BAZEL_HEADER.search(text):
        return CacheConfig(
            remote_configured=True,
            credential_field="--remote_header=Authorization",
            detail=".bazelrc passes an Authorization header for the remote cache.",
        )
    if _BAZEL_REMOTE.search(text):
        return CacheConfig(
            remote_configured=True,
            detail="A remote cache is configured in .bazelrc.",
        )
    return CacheConfig(detail="Local cache only.")


def detect_build_tools(root: Path) -> tuple[BuildTool, ...]:
    """Which orchestrators this repository uses, and how each caches.

    Nothing is executed. `nx show projects` and `bazel info` both start a
    long-lived daemon, and a diagnostic that leaves a JVM running on somebody's
    machine is not read-only in any sense that matters.
    """
    found: list[BuildTool] = []
    seen: set[str] = set()

    for filename, tool in BUILD_TOOLS:
        path = root / filename
        if not path.is_file() or tool in seen:
            continue
        seen.add(tool)

        if tool == "nx":
            cache = read_nx(path)
        elif tool == "turborepo":
            cache = read_turbo(path)
        elif tool == "bazel":
            bazelrc = root / ".bazelrc"
            cache = (
                read_bazelrc(bazelrc)
                if bazelrc.is_file()
                else CacheConfig(detail="No .bazelrc; cache configuration is elsewhere.")
            )
        else:
            cache = CacheConfig(detail="Cache configuration not modelled for this tool.")

        found.append(BuildTool(name=tool, config_path=filename, cache=cache))

    return tuple(found)
