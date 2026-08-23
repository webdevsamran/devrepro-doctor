"""dotnet rule pack."""

from __future__ import annotations

from typing import TYPE_CHECKING

from devrepro.rules.packs.common import runtime_findings

if TYPE_CHECKING:
    from devrepro.core.models import Finding
    from devrepro.rules.base import RuleContext

__all__ = ["evaluate"]


def evaluate(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    reqs = [r for r in ctx.requirements if r.ecosystem == "dotnet"]
    if not reqs and not (ctx.policy and ctx.policy.required_runtimes.get("dotnet")):
        return findings
    findings.extend(runtime_findings(ctx, pack="dotnet", tool="dotnet"))
    return findings
