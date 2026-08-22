"""Shared helpers for rule packs."""

from __future__ import annotations

from devrepro.core.models import (
    Evidence,
    Finding,
    FindingState,
    ProjectRequirement,
    ToolInstallation,
)
from devrepro.rules.base import RuleContext, check_version_requirement

__all__ = ["runtime_findings", "tool_findings", "requirement_for", "active_version_of"]


def requirement_for(ctx: RuleContext, ecosystem: str, name: str) -> ProjectRequirement | None:
    for r in ctx.requirements:
        if r.ecosystem == ecosystem and r.name == name:
            return r
    return None


def active_version_of(ctx: RuleContext, tool: str) -> ToolInstallation | None:
    return ctx.active_tool(tool)


def runtime_findings(
    ctx: RuleContext,
    *,
    pack: str,
    tool: str,
    policy_key: str | None = None,
    missing_state: FindingState = FindingState.BLOCKED,
) -> list[Finding]:
    """Evaluate a runtime against project requirements + policy."""
    req = requirement_for(ctx, pack, tool)
    policy = ctx.policy
    spec: str | None = None
    source = ""
    if req is not None:
        spec = req.spec
        source = req.source_file
    if policy is not None:
        policy_spec = policy.required_runtimes.get(policy_key or tool)
        if policy_spec:
            spec = policy_spec if spec in (None, "*") else spec
            source = source or ".devrepro.toml"
    if spec is None:
        return []
    active = active_version_of(ctx, tool)
    known_bad: tuple[str, ...] = ()
    if policy is not None:
        known_bad = policy.known_bad_versions.get(policy_key or tool, ())
    return check_version_requirement(
        rule_prefix=pack,
        tool_name=tool,
        active=active,
        required_spec=spec,
        known_bad=known_bad,
        source=source,
        missing_state=missing_state,
        evidence_excerpt=f"{tool} --version resolved via PATH",
    )


def tool_findings(
    ctx: RuleContext,
    *,
    pack: str,
    tool: str,
    missing_state: FindingState = FindingState.WARN,
) -> list[Finding]:
    """Required tools from policy (e.g. git, docker)."""
    policy = ctx.policy
    if policy is None:
        return []
    spec = policy.required_tools.get(tool)
    if spec is None:
        return []
    active = active_version_of(ctx, tool)
    known_bad = policy.known_bad_versions.get(tool, ())
    return check_version_requirement(
        rule_prefix=pack,
        tool_name=tool,
        active=active,
        required_spec=spec,
        known_bad=known_bad,
        source=".devrepro.toml [required_tools]",
        missing_state=missing_state,
        evidence_excerpt=f"{tool} --version resolved via PATH",
    )