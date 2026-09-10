"""Typed domain models for DevRepro Doctor.

These Pydantic models are the public SDK surface. They are the single
source of truth for JSON schemas under ``schemas/``. Models are immutable
(frozen) so scan results cannot be mutated after the privacy gate runs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "ContainerState",
    "DiffClassification",
    "DiffEntry",
    "EnvironmentDiff",
    "Evidence",
    "Finding",
    "FindingState",
    "GpuStack",
    "PathAnalysis",
    "PathEntry",
    "PlatformInfo",
    "Policy",
    "ProjectRequirement",
    "Remediation",
    "ReproducibilityPoint",
    "ReproducibilityScore",
    "RequirementKind",
    "RiskLevel",
    "ScanReport",
    "Snapshot",
    "ToolInstallation",
    "VirtualenvInfo",
    "WslState",
]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class _FrozenModel(BaseModel):
    """Base: immutable, forbids unknown fields on load."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class FindingState(StrEnum):
    """Lifecycle states for a finding."""

    PASS = "PASS"  # noqa: S105 - finding state name, not a credential
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


class RiskLevel(StrEnum):
    """Risk tiers for remediations. Only SAFE/LOW may be automated."""

    SAFE = "SAFE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class DiffClassification(StrEnum):
    """How a component differs between two snapshots."""

    SAME = "same"
    VERSION_DRIFT = "version-drift"
    MISSING = "missing"
    EXTRA = "extra"
    PATH_PRECEDENCE = "path-precedence"
    PLATFORM_EXPECTED = "platform-expected"
    PROJECT_CRITICAL = "project-critical"


class RequirementKind(StrEnum):
    RUNTIME = "runtime"
    TOOL = "tool"
    ENV_NAME = "env-name"
    CONTAINER = "container"
    COMPILER = "compiler"


class Evidence(_FrozenModel):
    """Proof backing a finding. Findings without evidence are invalid."""

    source: str = Field(description="command | file | env | system | network")
    command: tuple[str, ...] | None = None
    path: str | None = None
    excerpt: str | None = Field(default=None, description="Sanitized output excerpt")
    redacted: bool = True

    @field_validator("source")
    @classmethod
    def _check_source(cls, v: str) -> str:
        allowed = {"command", "file", "env", "system", "network"}
        if v not in allowed:
            raise ValueError(f"evidence source must be one of {sorted(allowed)}")
        return v

    @field_validator("command", mode="before")
    @classmethod
    def _coerce_command(cls, v: object) -> object:
        # accept a single command string and store it as a 1-tuple
        if isinstance(v, str):
            return (v,)
        return v


class Finding(_FrozenModel):
    """A single diagnostic result produced by a rule or probe."""

    rule_id: str = Field(description="Stable machine-readable ID, e.g. node/version-mismatch")
    state: FindingState
    summary: str
    evidence: tuple[Evidence, ...] = Field(min_length=1)
    detected: str | None = None
    required: str | None = None
    component: str | None = None
    remediation_hint: str | None = None
    references: tuple[str, ...] = ()
    probe_id: str | None = None


class ToolInstallation(_FrozenModel):
    """One installation of a developer tool found on the machine."""

    name: str
    version: str | None = None
    exe_path: str | None = None
    install_source: str | None = Field(
        default=None,
        description="Best-effort origin: brew, apt, choco, winget, scoop, "
        "nvm, pyenv, official-installer, store-alias, unknown",
    )
    is_active: bool = False
    precedence: int | None = Field(default=None, description="PATH precedence rank; lower wins")


class PathEntry(_FrozenModel):
    """A single PATH entry with liveness and origin metadata."""

    raw: str
    normalized: str
    exists: bool
    origin: str = Field(default="unknown", description="user | system | profile | inherited")
    index: int


class PathAnalysis(_FrozenModel):
    """Result of analyzing the PATH environment variable."""

    entries: tuple[PathEntry, ...]
    duplicates: tuple[str, ...] = ()
    dead_entries: tuple[str, ...] = ()
    shadowed_executables: tuple[tuple[str, str, str], ...] = Field(
        default=(),
        description="(name, winner_path, shadowed_path) tuples",
    )
    store_aliases: tuple[str, ...] = ()
    tool_manager_interference: tuple[str, ...] = ()
    profile_inconsistencies: tuple[str, ...] = ()


class ProjectRequirement(_FrozenModel):
    """A requirement *declared* by a project manifest/lockfile/policy."""

    ecosystem: str = Field(
        description=(
            "python | node | dotnet | go | rust | php | ruby | java | cpp | container | generic"
        )
    )
    name: str
    spec: str = Field(description="Version range as declared; never invented")
    kind: RequirementKind
    source_file: str
    optional: bool = False
    note: str | None = None


class PlatformInfo(_FrozenModel):
    os_name: str
    os_version: str
    arch: str
    kernel: str | None = None
    shell: str | None = None
    is_wsl: bool = False


class ContainerState(_FrozenModel):
    docker_cli_version: str | None = None
    docker_daemon_ok: bool = False
    podman_version: str | None = None
    compose_version: str | None = None
    kubectl_version: str | None = None
    errors: tuple[str, ...] = ()

    # --- what is actually behind `docker` -----------------------------------
    #
    # Docker Desktop, Colima, Rancher Desktop, OrbStack, Podman's machine and a
    # plain Linux daemon all answer the same CLI, and they differ on
    # file-sharing performance, on which host paths bind-mount at all, and on
    # how much memory the VM was given. "Docker works there but not here" is
    # usually one of those, not a daemon that is down.
    backend: str | None = None
    #: The *kind* of daemon endpoint (`unix`, `npipe`, `tcp`, `ssh`), never the
    #: endpoint. A Colima socket path contains the username, and a snapshot is
    #: something people share.
    endpoint_kind: str | None = None
    context_name: str | None = None
    server_version: str | None = None
    server_os: str | None = None
    server_arch: str | None = None
    storage_driver: str | None = None
    cgroup_version: str | None = None
    cgroup_driver: str | None = None
    rootless: bool | None = None
    engine_cpus: int | None = None
    engine_memory_bytes: int | None = None
    buildx_version: str | None = None
    #: Reclaimable bytes as the daemon itself computes them. A build that dies
    #: on "no space left on device" usually has tens of gigabytes of dangling
    #: layers behind it, and the daemon already knows.
    reclaimable_bytes: int | None = None
    dangling_images: int | None = None
    unused_volumes: int | None = None
    #: Other container engines installed, whichever one is currently answering.
    other_runtimes: tuple[str, ...] = ()


class WslState(_FrozenModel):
    available: bool = False
    version: str | None = None
    distros: tuple[str, ...] = ()
    default_distro: str | None = None
    interop_enabled: bool | None = None
    errors: tuple[str, ...] = ()


class GpuDeviceInfo(_FrozenModel):
    """One physical accelerator, enumerated rather than summarised.

    Present because a *mixed* pair is a real failure mode: a build targeting
    the compute capability of device 0 produces kernels the other card cannot
    execute, and the runtime error names neither the device nor the
    architecture.
    """

    index: int
    name: str
    memory_mib: int | None = None
    compute_capability: str | None = None


class GpuStack(_FrozenModel):
    nvidia_driver: str | None = None
    #: The highest CUDA *runtime* the installed driver can run, as nvidia-smi
    #: reports it. Not the installed toolkit; confusing the two is the single
    #: most common CUDA misdiagnosis.
    max_cuda_runtime: str | None = None
    devices: tuple[GpuDeviceInfo, ...] = ()
    cuda_toolkit: str | None = None
    rocm: str | None = None
    oneapi: str | None = None
    directml: bool = False
    vulkan: str | None = None
    metal: str | None = None
    wsl_gpu_passthrough: bool | None = None
    notes: tuple[str, ...] = ()


class VirtualenvInfo(_FrozenModel):
    kind: str = Field(description="venv | conda | pyenv | nvm | fnm | volta | mise | asdf")
    active: bool = False
    root_hint: str | None = Field(
        default=None, description="Redacted marker; never an absolute home path"
    )


class ReproducibilityPoint(_FrozenModel):
    criterion: str
    earned: int
    possible: int
    explanation: str


class ReproducibilityScore(_FrozenModel):
    total: int
    possible: int
    points: tuple[ReproducibilityPoint, ...]

    @property
    def percent(self) -> float:
        """Convenience for Python callers; deliberately NOT serialized.

        Making this a ``computed_field`` so the JSON carried it breaks every
        scan: ``_sanitize_report`` dumps the report, redacts it and re-validates
        it, and a computed field is output-only, so ``extra="forbid"`` rejects
        it on the way back in. That round-trip is what turns the privacy gate
        from a convention into a guarantee, so consumers of the JSON derive the
        percentage from ``total`` and ``possible`` instead.
        """
        return round(100.0 * self.total / self.possible, 1) if self.possible else 0.0


class Snapshot(_FrozenModel):
    """Privacy-sanitized environment manifest."""

    schema_version: str = "1.0"
    created_at: datetime = Field(default_factory=_utcnow)
    devrepro_version: str
    platform: PlatformInfo
    tools: tuple[ToolInstallation, ...] = ()
    path_analysis: PathAnalysis | None = None
    compilers: tuple[ToolInstallation, ...] = ()
    requirements_fingerprint: tuple[ProjectRequirement, ...] = ()
    containers: ContainerState | None = None
    wsl: WslState | None = None
    gpu: GpuStack | None = None
    virtualenvs: tuple[VirtualenvInfo, ...] = ()
    score: ReproducibilityScore | None = None
    privacy: dict[str, Any] = Field(
        default_factory=lambda: {"redacted": True, "secrets_blocked": True}
    )

    @property
    def snapshot_id(self) -> str:
        """Stable short id derived from content (no personal data)."""
        import hashlib
        import json

        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


class DiffEntry(_FrozenModel):
    component: str = Field(
        description="tool | path | compiler | container | wsl | gpu | requirement"
    )
    name: str
    classification: DiffClassification
    a_value: str | None = None
    b_value: str | None = None
    detail: str | None = None
    project_critical: bool = False


class EnvironmentDiff(_FrozenModel):
    a_snapshot_id: str
    b_snapshot_id: str
    created_at: datetime = Field(default_factory=_utcnow)
    entries: tuple[DiffEntry, ...] = ()

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for e in self.entries:
            out[e.classification.value] = out.get(e.classification.value, 0) + 1
        return out


class Remediation(_FrozenModel):
    """A safe repair plan step. Dry-run is always the default."""

    id: str
    title: str
    risk: RiskLevel
    preconditions: tuple[str, ...] = ()
    changes: tuple[str, ...] = Field(description="Exact intended changes; no side effects implied")
    rollback: str
    automatable: bool = False
    finding_ids: tuple[str, ...] = ()
    commands: tuple[tuple[str, ...], ...] = Field(
        default=(),
        description="Commands that WOULD run; executed only after explicit confirmation",
    )


class PolicySupportedOS(_FrozenModel):
    windows: bool = True
    linux: bool = True
    macos: bool = True


class PolicyContainers(_FrozenModel):
    require_devcontainer: bool = False
    require_compose: bool = False


class PolicyRequiredEnvNames(_FrozenModel):
    names: tuple[str, ...] = ()

    @field_validator("names")
    @classmethod
    def _names_look_like_names(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        for n in v:
            if not n.replace("_", "").replace("-", "").isalnum():
                raise ValueError(f"invalid env var NAME: {n!r}")
        return v


class Policy(_FrozenModel):
    """Parsed .devrepro.toml. Values are never secrets—only names/ranges."""

    supported_os: PolicySupportedOS = Field(default_factory=PolicySupportedOS)
    required_runtimes: dict[str, str] = Field(default_factory=dict)
    required_tools: dict[str, str] = Field(default_factory=dict)
    optional_tools: dict[str, str] = Field(default_factory=dict)
    known_bad_versions: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    containers: PolicyContainers = Field(default_factory=PolicyContainers)
    required_env_names: PolicyRequiredEnvNames = Field(default_factory=PolicyRequiredEnvNames)


class ScanReport(_FrozenModel):
    """Complete output of one scan, ready for rendering/export."""

    schema_version: str = "1.0"
    created_at: datetime = Field(default_factory=_utcnow)
    devrepro_version: str
    platform: PlatformInfo
    findings: tuple[Finding, ...] = ()
    tools: tuple[ToolInstallation, ...] = ()
    path_analysis: PathAnalysis | None = None
    requirements: tuple[ProjectRequirement, ...] = ()
    policy_applied: bool = False
    score: ReproducibilityScore | None = None
    probe_errors: tuple[str, ...] = ()
    # Collected by the container/wsl/gpu probes and declared in ``privacy``
    # below. These were computed by the scan and then dropped on the floor, so
    # a Snapshot could never carry them and ``diff_snapshots`` could never
    # report container drift -- "Docker works there but not here" was
    # unanswerable despite the probes gathering exactly that.
    containers: ContainerState | None = None
    wsl: WslState | None = None
    gpu: GpuStack | None = None
    privacy: dict[str, Any] = Field(
        default_factory=lambda: {
            "redacted": True,
            "secrets_blocked": True,
            "collected": [
                "os/arch/kernel",
                "cpu/ram/disk totals",
                "shell name",
                "PATH entries (normalized)",
                "tool names/versions/exe paths",
                "declared project requirements",
                "container/wsl/gpu state",
            ],
            "never_collected": [
                "usernames",
                "home directory absolute paths",
                "tokens/secrets",
                "file contents beyond manifests",
                "browser history",
                "emails",
            ],
        }
    )

    def active_versions(self) -> dict[str, str | None]:
        """Tool name to version, preferring the installation that has one.

        A dict comprehension over `is_active` tools looks equivalent and is
        not. A machine routinely reports the same tool more than once with only
        one readable version -- on Windows, `python` resolves to both a real
        interpreter and the App Execution Alias, a stub that exits without
        printing anything, and both are marked active. Last-one-wins then maps
        `python` to `None`, and `None` reads downstream as "not installed".

        That mistake shipped in three places at once, because the comprehension
        was copied. `devrepro onboard` told a machine running 3.14.7 to install
        Python.

        An installation whose version could not be read is not evidence that
        the tool is absent, so a readable version always wins over an
        unreadable one; the name is still present with a `None` value when
        nothing readable exists, because "installed, version unknown" is a real
        answer this project reports elsewhere.
        """
        versions: dict[str, str | None] = {}
        for tool in self.tools:
            if not tool.is_active:
                continue
            if versions.get(tool.name) is None:
                versions[tool.name] = tool.version
        return versions

    def worst_state(self) -> FindingState:
        order = [
            FindingState.BLOCKED,
            FindingState.ERROR,
            FindingState.WARN,
            FindingState.UNKNOWN,
            FindingState.INFO,
            FindingState.PASS,
        ]
        states = {f.state for f in self.findings}
        for s in order:
            if s in states:
                return s
        return FindingState.PASS
