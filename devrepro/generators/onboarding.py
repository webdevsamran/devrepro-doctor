"""A setup script for what *this* machine is missing, not a generic README.

Onboarding documents rot because they describe a machine nobody has: they list
every dependency, including the eleven a new starter already has, and the one
that matters is on line 40 between two they can skip. The reader stops reading
around line 12 and installs things they had.

This emits the difference instead. Policy says what the project requires, the
scan says what is here, and the script covers exactly the gap -- which on most
machines is two lines and on a fresh one is the whole list.

**It is a script to read, not a script that ran.** Nothing is executed. Every
install command is a real command a person could have typed, the risky ones are
commented rather than omitted, and the header says plainly that it was
generated from a scan of one machine at one moment. That last part matters: the
same file handed to somebody else is wrong for their machine, and a generated
artefact that does not say when and where it came from will be found in a wiki
two years later and followed.

The commands are per-platform and per-tool, from a table. Where no command is
known the tool is listed with a link rather than an invented one-liner: a wrong
install command in a setup script is worse than an absent one, because somebody
runs it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from devrepro.core.models import Policy, ScanReport

__all__ = [
    "INSTALL_COMMANDS",
    "MissingRequirement",
    "missing_requirements",
    "render_onboarding_script",
]

#: (tool) -> (windows, macos, linux). `None` means no command this project is
#: confident enough to print; the tool is named and left to the reader.
INSTALL_COMMANDS: dict[str, tuple[str | None, str | None, str | None]] = {
    "python": ("winget install Python.Python.3.12", "brew install python@3.12", None),
    "node": ("winget install OpenJS.NodeJS.LTS", "brew install node", None),
    "go": ("winget install GoLang.Go", "brew install go", None),
    "rustc": (
        "winget install Rustlang.Rustup",
        "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh",
        "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh",
    ),
    "cargo": (None, None, None),
    "git": ("winget install Git.Git", "brew install git", "sudo apt-get install -y git"),
    "docker": ("winget install Docker.DockerDesktop", "brew install --cask docker", None),
    "kubectl": ("winget install Kubernetes.kubectl", "brew install kubectl", None),
    "java": ("winget install EclipseAdoptium.Temurin.21.JDK", "brew install openjdk@21", None),
    "dotnet": ("winget install Microsoft.DotNet.SDK.8", "brew install dotnet", None),
    "uv": (
        "winget install astral-sh.uv",
        "brew install uv",
        "curl -LsSf https://astral.sh/uv/install.sh | sh",
    ),
    "pnpm": ("npm install -g pnpm", "npm install -g pnpm", "npm install -g pnpm"),
    "yarn": ("npm install -g yarn", "npm install -g yarn", "npm install -g yarn"),
}

#: Commands that fetch and execute a remote script. Emitted commented out, with
#: the reason: piping a URL into a shell is a decision, and a generated file is
#: not the place to make it on somebody's behalf.
_PIPES_TO_SHELL = ("| sh", "| bash", "iex ")


@dataclass(frozen=True)
class MissingRequirement:
    """Something the policy requires that this machine does not have."""

    name: str
    required: str
    detected: str | None = None

    @property
    def wrong_version(self) -> bool:
        return self.detected is not None


def missing_requirements(report: ScanReport, policy: Policy) -> tuple[MissingRequirement, ...]:
    """What the policy asks for that this machine does not satisfy.

    Both halves: absent tools, and present tools at the wrong version. The
    second is the one a hand-written onboarding document never covers, because
    the person writing it had the right version.
    """
    installed = report.active_versions()
    missing: list[MissingRequirement] = []

    from devrepro.core.versioning import satisfies

    for source in (policy.required_runtimes, policy.required_tools):
        for name, spec in sorted(source.items()):
            version = installed.get(name)
            if version is None:
                missing.append(MissingRequirement(name=name, required=spec))
                continue
            try:
                if not satisfies(version, spec):
                    missing.append(MissingRequirement(name=name, required=spec, detected=version))
            except (ValueError, TypeError):
                # An unparseable version is not evidence of a mismatch. It is
                # reported by the rule packs; inventing an install step for it
                # here would tell somebody to reinstall a working tool.
                continue
    return tuple(missing)


def _command_for(name: str, platform: str) -> str | None:
    entry = INSTALL_COMMANDS.get(name)
    if entry is None:
        return None
    index = {"windows": 0, "macos": 1}.get(platform, 2)
    return entry[index]


def render_onboarding_script(
    report: ScanReport,
    policy: Policy,
    *,
    platform: str,
    generated_at: str,
) -> str:
    """A commented setup script covering the gap between policy and this machine.

    `generated_at` is passed in rather than read from the clock, so the same
    inputs produce the same file -- which is what makes it reviewable in a diff
    and testable at all.
    """
    missing = missing_requirements(report, policy)
    # Both shells use `#`; the conditional this replaced had identical branches.
    comment = "#"
    lines: list[str] = []

    if platform == "windows":
        lines.append("# PowerShell. Read before running.")
    else:
        lines.append("#!/usr/bin/env bash")
        lines.append("set -euo pipefail")
    lines.append("")
    lines.append(f"{comment} Generated by devrepro {report.devrepro_version} at {generated_at}")
    lines.append(
        f"{comment} from a scan of ONE machine ({report.platform.os_name} "
        f"{report.platform.arch}). It covers what that machine was missing, not"
    )
    lines.append(f"{comment} everything the project needs. Re-run `devrepro onboard` on yours.")
    lines.append(f"{comment} Nothing here has been executed.")
    lines.append("")

    if not missing:
        lines.append(f"{comment} Nothing to install: this machine already satisfies the policy.")
        lines.append("")
        return "\n".join(lines) + "\n"

    for item in missing:
        if item.wrong_version:
            lines.append(
                f"{comment} {item.name}: have {item.detected}, policy requires {item.required}"
            )
        else:
            lines.append(f"{comment} {item.name}: not installed, policy requires {item.required}")

        command = _command_for(item.name, platform)
        if command is None:
            lines.append(
                f"{comment}   No install command is printed for {item.name} on this "
                "platform. A wrong one in a setup script is worse than none, because"
            )
            lines.append(f"{comment}   somebody runs it. Install it the way your team does.")
        elif any(marker in command for marker in _PIPES_TO_SHELL):
            lines.append(
                f"{comment}   This downloads and executes a remote script. That is a "
                "decision, and a generated file should not make it for you:"
            )
            lines.append(f"{comment}   {command}")
        else:
            lines.append(command)
        lines.append("")

    lines.append(f"{comment} Then re-check: devrepro check")
    return "\n".join(lines) + "\n"
