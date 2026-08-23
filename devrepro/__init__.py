"""DevRepro Doctor SDK.

Cross-platform diagnostics, reproducibility auditing and safe repair
planning for developer machines. Read-only by default; privacy-safe by
construction.

Created by @webdevsamran.
"""

from __future__ import annotations

__version__ = "0.1.0"

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
