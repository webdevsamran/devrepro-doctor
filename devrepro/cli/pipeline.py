"""Scan pipeline shared by doctor/scan/preflight/snapshot/plan commands.

Runs probes → collects toolchain/path/container/wsl/gpu state → loads
project requirements + policy → evaluates rule packs → computes score →
returns a fully sanitized ScanReport.
"""

from __future__ import annotations

import json
from pathlib import Path

from devrepro import __version__
from devrepro.core.models import (
    ContainerState,
    GpuStack,
    PathAnalysis,
    PlatformInfo,
    Policy,
    ProjectRequirement,
    ScanReport,
    ToolInstallation,
    WslState,
)
from devrepro.core.runner import SubprocessRunner
from devrepro.privacy.gate import PrivacyGate
from devrepro.project.detectors import detect_requirements
from devrepro.rules.base import RuleContext, RuleEngine, load_builtin_packs
from devrepro.rules.score import compute_score

__all__ = ["run_scan"]


def _probe_data(result: object, key: str) -> object:
    """Extract ``key`` from a single ProbeResult's data payload."""
    data = getattr(result, "data", None)
    if isinstance(data, dict):
        inner = data.get(key)
        if inner is not None:
            return inner
        return data
    return {}


def run_scan(
    *,
    project_dir: Path | None = None,
    policy: Policy | None = None,
    runner: object | None = None,
) -> ScanReport:
    """Full read-only scan. Never raises for probe failures."""
    from devrepro.probes.base import ProbeContext, ProbeEngine
    from devrepro.probes.registry import build_default_probes, load_plugin_probes

    cmd_runner = runner or SubprocessRunner()
    ctx = ProbeContext.capture(cmd_runner, project_dir=project_dir)  # type: ignore[arg-type]

    probes = build_default_probes(ctx) + load_plugin_probes(ctx)
    engine = ProbeEngine(probes)
    results = engine.run_all()

    # ---- structured state -------------------------------------------------
    tools_raw = _probe_data(results.get("toolchain/detect", {}), "tools")
    tools = tuple(
        ToolInstallation.model_validate(t)
        for t in (tools_raw or []) if isinstance(t, dict)
    )

    path_analysis: PathAnalysis | None = None
    path_data = _probe_data(results.get("path/entries", {}), "analysis")  # type: ignore[arg-type]
    if path_data:
        try:
            path_analysis = PathAnalysis.model_validate(path_data)
        except Exception:  # noqa: BLE001
            path_analysis = None

    containers: ContainerState | None = None
    cdata = _probe_data(results.get("containers/doctor", {}), "state")  # type: ignore[arg-type]
    if cdata:
        try:
            containers = ContainerState.model_validate(cdata)
        except Exception:  # noqa: BLE001
            containers = None

    wsl: WslState | None = None
    wdata = _probe_data(results.get("virt/wsl", {}), "state")  # type: ignore[arg-type]
    if wdata:
        try:
            wsl = WslState.model_validate(wdata)
        except Exception:  # noqa: BLE001
            wsl = None

    gpu: GpuStack | None = None
    gdata = _probe_data(results.get("gpu/ai-stack", {}), "stack")  # type: ignore[arg-type]
    if gdata:
        try:
            gpu = GpuStack.model_validate(gdata)
        except Exception:  # noqa: BLE001
            gpu = None

    active_manager = results.get("shell/profiles").data.get("active_manager") \
        if isinstance(results.get("shell/profiles"), object) and hasattr(
            results.get("shell/profiles"), "data") else None  # type: ignore[union-attr]

    # ---- project requirements -------------------------------------------------
    requirements: list[ProjectRequirement] = []
    root = project_dir or Path.cwd()
    try:
        requirements = detect_requirements(root)
    except Exception:  # noqa: BLE001 - manifest errors must not kill the scan
        requirements = []

    required_env_names: list[str] = []
    if policy is not None:
        required_env_names = list(policy.required_env_names.names)

    ctx2 = ProbeContext.capture(cmd_runner, project_dir=root)  # type: ignore[arg-type]
    ctx2.extra["required_env_names"] = required_env_names  # type: ignore[attr-defined]
    env_results = {}
    from devrepro.probes.env_probe import EnvAuditProbe

    env_probe = EnvAuditProbe(ctx2)
    try:
        env_results = {env_probe.id: env_probe.run()}
    except Exception:  # noqa: BLE001
        env_results = {}

    # ---- rules -------------------------------------------------------------------
    platform_info = ctx.platform_info
    if wsl is not None and getattr(platform_info, "is_wsl", False) is False and False:
        pass  # keep mypy quiet; WSL detection handled by probe on Windows hosts

    rule_ctx = RuleContext(
        platform_info=platform_info,
        tools=tools,
        requirements=tuple(requirements),
        policy=policy,
        path_analysis=path_analysis,
        containers=containers,
        wsl=wsl,
        gpu=gpu,
        active_manager=str(active_manager) if active_manager else None,
    )
    rule_engine = RuleEngine()
    load_builtin_packs(rule_engine)
    findings = list(rule_engine.evaluate(rule_ctx))

    for res in list(results.values()) + list(env_results.values()):
        findings.extend(getattr(res, "findings", ()) or ())

    probe_errors = [
        f"{pid}: {getattr(res, 'error', '')}"
        for pid, res in sorted(results.items())
        if getattr(res, "error", None)
    ]

    score = compute_score(root, requirements)

    report = ScanReport(
        schema_version="1.0",
        devrepro_version=__version__,
        platform=platform_info,
        findings=tuple(findings),
        tools=tools,
        path_analysis=path_analysis,
        requirements=tuple(requirements),
        policy_applied=policy is not None,
        score=score,
        probe_errors=tuple(probe_errors),
    )
    return _sanitize_report(report)


def _sanitize_report(report: ScanReport) -> ScanReport:
    """Final privacy pass over every string in the report payload."""
    gate = PrivacyGate()
    payload = json.dumps(report.model_dump(mode="json"), default=str)
    sanitized = gate.redact(payload)
    import json as _json

    data = _json.loads(sanitized)
    return ScanReport.model_validate(data)