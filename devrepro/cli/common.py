"""Shared CLI helpers: option defaults, output emission, exit-code mapping.

Kept dependency-light and side-effect-free so every command module can
import it at module scope without slowing CLI startup.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import typer

from devrepro.core.exit_codes import ExitCode

if TYPE_CHECKING:
    from pathlib import Path

    from devrepro.core.models import Policy

JsonOption = typer.Option(False, "--json", help="Emit machine-readable JSON.")
PolicyOption = typer.Option(None, "--policy", help="Path to .devrepro.toml policy.")
QuietOption = typer.Option(
    False,
    "--quiet",
    "-q",
    help="Suppress output; communicate only through the exit code.",
)


def color_enabled() -> bool:
    """Whether ANSI colour should be written to stdout.

    Honours the `NO_COLOR` convention (https://no-color.org): any value,
    including an empty one, disables colour. `FORCE_COLOR` wins over it, which
    is what CI systems that render ANSI in their log viewers set.

    Colour is also dropped when stdout is not a terminal, so a redirected
    report does not arrive full of escape sequences.
    """
    import os
    import sys

    if os.environ.get("FORCE_COLOR"):
        return True
    if "NO_COLOR" in os.environ:
        return False
    return sys.stdout.isatty()


def secho(message: str, *, fg: str | None = None, err: bool = False) -> None:
    """`typer.secho` that respects NO_COLOR and non-TTY output."""
    typer.secho(message, fg=fg if color_enabled() else None, err=err)


def load_policy_or_none(path: Path | None) -> Policy | None:
    """Load a .devrepro.toml policy; None when no path given."""
    if path is None:
        return None
    from devrepro.project.policy import load_policy

    return load_policy(path)


def emit(data: object, as_json: bool, *, quiet: bool = False) -> None:
    """Echo payload as pretty JSON or plain text.

    `quiet` suppresses the payload entirely. The exit code is the whole
    interface in that mode, which is what a shell script or a pre-commit hook
    wants: a gate that prints nothing when it passes and still fails loudly.
    """
    if quiet:
        return
    if as_json:
        typer.echo(json.dumps(data, indent=2, default=str))
    else:
        typer.echo(data)


def exit_for(findings_states: set[str]) -> int:
    """Map finding states to the stable exit-code contract."""
    if "BLOCKED" in findings_states or "ERROR" in findings_states:
        return ExitCode.BLOCKED
    if "WARN" in findings_states or "UNKNOWN" in findings_states:
        return ExitCode.READY_WITH_WARNINGS
    return ExitCode.READY


def local_tool_versions() -> dict[str, str]:
    """Best-effort active versions of common tools (never raises)."""
    from devrepro.core.runner import SubprocessRunner

    runner = SubprocessRunner()
    out: dict[str, str] = {}
    probes = {
        "python": ("python", ("--version",)),
        "node": ("node", ("--version",)),
        "go": ("go", ("version",)),
        "dotnet": ("dotnet", ("--version",)),
        "java": ("java", ("-version",)),
        "ruby": ("ruby", ("--version",)),
        "php": ("php", ("--version",)),
    }
    for name, (exe, args) in probes.items():
        try:
            res = runner.run((exe, *args), timeout=5.0)
            text = (res.stdout or "") + (res.stderr or "")
            first = text.strip().splitlines()[0] if text.strip() else ""
            # extract a version-looking token
            import re as _re

            m = _re.search(r"(\d+\.\d+(\.\d+)?)", first)
            if m and res.returncode == 0:
                out[name] = m.group(1)
        except Exception:
            pass
    # fall back to installed Python distributions for library-style names
    from contextlib import suppress
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as dist_version

    for name in ("pydantic", "typer", "rich", "tomli", "httpx", "pytest"):
        if name not in out:
            with suppress(PackageNotFoundError):
                out[name] = dist_version(name)
    return out
