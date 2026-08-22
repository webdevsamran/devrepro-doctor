"""node rule pack."""

from __future__ import annotations

from devrepro.core.models import Finding
from devrepro.rules.base import RuleContext
from devrepro.rules.packs.common import runtime_findings, tool_findings

__all__ = ["evaluate"]


def evaluate(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = runtime_findings(ctx, pack="node", tool="node")
    # npm is only checked when the project declares it
    reqs = [r for r in ctx.requirements if r.ecosystem == "node" and r.name == "npm"]
    if reqs:
        findings.extend(runtime_findings(ctx, pack="node", tool="npm"))
    findings.extend(tool_findings(ctx, pack="node", tool="git"))
    return findings
