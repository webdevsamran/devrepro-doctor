"""Which files define what the environment must provide.

A gate that runs on every commit gets removed. `devrepro guard` describes
itself as designed for a pre-commit hook and then fails on any machine-wide
blocker, so a stopped Docker daemon blocks a commit that touches only Python
source. That is the shape of a check people switch off in week one.

The reframing is small and makes the gate survivable: this tool scans a
*machine*, and a machine has no per-file technical debt, so scoping to "changed
files" the way a linter does is meaningless. What is meaningful is the
**environment contract** -- the lockfiles, manifests, CI workflows and policy
that declare what a machine has to provide. When a commit changes one of those,
the machine is worth re-checking. When it changes a function body, it is not.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from devrepro.core.runner import CommandRunner, SubprocessRunner

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "CONTRACT_PATTERNS",
    "ContractChange",
    "changed_files",
    "classify_contract_path",
    "contract_changes",
]

#: Glob patterns for files that declare what an environment must provide,
#: paired with the kind of change they represent. Ordered: the first match
#: wins, so a lockfile is classified as a lockfile rather than a manifest.
CONTRACT_PATTERNS: tuple[tuple[str, str], ...] = (
    # Policy comes first: it is this project's own declaration.
    (".devrepro.toml", "policy"),
    ("**/.devrepro.toml", "policy"),
    # Lockfiles pin exact dependency trees.
    ("**/package-lock.json", "lockfile"),
    ("**/pnpm-lock.yaml", "lockfile"),
    ("**/yarn.lock", "lockfile"),
    ("**/bun.lockb", "lockfile"),
    ("**/poetry.lock", "lockfile"),
    ("**/uv.lock", "lockfile"),
    ("**/Pipfile.lock", "lockfile"),
    ("**/Cargo.lock", "lockfile"),
    ("**/composer.lock", "lockfile"),
    ("**/Gemfile.lock", "lockfile"),
    ("**/go.sum", "lockfile"),
    # Manifests declare ranges and runtimes.
    ("**/pyproject.toml", "manifest"),
    ("**/package.json", "manifest"),
    ("**/go.mod", "manifest"),
    ("**/Cargo.toml", "manifest"),
    ("**/composer.json", "manifest"),
    ("**/Gemfile", "manifest"),
    ("**/pom.xml", "manifest"),
    ("**/build.gradle", "manifest"),
    ("**/build.gradle.kts", "manifest"),
    ("**/*.csproj", "manifest"),
    ("**/global.json", "manifest"),
    ("**/requirements*.txt", "manifest"),
    # Version-manager pins.
    ("**/.nvmrc", "toolchain-pin"),
    ("**/.node-version", "toolchain-pin"),
    ("**/.python-version", "toolchain-pin"),
    ("**/.ruby-version", "toolchain-pin"),
    ("**/.java-version", "toolchain-pin"),
    ("**/.tool-versions", "toolchain-pin"),
    ("**/mise.toml", "toolchain-pin"),
    ("**/.mise.toml", "toolchain-pin"),
    ("**/rust-toolchain", "toolchain-pin"),
    ("**/rust-toolchain.toml", "toolchain-pin"),
    # What CI will demand of the machine.
    (".github/workflows/*.yml", "ci"),
    (".github/workflows/*.yaml", "ci"),
    (".gitlab-ci.yml", "ci"),
    ("azure-pipelines.yml", "ci"),
    ("Jenkinsfile", "ci"),
    # Container definitions.
    ("**/Dockerfile", "container"),
    ("**/Dockerfile.*", "container"),
    ("**/docker-compose*.yml", "container"),
    ("**/compose*.yml", "container"),
    ("**/devcontainer.json", "container"),
    # Environment declarations. `.env` itself is deliberately absent: it holds
    # values, and this project reads names only.
    ("**/.env.example", "env-names"),
    ("**/.env.sample", "env-names"),
    # Agent instructions are an environment contract for an agent.
    ("AGENTS.md", "agent-manifest"),
    ("CLAUDE.md", "agent-manifest"),
    (".cursorrules", "agent-manifest"),
)

#: `git status --porcelain` prefixes a rename with its old path.
_RENAME = re.compile(r"^.*? -> (.*)$")


@dataclass(frozen=True)
class ContractChange:
    """A changed file that alters what the environment must provide."""

    path: str
    kind: str


def classify_contract_path(path: str) -> str | None:
    """The contract kind a path represents, or None if it is ordinary source.

    Two subtleties, both of which produced wrong answers first time:

    * ``str.lstrip("./")`` strips *characters*, not a prefix, so it turns
      ``.nvmrc`` into ``nvmrc`` and ``.github/workflows/ci.yml`` into
      ``github/...``. Every dotfile in the table is a dotfile, so this matters
      for most of them. ``removeprefix`` is what was meant.
    * ``fnmatch`` has no recursive wildcard: ``*`` happily matches ``/``, so
      ``**/package-lock.json`` requires a literal separator and never matches a
      lockfile at the repository root. A ``**/`` pattern therefore also has to
      be tried against the bare filename.
    """
    normalised = path.replace("\\", "/").removeprefix("./")
    name = normalised.rsplit("/", 1)[-1]

    for pattern, kind in CONTRACT_PATTERNS:
        if fnmatch.fnmatch(normalised, pattern):
            return kind
        if pattern.startswith("**/") and fnmatch.fnmatch(name, pattern[3:]):
            return kind
        if "/" not in pattern and fnmatch.fnmatch(name, pattern):
            return kind
    return None


def changed_files(
    root: Path | str,
    *,
    base: str | None = None,
    runner: CommandRunner | None = None,
) -> list[str]:
    """Paths changed relative to ``base``, or uncommitted when base is None.

    Without a base this is the staged-and-unstaged working tree, which is what
    a pre-commit hook wants. With one it is the pull request, which is what CI
    wants. Both are read-only git plumbing.
    """
    runner = runner or SubprocessRunner()
    root = str(root)

    if base:
        # Three-dot: what this branch changed, not what also landed on base.
        result = runner.run(
            ("git", "-C", root, "diff", "--name-only", f"{base}...HEAD"), timeout=30
        )
        if not result.ok:
            # A shallow clone or an absent base ref; fall back to a two-dot
            # diff rather than reporting nothing and passing silently.
            result = runner.run(("git", "-C", root, "diff", "--name-only", base), timeout=30)
        if not result.ok:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    # `--untracked-files=all` matters: the default collapses a newly added
    # directory to `.devcontainer/` rather than listing the devcontainer.json
    # inside it, so a brand-new container definition -- exactly the change most
    # worth gating on -- goes unseen.
    result = runner.run(
        ("git", "-C", root, "status", "--porcelain", "--untracked-files=all"), timeout=30
    )
    if not result.ok:
        return []
    paths: list[str] = []
    for line in result.stdout.splitlines():
        entry = line[3:].strip() if len(line) > 3 else ""
        if not entry:
            continue
        rename = _RENAME.match(entry)
        paths.append(rename.group(1).strip() if rename else entry)
    return paths


def contract_changes(
    root: Path | str,
    *,
    base: str | None = None,
    runner: CommandRunner | None = None,
) -> list[ContractChange]:
    """Changed files that alter the environment contract."""
    changes: list[ContractChange] = []
    seen: set[str] = set()
    for path in changed_files(root, base=base, runner=runner):
        kind = classify_contract_path(path)
        if kind is None or path in seen:
            continue
        seen.add(path)
        changes.append(ContractChange(path=path, kind=kind))
    return sorted(changes, key=lambda c: (c.kind, c.path))


#: Which findings a contract change makes relevant, by rule-id prefix.
#:
#: Scoping decides *whether* to check; this decides *what*. Without it,
#: changing a Python manifest still blocks the commit because Docker happens to
#: be stopped -- better than gating on everything always, and still the wrong
#: answer for the change in front of you.
#:
#: A policy change maps to everything on purpose: the policy is the declaration
#: of what this machine must provide, so changing it re-opens every question.
RELEVANT_PREFIXES: dict[str, tuple[str, ...]] = {
    "policy": (),  # empty means "no filter": everything is relevant
    "lockfile": (
        "lockfiles",
        "python",
        "node",
        "go",
        "rust",
        "php",
        "ruby",
        "java",
        "dotnet",
        "path",
    ),
    "manifest": (
        "lockfiles",
        "python",
        "node",
        "go",
        "rust",
        "php",
        "ruby",
        "java",
        "dotnet",
        "cpp",
        "path",
    ),
    "toolchain-pin": (
        "lockfiles",
        "python",
        "node",
        "go",
        "rust",
        "php",
        "ruby",
        "java",
        "dotnet",
        "path",
        "shell",
    ),
    "ci": ("python", "node", "go", "rust", "java", "dotnet", "containers", "network"),
    "container": ("containers", "wsl", "virt"),
    "env-names": ("env",),
    "agent-manifest": ("agents", "hygiene", "path"),
}


def relevant_rule_prefixes(changes: list[ContractChange]) -> set[str] | None:
    """Rule-id prefixes worth gating on for these changes.

    Returns None when everything is relevant -- a policy change, or a kind not
    in the table. None means "do not filter", which is the safe direction: a
    gate that silently ignores a finding it does not recognise is worse than
    one that occasionally reports something adjacent.
    """
    if not changes:
        return set()
    prefixes: set[str] = set()
    for change in changes:
        mapped = RELEVANT_PREFIXES.get(change.kind)
        if mapped is None or mapped == ():
            return None
        prefixes.update(mapped)
    return prefixes
