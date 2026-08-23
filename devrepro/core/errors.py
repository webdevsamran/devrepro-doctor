"""Typed error taxonomy for DevRepro Doctor.

Every error the CLI can surface maps to a stable exit code. Probes and
rules must raise (or capture) these rather than bare exceptions so the
engine can degrade gracefully.
"""

from __future__ import annotations

from devrepro.core.exit_codes import ExitCode

__all__ = [
    "DevReproError",
    "DiffError",
    "PluginError",
    "PolicyError",
    "PrivacyViolationError",
    "ProbeError",
    "ProbeTimeoutError",
    "ProjectParseError",
    "RemediationError",
    "RemediationRefusedError",
    "SnapshotError",
    "SnapshotSchemaError",
]


class DevReproError(Exception):
    """Base class for all DevRepro errors. Maps to INTERNAL_ERROR."""

    exit_code: ExitCode = ExitCode.INTERNAL_ERROR

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class ProbeError(DevReproError):
    """A probe failed. The engine captures this; the scan continues."""


class ProbeTimeoutError(ProbeError):
    """A probe exceeded its time budget."""


class PolicyError(DevReproError):
    """A .devrepro.toml policy is missing or invalid."""


class SnapshotError(DevReproError):
    """Snapshot creation or storage failed."""


class SnapshotSchemaError(SnapshotError):
    """A snapshot file failed schema validation (untrusted input)."""


class DiffError(DevReproError):
    """A diff could not be computed (e.g. incompatible schema versions)."""


class RemediationError(DevReproError):
    """Remediation planning or execution failed."""


class RemediationRefusedError(RemediationError):
    """Execution refused: risk too high, preconditions unmet, or the
    user declined confirmation. Never a partial mutation.
    """


class PrivacyViolationError(DevReproError):
    """Probable secret detected in output; export blocked."""


class ProjectParseError(DevReproError):
    """A project manifest could not be parsed."""


class PluginError(DevReproError):
    """A plugin could not be loaded or violated the plugin API."""
