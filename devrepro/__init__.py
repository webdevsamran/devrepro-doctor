"""DevRepro Doctor SDK.

Cross-platform diagnostics, reproducibility auditing and safe repair
planning for developer machines. Read-only by default; privacy-safe by
construction.

Created by @webdevsamran.
"""

from __future__ import annotations

from devrepro.core import (
    PLUGIN_API_VERSION,
    CommandResult,
    CommandRunner,
    ContainerState,
    DiffClassification,
    DiffEntry,
    EnvironmentDiff,
    Evidence,
    ExitCode,
    Finding,
    FindingState,
    GpuStack,
    PathAnalysis,
    PathEntry,
    PlatformInfo,
    Policy,
    ProjectRequirement,
    RecordingRunner,
    Remediation,
    ReproducibilityPoint,
    ReproducibilityScore,
    RequirementKind,
    RiskLevel,
    ScanReport,
    Snapshot,
    SubprocessRunner,
    ToolInstallation,
    VirtualenvInfo,
    WslState,
    parse_spec,
    parse_version,
    satisfies,
)


def _installed_version() -> str:
    """The version actually installed, not a literal in this file.

    `__version__` was hardcoded to "0.1.0" while `pyproject.toml` said 0.2.0,
    so every scan table printed "DevRepro Doctor v0.1.0", every snapshot
    recorded `devrepro_version: 0.1.0`, and every SARIF upload carried the
    wrong tool version. A stored snapshot is meant to be comparable across
    machines and time; a version field that never moves makes two snapshots
    from different releases look like they came from the same one.
    """
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("devrepro-doctor")
    except PackageNotFoundError:  # source tree, not installed
        import pathlib

        pyproject = pathlib.Path(__file__).resolve().parent.parent / "pyproject.toml"
        try:
            import tomllib

            return str(tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"])
        except Exception:
            return "unknown"


__version__ = _installed_version()

__all__ = [
    "PLUGIN_API_VERSION",
    "CommandResult",
    "CommandRunner",
    "ContainerState",
    "DiffClassification",
    "DiffEntry",
    "EnvironmentDiff",
    "Evidence",
    "ExitCode",
    "Finding",
    "FindingState",
    "GpuStack",
    "PathAnalysis",
    "PathEntry",
    "PlatformInfo",
    "Policy",
    "ProjectRequirement",
    "RecordingRunner",
    "Remediation",
    "ReproducibilityPoint",
    "ReproducibilityScore",
    "RequirementKind",
    "RiskLevel",
    "ScanReport",
    "Snapshot",
    "SubprocessRunner",
    "ToolInstallation",
    "VirtualenvInfo",
    "WslState",
    "__version__",
    "parse_spec",
    "parse_version",
    "satisfies",
]
