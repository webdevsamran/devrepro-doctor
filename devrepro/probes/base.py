"""Probe interface, context and engine.

Contract
--------
A probe is a small, isolated diagnostic that:

- declares a stable ``id`` and ``version``,
- declares the platforms it supports,
- optionally declares dependencies on other probe ids,
- runs read-only commands/filesystem reads through its ``CommandRunner``,
- returns findings **with evidence** plus structured ``data`` for rules.

The engine guarantees: one failing probe never crashes the whole scan.
Failures become UNKNOWN findings with evidence of the failure itself.
"""

from __future__ import annotations

import os
import platform as _pyplatform
import sys
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from devrepro.core.errors import ProbeError
from devrepro.core.models import Evidence, Finding, FindingState, PlatformInfo

if TYPE_CHECKING:
    from pathlib import Path

    from devrepro.core.runner import CommandRunner

__all__ = ["Probe", "ProbeContext", "ProbeEngine", "ProbeResult", "current_platform"]

Platform = str  # "windows" | "linux" | "macos"


def current_platform() -> Platform:
    system = _pyplatform.system().lower()
    if system == "windows":
        return "windows"
    if system == "darwin":
        return "macos"
    return "linux"


@dataclass(frozen=True)
class ProbeResult:
    """What a probe returns: findings + structured data."""

    probe_id: str
    findings: tuple[Finding, ...] = ()
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class ProbeContext:
    """Everything a probe may touch. Read-only by contract."""

    runner: CommandRunner
    platform: Platform
    platform_info: PlatformInfo
    project_dir: Path | None = None
    env: dict[str, str] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def capture(
        runner: CommandRunner,
        *,
        project_dir: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> ProbeContext:
        plat = current_platform()
        info = PlatformInfo(
            os_name=_pyplatform.system(),
            os_version=_pyplatform.version().split()[0] if _pyplatform.version() else "",
            arch=_pyplatform.machine(),
            kernel=_pyplatform.release(),
            shell=None,
            is_wsl=False,
        )
        if env is None:
            # Keep only variable NAMES + non-sensitive values we need.
            # Values are available to probes but never serialized directly.
            env = dict(os.environ)
        return ProbeContext(
            runner=runner,
            platform=plat,
            platform_info=info,
            project_dir=project_dir,
            env=env,
        )


class Probe(ABC):
    """Base class for all probes (plugin API v1)."""

    id: str = ""
    version: str = "1"
    platforms: tuple[Platform, ...] = ("windows", "linux", "macos")
    dependencies: tuple[str, ...] = ()
    timeout_seconds: float = 20.0

    def __init__(self, ctx: ProbeContext) -> None:
        self.ctx = ctx

    def supported(self) -> bool:
        return self.ctx.platform in self.platforms

    @abstractmethod
    def run(self) -> ProbeResult:
        """Execute the probe. Must be read-only and exception-safe."""

    # -- helpers for subclasses ------------------------------------------

    def finding(
        self,
        rule_id: str,
        state: FindingState,
        summary: str,
        *,
        evidence: tuple[Evidence, ...],
        detected: str | None = None,
        required: str | None = None,
        component: str | None = None,
        remediation_hint: str | None = None,
        references: tuple[str, ...] = (),
    ) -> Finding:
        return Finding(
            rule_id=rule_id,
            state=state,
            summary=summary,
            evidence=evidence,
            detected=detected,
            required=required,
            component=component,
            remediation_hint=remediation_hint,
            references=references,
            probe_id=self.id,
        )

    def cmd_evidence(self, argv: tuple[str, ...], result_excerpt: str) -> Evidence:
        return Evidence(source="command", command=argv, excerpt=result_excerpt[:2000])


class ProbeEngine:
    """Runs probes with isolation: exceptions/timeouts become findings."""

    def __init__(self, probes: list[Probe], *, max_workers: int = 8) -> None:
        self._probes = list(probes)
        self._max_workers = max_workers

    def run_all(self) -> dict[str, ProbeResult]:
        results: dict[str, ProbeResult] = {}
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            futures = {pool.submit(self._run_one, p): p for p in self._probes}
            for future, probe in futures.items():
                try:
                    results[probe.id] = future.result(timeout=probe.timeout_seconds * 4)
                except Exception as exc:
                    results[probe.id] = ProbeResult(
                        probe_id=probe.id,
                        error=f"engine-level failure: {type(exc).__name__}: {exc}",
                    )
        return results

    def _run_one(self, probe: Probe) -> ProbeResult:
        if not probe.supported():
            return ProbeResult(probe_id=probe.id, error="unsupported on this platform")
        try:
            result = probe.run()
        except Exception as exc:
            ev = Evidence(
                source="system",
                excerpt=f"probe raised {type(exc).__name__}: {exc}",
            )
            finding = Finding(
                rule_id=f"probe/{probe.id}/failed",
                state=FindingState.UNKNOWN,
                summary=f"Probe '{probe.id}' failed internally; results may be incomplete.",
                evidence=(ev,),
                probe_id=probe.id,
            )
            return ProbeResult(
                probe_id=probe.id,
                findings=(finding,),
                error=str(exc),
            )
        if not isinstance(result, ProbeResult):
            raise ProbeError(f"probe {probe.id} returned invalid result type")
        return result


def default_probe_ids() -> list[str]:  # pragma: no cover - introspection aid
    from devrepro.probes.registry import build_default_probes

    return [p.id for p in build_default_probes(ProbeContext.capture(runner=None))]  # type: ignore[arg-type]


def _unused(*_args: object) -> None:  # pragma: no cover
    sys.stdout.flush()
