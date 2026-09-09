"""Do the commands a manifest declares still exist in the project?

A manifest ages differently from the code it describes. Someone renames an npm
script, deletes a Makefile target, moves a helper -- and `AGENTS.md` keeps
telling every agent to run the old name. The command resolves (npm is
installed, make is installed), so a PATH check passes it, and the agent
discovers the problem by running it and reading an error.

This is the check one level in: not "does `npm` exist" but "does `npm run
build` refer to a script this project still defines".

Also here: whether a repository's several manifests agree with each other. A
project carrying `AGENTS.md` and `CLAUDE.md` has two documents that drift
independently, and an agent reads whichever one its vendor looks for.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from devrepro.probes.helpers import read_text_safe

if TYPE_CHECKING:
    from collections.abc import Iterable

    from devrepro.agents.manifest import AgentManifest, DeclaredCommand

__all__ = [
    "ManifestDisagreement",
    "StaleCommand",
    "compare_manifests",
    "project_script_names",
    "stale_commands",
]


@dataclass(frozen=True)
class StaleCommand:
    """A declared command whose target no longer exists in the project."""

    raw: str
    runner: str
    target: str
    manifest: str
    line: int
    available: tuple[str, ...]

    @property
    def summary(self) -> str:
        known = ", ".join(self.available[:6]) or "none defined"
        return (
            f"{self.raw!r} refers to {self.runner} target {self.target!r}, "
            f"which this project does not define (available: {known})"
        )


@dataclass(frozen=True)
class ManifestDisagreement:
    """Two manifests that tell an agent different things."""

    command: str
    present_in: tuple[str, ...]
    absent_from: tuple[str, ...]


def project_script_names(root: Path | str) -> dict[str, tuple[str, ...]]:
    """Runnable target names this project defines, by runner.

    Only sources that genuinely declare named entry points are read. Guessing
    at shell functions or CI job names would produce false confidence, and a
    freshness check that invents targets is worse than none.
    """
    root = Path(root)
    scripts: dict[str, tuple[str, ...]] = {}

    package_json = read_text_safe(root / "package.json")
    if package_json:
        try:
            data = json.loads(package_json)
        except ValueError:
            data = {}
        entries = data.get("scripts") if isinstance(data, dict) else None
        if isinstance(entries, dict):
            scripts["npm"] = tuple(sorted(str(k) for k in entries))

    makefile = None
    for name in ("Makefile", "makefile", "GNUmakefile"):
        makefile = read_text_safe(root / name)
        if makefile:
            break
    if makefile:
        targets = re.findall(r"^([A-Za-z0-9][\w.-]*)\s*:(?!=)", makefile, flags=re.MULTILINE)
        scripts["make"] = tuple(sorted(set(targets)))

    pyproject = read_text_safe(root / "pyproject.toml")
    if pyproject:
        import tomllib

        try:
            data = tomllib.loads(pyproject)
        except (ValueError, TypeError):
            data = {}
        console = data.get("project", {}).get("scripts", {})
        if isinstance(console, dict) and console:
            scripts["python-console"] = tuple(sorted(str(k) for k in console))

    just = read_text_safe(root / "justfile") or read_text_safe(root / "Justfile")
    if just:
        recipes = re.findall(r"^([A-Za-z0-9][\w-]*)\s*:", just, flags=re.MULTILINE)
        scripts["just"] = tuple(sorted(set(recipes)))

    return scripts


#: How to read a target out of a command, per runner. The value is the number
#: of leading tokens to skip before the target name.
_RUNNER_OFFSETS = {
    ("npm", "run"): 2,
    ("pnpm", "run"): 2,
    ("yarn", "run"): 2,
    ("bun", "run"): 2,
    ("make",): 1,
    ("just",): 1,
}


def _target_of(command: str) -> tuple[str, str] | None:
    """The (runner, target) a command invokes, if it names one."""
    tokens = [t for t in command.split() if not t.startswith("-")]
    if not tokens:
        return None
    for prefix, offset in _RUNNER_OFFSETS.items():
        if tuple(tokens[: len(prefix)]) == prefix and len(tokens) > offset:
            runner = "npm" if prefix[0] in {"npm", "pnpm", "yarn", "bun"} else prefix[0]
            return runner, tokens[offset]
    return None


def stale_commands(
    commands: Iterable[DeclaredCommand],
    root: Path | str,
    scripts: dict[str, tuple[str, ...]] | None = None,
) -> list[StaleCommand]:
    """Declared commands whose target the project no longer defines.

    A runner with no declared targets at all is skipped rather than reported:
    absence of a `scripts` block means the check has nothing to say, not that
    every command is wrong.
    """
    root = Path(root)
    # Targets are looked up per directory: `cd web && npm run lint` must be
    # checked against web/package.json, which is where a monorepo keeps them.
    by_directory: dict[str, dict[str, tuple[str, ...]]] = {}

    def _known_for(directory: str) -> dict[str, tuple[str, ...]]:
        if scripts is not None:
            return scripts
        if directory not in by_directory:
            by_directory[directory] = project_script_names(root / directory)
        return by_directory[directory]

    stale: list[StaleCommand] = []

    for command in commands:
        parsed = _target_of(command.raw)
        if parsed is None:
            continue
        runner, target = parsed
        available = _known_for(command.cwd).get(runner)
        if not available or target in available:
            continue
        stale.append(
            StaleCommand(
                raw=command.raw,
                runner=runner,
                target=target,
                manifest=command.manifest,
                line=command.line,
                available=available,
            )
        )
    return stale


def compare_manifests(manifests: Iterable[AgentManifest]) -> list[ManifestDisagreement]:
    """Commands one manifest declares and another omits.

    A repository with both `AGENTS.md` and `CLAUDE.md` has two documents that
    drift apart, and an agent reads whichever its vendor looks for. Reported
    only when at least two manifests exist -- with one there is nothing to
    disagree with.
    """
    manifest_list = list(manifests)
    if len(manifest_list) < 2:
        return []

    by_manifest = {
        m.path: {_command_key(c.raw) for c in m.commands if _command_key(c.raw)}
        for m in manifest_list
    }
    every_command = set().union(*by_manifest.values()) if by_manifest else set()

    disagreements: list[ManifestDisagreement] = []
    for command in sorted(every_command):
        present = tuple(sorted(p for p, cmds in by_manifest.items() if command in cmds))
        absent = tuple(sorted(p for p, cmds in by_manifest.items() if command not in cmds))
        if present and absent:
            disagreements.append(
                ManifestDisagreement(command=command, present_in=present, absent_from=absent)
            )
    return disagreements


def _command_key(command: str) -> str:
    """Program plus first meaningful argument, for comparing two spellings."""
    tokens = [t for t in command.split() if not t.startswith("-")]
    if not tokens:
        return ""
    if len(tokens) > 1:
        return f"{tokens[0]} {tokens[1]}"
    return tokens[0]
