"""Rule engine: compare machine state against project requirements and
policy. Every finding carries rule id, evidence, detected/required values,
affected component, safe remediation hint and references.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from devrepro.core.models import (
    ContainerState,
    Finding,
    FindingState,
    GpuStack,
    PathAnalysis,
    PlatformInfo,
    Policy,
    ProjectRequirement,
    ToolInstallation,
    WslState,
)
from devrepro.core.versioning import parse_spec, parse_version

__all__ = ["RuleContext", "RuleEngine", "check_version_requirement", "PACK_NAMES"]

PACK_NAMES: tuple[str, ...] = (
    "python", "node", "dotnet", "java", "cpp", "go", "rust",
    "containers", "wsl", "ai-gpu",
)


@dataclass(frozen=True)
class RuleContext:
    """Everything rules may look at (already sanitized where needed)."""

    platform_info: PlatformInfo
    tools: tuple[ToolInstallation, ...] = ()
    requirements: tuple[ProjectRequirement, ...] = ()
    policy: Policy | None = None
    path_analysis: PathAnalysis | None = None
    containers: ContainerState | None = None
    wsl: WslState | None = None
    gpu: GpuStack | None = None
    active_manager: str | None = None
    extra: dict[str, object] = field(default_factory=dict)

    def active_tool(self, name: str) -> ToolInstallation | None:
        candidates = [t for t in self.tools if t.name == name]
        if not candidates:
            return None
        return next((t for t in candidates if t.is_active), candidates[0])


def check_version_requirement(
    *,
    rule_prefix: str,
    tool_name: str,
    active: ToolInstallation | None,
    required_spec: str,
    known_bad: tuple[str, ...] = (),
    source: str = "policy",
    missing_state: FindingState = FindingState.BLOCKED,
    evidence_excerpt: str = "",
) -> list[Finding]:
    """Shared logic: missing / known-bad / out-of-range / satisfied."""
    from devrepro.core.models import Evidence

    findings: list[Finding] = []
    evidence = (Evidence(source="command", excerpt=evidence_excerpt or f"{tool_name} version check"),)

    if active is None or not active.version:
        findings.append(
            Finding(
                rule_id=f"{rule_prefix}/missing",
                state=missing_state,
                summary=f"Required tool '{tool_name}' ({required_spec}) not found on PATH.",
                evidence=evidence,
                required=required_spec,
                component=tool_name,
                remediation_hint=f"Install {tool_name} {required_spec} via your preferred "
                "package manager or version manager.",
                references=(f"declared in {source}",),
            )
        )
        return findings

    version = active.version
    try:
        v = parse_version(version)
        spec = parse_spec(required_spec)
        in_range = spec.satisfied_by(v)
    except ValueError:
        findings.append(
            Finding(
                rule_id=f"{rule_prefix}/version-unparseable",
                state=FindingState.UNKNOWN,
                summary=f"Could not parse {tool_name} version {version!r} against {required_spec!r}.",
                evidence=evidence,
                detected=version,
                required=required_spec,
                component=tool_name,
            )
        )
        return findings

    for bad_spec in known_bad:
        try:
            if parse_spec(bad_spec).satisfied_by(v):
                findings.append(
                    Finding(
                        rule_id=f"{rule_prefix}/known-bad-version",
                        state=FindingState.ERROR,
                        summary=f"{tool_name} {version} matches a known-bad range ({bad_spec}).",
                        evidence=evidence,
                        detected=version,
                        required=f"not {bad_spec}",
                        component=tool_name,
                        remediation_hint=f"Upgrade {tool_name} outside the known-bad range.",
                        references=(f"policy known_bad_versions[{tool_name}]",),
                    )
                )
                break
        except ValueError:
            continue

    if in_range:
        findings.append(
            Finding(
                rule_id=f"{rule_prefix}/version-ok",
                state=FindingState.PASS,
                summary=f"{tool_name} {version} satisfies {required_spec}.",
                evidence=evidence,
                detected=version,
                required=required_spec,
                component=tool_name,
            )
        )
    else:
        findings.append(
            Finding(
                rule_id=f"{rule_prefix}/version-mismatch",
                state=FindingState.ERROR,
                summary=f"{tool_name} {version} does not satisfy required range {required_spec}.",
                evidence=evidence,
                detected=version,
                required=required_spec,
                component=tool_name,
                remediation_hint=f"Install a {tool_name} version within {required_spec} "
                "(use a version manager to avoid disturbing other projects).",
                references=(f"declared in {source}",),
            )
        )
    return findings


PackFunc = Callable[[RuleContext], list[Finding]]


class RuleEngine:
    """Runs rule packs against a context. Packs are isolated: one failing
    pack yields an UNKNOWN finding, never a crashed evaluation."""

    def __init__(self) -> None:
        self._packs: dict[str, PackFunc] = {}

    def register(self, name: str, func: PackFunc) -> None:
        self._packs[name] = func

    def pack_names(self) -> list[str]:
        return sorted(self._packs)

    def evaluate(self, ctx: RuleContext, packs: list[str] | None = None) -> list[Finding]:
        selected = packs or sorted(self._packs)
        findings: list[Finding] = []
        for name in selected:
            func = self._packs.get(name)
            if func is None:
                continue
            try:
                findings.extend(func(ctx))
            except Exception as exc:  # noqa: BLE001 - isolation boundary
                from devrepro.core.models import Evidence

                findings.append(
                    Finding(
                        rule_id=f"rulepack/{name}/failed",
                        state=FindingState.UNKNOWN,
                        summary=f"Rule pack '{name}' failed internally: {type(exc).__name__}: {exc}",
                        evidence=(Evidence(source="system", excerpt=str(exc)[:500]),),
                    )
                )
        return findings


def load_builtin_packs(engine: RuleEngine) -> None:
    from devrepro.rules.packs.ai_gpu import evaluate as ai_gpu
    from devrepro.rules.packs.containers import evaluate as containers
    from devrepro.rules.packs.cpp import evaluate as cpp
    from devrepro.rules.packs.dotnet import evaluate as dotnet
    from devrepro.rules.packs.go import evaluate as go
    from devrepro.rules.packs.java import evaluate as java
    from devrepro.rules.packs.node import evaluate as node
    from devrepro.rules.packs.python import evaluate as python
    from devrepro.rules.packs.rust import evaluate as rust
    from devrepro.rules.packs.wsl import evaluate as wsl

    engine.register("python", python)
    engine.register("node", node)
    engine.register("dotnet", dotnet)
    engine.register("java", java)
    engine.register("cpp", cpp)
    engine.register("go", go)
    engine.register("rust", rust)
    engine.register("containers", containers)
    engine.register("wsl", wsl)
    engine.register("ai-gpu", ai_gpu)