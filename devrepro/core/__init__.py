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
    # errors
    "DevReproError", "DiffError", "PluginError", "PolicyError",
    "PrivacyViolationError", "ProbeError", "ProbeTimeoutError",
    "ProjectParseError", "RemediationError", "RemediationRefusedError",
    "SnapshotError", "SnapshotSchemaError",
    # exit codes
    "ExitCode",
    # models
    "ContainerState", "DiffClassification", "DiffEntry", "EnvironmentDiff",
    "Evidence", "Finding", "FindingState", "GpuStack", "PathAnalysis",
    "PathEntry", "PlatformInfo", "Policy", "ProjectRequirement",
    "Remediation", "ReproducibilityPoint", "ReproducibilityScore",
    "RequirementKind", "RiskLevel", "ScanReport", "Snapshot",
    "ToolInstallation", "VirtualenvInfo", "WslState",
    # runner
    "CommandResult", "CommandRunner", "RecordingRunner", "SubprocessRunner",
    # versioning
    "SpecClause", "SpecSet", "Version", "parse_spec", "parse_version",
    "satisfies",
]