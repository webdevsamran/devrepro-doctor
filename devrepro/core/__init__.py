"""Core typed contracts for DevRepro Doctor."""

from __future__ import annotations

from devrepro.core.errors import (
    DevReproError,
    DiffError,
    PluginError,
    PolicyError,
    PrivacyViolationError,
    ProbeError,
    ProbeTimeoutError,
    ProjectParseError,
    RemediationError,
    RemediationRefusedError,
    SnapshotError,
    SnapshotSchemaError,
)
from devrepro.core.exit_codes import ExitCode
from devrepro.core.models import (
    ContainerState,
    DiffClassification,
    DiffEntry,
    EnvironmentDiff,
    Evidence,
    Finding,
    FindingState,
    GpuStack,
    PathAnalysis,
    PathEntry,
    PlatformInfo,
    Policy,
    ProjectRequirement,
    Remediation,
    ReproducibilityPoint,
    ReproducibilityScore,
    RequirementKind,
    RiskLevel,
    ScanReport,
    Snapshot,
    ToolInstallation,
    VirtualenvInfo,
    WslState,
)
from devrepro.core.runner import (
    CommandResult,
    CommandRunner,
    RecordingRunner,
    SubprocessRunner,
)
from devrepro.core.versioning import (
    SpecClause,
    SpecSet,
    Version,
    parse_spec,
    parse_version,
    satisfies,
)

PLUGIN_API_VERSION = "1"

__all__ = [
    "PLUGIN_API_VERSION",
    # runner
    "CommandResult",
    "CommandRunner",
    # models
    "ContainerState",
    # errors
    "DevReproError",
    "DiffClassification",
    "DiffEntry",
    "DiffError",
    "EnvironmentDiff",
    "Evidence",
    # exit codes
    "ExitCode",
    "Finding",
    "FindingState",
    "GpuStack",
    "PathAnalysis",
    "PathEntry",
    "PlatformInfo",
    "PluginError",
    "Policy",
    "PolicyError",
    "PrivacyViolationError",
    "ProbeError",
    "ProbeTimeoutError",
    "ProjectParseError",
    "ProjectRequirement",
    "RecordingRunner",
    "Remediation",
    "RemediationError",
    "RemediationRefusedError",
    "ReproducibilityPoint",
    "ReproducibilityScore",
    "RequirementKind",
    "RiskLevel",
    "ScanReport",
    "Snapshot",
    "SnapshotError",
    "SnapshotSchemaError",
    # versioning
    "SpecClause",
    "SpecSet",
    "SubprocessRunner",
    "ToolInstallation",
    "Version",
    "VirtualenvInfo",
    "WslState",
    "parse_spec",
    "parse_version",
    "satisfies",
]
