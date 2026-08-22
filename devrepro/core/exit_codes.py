"""Stable exit codes for the DevRepro Doctor CLI.

These codes are a public contract used by onboarding scripts and CI.
Never change the meaning of an existing code; only append new ones.
"""

from __future__ import annotations

from enum import IntEnum

__all__ = ["ExitCode"]


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