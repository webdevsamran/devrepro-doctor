"""dotnet rule pack."""

from __future__ import annotations

from devrepro.core.models import Finding
from devrepro.rules.base import RuleContext
from devrepro.rules.packs.common import runtime_findings

__all__ = ["evaluate"]


def evaluate(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    reqs = [r for r in ctx.requirements if r.ecosystem == "dotnet"]
    if not reqs and not (ctx.policy and ctx.policy.required_runtimes.get("dotnet")):
        return findings
    findings.extend(runtime_findings(ctx, pack="dotnet", tool="dotnet"))
    return findings