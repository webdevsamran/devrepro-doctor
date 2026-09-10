"""Stable exit codes for the DevRepro Doctor CLI.

These codes are a public contract used by onboarding scripts and CI.
Never change the meaning of an existing code; only append new ones.
"""

from __future__ import annotations

from enum import IntEnum

__all__ = ["MEANINGS", "ExitCode"]


class ExitCode(IntEnum):
    """Process exit codes with stable, documented meanings."""

    READY = 0
    """Scan succeeded with no blocking problems."""

    READY_WITH_WARNINGS = 1
    """Scan succeeded but warnings were found."""

    BLOCKED = 2
    """One or more BLOCKED/ERROR findings prevent a clean build."""

    INTERNAL_ERROR = 3
    """DevRepro itself failed (bug, unreadable input, bad arguments)."""

    USAGE_ERROR = 4
    """Invalid command-line usage."""


#: One sentence per code, for anything that has to *render* the contract rather
#: than branch on it.
#:
#: A separate mapping because the string literals under each member above are
#: discarded at import: Python keeps only a class docstring, so
#: ``ExitCode.BLOCKED.__doc__`` returns the *class* description for every
#: member. Reading them at runtime would have produced a contract document that
#: gave all five codes the same meaning -- correct-looking and useless.
#: ``tests/test_exit_codes_documented.py`` holds this against the enum.
MEANINGS: dict[ExitCode, str] = {
    ExitCode.READY: "Scan succeeded with no blocking problems.",
    ExitCode.READY_WITH_WARNINGS: "Scan succeeded but warnings were found.",
    ExitCode.BLOCKED: "One or more BLOCKED/ERROR findings prevent a clean build.",
    ExitCode.INTERNAL_ERROR: "DevRepro itself failed (bug, unreadable input, bad arguments).",
    ExitCode.USAGE_ERROR: "Invalid command-line usage.",
}
