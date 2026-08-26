"""Environment-manager project diagnostics.

DevRepro Doctor deliberately does NOT replace Nix, devenv, Devbox, mise,
asdf or direnv — it diagnoses how well the *project* declares its
expectations to them and whether the active toolchain matches those
declarations. See INTEROP.md for the source-of-truth policy.

Capabilities (all read-only):
- detection of asdf ``.tool-versions``, mise ``mise.toml``/``.mise.toml``,
  nvm ``.nvmrc``, direnv ``.envrc``, Nix ``flake.nix``/``flake.lock``,
  devenv ``devenv.yaml``/``devenv.nix`` and Devbox ``devbox.json``/
  ``devbox.lock``;
- pinned-tool extraction from ``.tool-versions`` and TOML-style mise files
  (``[tools]`` table);
- active-vs-pinned mismatch checks when a version resolver is supplied;
- lockfile presence checks so flake/devbox pins are actually committed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    ReadText = Callable[[Path], "str | None"]
else:  # pragma: no cover - runtime alias for annotations only
    ReadText = object

__all__ = [
    "EnvManagerFinding",
    "EnvManagerInventory",
    "ManagerKind",
    "PinnedTool",
    "inventory_project",
    "parse_mise_toml_tools",
    "parse_tool_versions",
    "pinned_vs_active",
]


@dataclass(frozen=True)
class ManagerKind:
    """A detected environment-manager configuration in a project."""

    manager: str  # nix | devenv | devbox | mise | asdf | direnv | nvm
    files: tuple[str, ...]
    locked: bool | None = None  # True when an explicit lockfile exists


@dataclass(frozen=True)
class PinnedTool:
    name: str
    version: str
    source_file: str


@dataclass(frozen=True)
class EnvManagerFinding:
    """One actionable observation about env-manager declarations."""

    manager: str
    severity: str  # info | warn
    message: str


@dataclass(frozen=True)
class EnvManagerInventory:
    managers: tuple[ManagerKind, ...]
    pins: tuple[PinnedTool, ...]
    findings: tuple[EnvManagerFinding, ...]


def parse_tool_versions(text: str) -> list[PinnedTool]:
    """Parse asdf/mise ``.tool-versions`` format: ``<name> <version>...``."""
    pins: list[PinnedTool] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        # A tool may declare multiple versions; record each.
        for version in parts[1:]:
            pins.append(PinnedTool(parts[0], version, ".tool-versions"))
    return pins


def parse_mise_toml_tools(text: str) -> list[PinnedTool]:
    """Extract ``[tools]`` entries from a mise.toml file.

    Supports bare-string values (``node = "22"``), inline tables
    (``node = { version = "22", ... }``) and array values. This is a
    deliberate minimal reader: mise's full TOML schema is larger, and any
    value we cannot confidently read is skipped rather than guessed.
    """
    pins: list[PinnedTool] = []
    in_tools = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            in_tools = line.strip("[]").strip() == "tools"
            continue
        if not in_tools or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip().strip('"').strip("'")
        value = value.strip()
        m = re.match(r'^\{.*?version\s*=\s*"([^"]+)"', value)
        if m:
            pins.append(PinnedTool(name, m.group(1), "mise.toml"))
            continue
        m = re.match(r'^"([^"]+)"', value)
        if m:
            pins.append(PinnedTool(name, m.group(1), "mise.toml"))
    return pins


def inventory_project(
    project_dir: Path,
    read_text: ReadText | None = None,
) -> EnvManagerInventory:
    """Detect environment-manager configurations under *project_dir*."""
    reader: Callable[[Path], str | None] = read_text or (
        lambda p: p.read_text(encoding="utf-8") if p.is_file() else None
    )

    def exists(name: str) -> bool:
        return (project_dir / name).is_file()

    def content(name: str) -> str | None:
        return reader(project_dir / name)

    managers: list[ManagerKind] = []
    pins: list[PinnedTool] = []
    findings: list[EnvManagerFinding] = []

    if exists(".tool-versions"):
        managers.append(ManagerKind("asdf", (".tool-versions",)))
        text = content(".tool-versions")
        if text:
            pins.extend(parse_tool_versions(text))
        if exists("mise.toml") or exists(".mise.toml"):
            findings.append(
                EnvManagerFinding(
                    "mise",
                    "warn",
                    "both .tool-versions and mise.toml present; mise reads both but "
                    "duplicate pinning invites drift",
                )
            )
    if exists(".nvmrc"):
        managers.append(ManagerKind("nvm", (".nvmrc",)))
    if exists("mise.toml") or exists(".mise.toml"):
        fname = "mise.toml" if exists("mise.toml") else ".mise.toml"
        managers.append(ManagerKind("mise", (fname,)))
        text = content(fname)
        if text:
            pins.extend(parse_mise_toml_tools(text))
    if exists(".envrc"):
        managers.append(ManagerKind("direnv", (".envrc",)))
        findings.append(
            EnvManagerFinding(
                "direnv",
                "info",
                ".envrc contains executable shell code; review it with `direnv status` "
                "before trusting this checkout on a new machine",
            )
        )
    if exists("flake.nix"):
        locked = exists("flake.lock")
        files = ("flake.nix", "flake.lock") if locked else ("flake.nix",)
        managers.append(ManagerKind("nix", files, locked))
        if not locked:
            findings.append(
                EnvManagerFinding(
                    "nix",
                    "warn",
                    "flake.nix without flake.lock is not reproducible; commit flake.lock "
                    "(`nix flake lock`) for deterministic environments",
                )
            )
    if exists("devenv.yaml"):
        managers.append(ManagerKind("devenv", ("devenv.yaml",), exists("devenv.lock")))
    elif exists("devenv.nix"):
        managers.append(ManagerKind("devenv", ("devenv.nix",), exists("devenv.lock")))
    if exists("devbox.json"):
        locked = exists("devbox.lock")
        files = ("devbox.json", "devbox.lock") if locked else ("devbox.json",)
        managers.append(ManagerKind("devbox", files, locked))
        if not locked:
            findings.append(
                EnvManagerFinding(
                    "devbox",
                    "warn",
                    "devbox.json without devbox.lock; run `devbox lock` and commit it",
                )
            )

    return EnvManagerInventory(tuple(managers), tuple(pins), tuple(findings))


def pinned_vs_active(
    pins: tuple[PinnedTool, ...],
    active_versions: dict[str, str],
) -> list[EnvManagerFinding]:
    """Compare pinned versions against resolved active toolchain versions.

    ``active_versions`` maps tool name -> installed version string (only the
    leading numeric version is compared). Tools that cannot be resolved are
    reported as informational, never as failures — absence of a manager is a
    legitimate state DevRepro explains, not punishes.
    """
    out: list[EnvManagerFinding] = []
    for pin in pins:
        active = active_versions.get(pin.name)
        source = pin.source_file.split(".")[0].lstrip(".") or "pin"
        if active is None:
            out.append(
                EnvManagerFinding(
                    source,
                    "info",
                    f"{pin.name} pinned to {pin.version} in {pin.source_file} but no "
                    f"'{pin.name}' installation was resolvable on this machine",
                )
            )
            continue
        pin_major = re.match(r"\d+", pin.version)
        act_major = re.match(r"\d+", active)
        if pin_major and act_major and pin_major.group(0) != act_major.group(0):
            out.append(
                EnvManagerFinding(
                    source,
                    "warn",
                    f"{pin.name}: project pins {pin.version} ({pin.source_file}) but the "
                    f"active toolchain resolves to {active}; major-version mismatch "
                    "commonly breaks builds",
                )
            )
        elif active != pin.version:
            out.append(
                EnvManagerFinding(
                    source,
                    "info",
                    f"{pin.name}: pinned {pin.version}, active {active} "
                    "(same major; verify patch-level requirements)",
                )
            )
    return out
