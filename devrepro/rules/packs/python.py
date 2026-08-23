"""python rule pack."""

from __future__ import annotations

from typing import TYPE_CHECKING

from devrepro.core.models import Evidence, Finding, FindingState
from devrepro.rules.packs.common import active_version_of, runtime_findings

if TYPE_CHECKING:
    from devrepro.rules.base import RuleContext

__all__ = ["evaluate"]


def evaluate(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = runtime_findings(ctx, pack="python", tool="python")

    installs = [t for t in ctx.tools if t.name == "python"]
    versions = {t.version for t in installs if t.version}
    if len(versions) > 1:
        active = active_version_of(ctx, "python")
        findings.append(
            Finding(
                rule_id="python/multiple-versions",
                state=FindingState.WARN,
                summary=f"Multiple Python versions installed: {', '.join(sorted(versions))}. "
                f"Active: {active.version if active else '?'} "
                f"({active.install_source if active else '?'}).",
                evidence=(Evidence(source="command", excerpt="which -a python / where python"),),
                detected=", ".join(sorted(versions)),
                component="python",
                remediation_hint="Use pyenv/uv to pin per-project versions; keep one "
                "system-wide install. See `devrepro which --all python`.",
            )
        )
    return findings
