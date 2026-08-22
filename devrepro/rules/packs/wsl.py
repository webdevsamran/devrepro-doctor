"""wsl rule pack."""

from __future__ import annotations

from devrepro.core.models import Evidence, Finding, FindingState
from devrepro.rules.base import RuleContext

__all__ = ["evaluate"]


def evaluate(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    wsl = ctx.wsl
    if wsl is None or not wsl.available:
        return findings  # WSL absent is INFO-level at most; probe already reported

    if wsl.default_distro is None and wsl.distros:
        findings.append(
            Finding(
                rule_id="wsl/no-default-distro",
                state=FindingState.WARN,
                summary="WSL distros exist but no default is set.",
                evidence=(Evidence(source="command", command=("wsl", "--status"),
                                   excerpt="default distro unset"),),
                component="wsl",
                remediation_hint="`wsl --set-default <distro>` (SAFE).",
            )
        )
    if wsl.interop_enabled is False:
        findings.append(
            Finding(
                rule_id="wsl/interop-disabled",
                state=FindingState.WARN,
                summary="WSL interop appears disabled; Windows/Linux tool mixing will fail.",
                evidence=(Evidence(source="command", command=("wsl", "-e", "test", "-e", "/init"),
                                   excerpt="interop check failed"),),
                component="wsl",
                remediation_hint="Enable interop in /etc/wsl.conf ([interop] enabled=true), "
                "then `wsl --shutdown`. LOW risk.",
            )
        )
    return findings