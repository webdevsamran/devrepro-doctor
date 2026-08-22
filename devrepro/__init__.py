"""DevRepro Doctor SDK.

Cross-platform diagnostics, reproducibility auditing and safe repair
planning for developer machines. Read-only by default; privacy-safe by
construction.

Created by @webdevsamran.
"""

from __future__ import annotations

__version__ = "0.1.0"

from devrepro.core import (  # noqa: F401  (re-exported SDK surface)
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
    PLUGIN_API_VERSION,
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

__all__ = [
    "__version__",
    "PLUGIN_API_VERSION",
    "CommandResult", "CommandRunner", "SubprocessRunner", "RecordingRunner",
    "ExitCode",
    "ContainerState", "DiffClassification", "DiffEntry", "EnvironmentDiff",
    "Evidence", "Finding", "FindingState", "GpuStack", "PathAnalysis",
    "PathEntry", "PlatformInfo", "Policy", "ProjectRequirement",
    "Remediation", "ReproducibilityPoint", "ReproducibilityScore",
    "RequirementKind", "RiskLevel", "ScanReport", "Snapshot",
    "ToolInstallation", "VirtualenvInfo", "WslState",
    "parse_spec", "parse_version", "satisfies",
]