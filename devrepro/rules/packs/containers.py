"""containers rule pack."""

from __future__ import annotations

from devrepro.core.models import Evidence, Finding, FindingState
from devrepro.rules.base import RuleContext
from devrepro.rules.packs.common import tool_findings

__all__ = ["evaluate"]


def evaluate(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    container_reqs = [r for r in ctx.requirements if r.ecosystem == "container"]

    needs_docker = bool(container_reqs) or (
        ctx.policy is not None and (
            ctx.policy.containers.require_devcontainer
            or ctx.policy.containers.require_compose
            or "docker" in ctx.policy.required_tools
        )
    )
    if not needs_docker:
        return findings

    c = ctx.containers
    if c is None:
        findings.append(
            Finding(
                rule_id="containers/state-unknown",
                state=FindingState.UNKNOWN,
                summary="Container requirements exist but container probe data is unavailable.",
                evidence=(Evidence(source="system", excerpt="no container probe result"),),
                component="docker",
            )
        )
        return findings

    if not c.docker_cli_version and not c.podman_version:
        findings.append(
            Finding(
                rule_id="containers/docker-missing",
                state=FindingState.BLOCKED,
                summary="Project requires containers but neither Docker nor Podman CLI found.",
                evidence=(Evidence(source="command", excerpt="docker --version / podman --version"),),
                component="docker",
                remediation_hint="Install Docker Desktop (or Podman) — MEDIUM risk; "
                "DevRepro will not install it automatically.",
            )
        )
    elif not c.docker_daemon_ok and c.docker_cli_version:
        findings.append(
            Finding(
                rule_id="containers/docker-daemon-unreachable",
                state=FindingState.BLOCKED,
                summary=f"Docker CLI {c.docker_cli_version} present but daemon unreachable. "
                + "; ".join(c.errors),
                evidence=(Evidence(source="command", command=("docker", "info"),
                                   excerpt="daemon did not respond"),),
                component="docker",
                remediation_hint="Start Docker Desktop / systemctl start docker, then re-scan.",
            )
        )

    if ctx.policy is not None and ctx.policy.containers.require_devcontainer:
        has_devcontainer = any(r.name == "devcontainer" for r in container_reqs)
        if not has_devcontainer:
            findings.append(
                Finding(
                    rule_id="containers/devcontainer-required",
                    state=FindingState.WARN,
                    summary="Policy requires a devcontainer definition but none was found.",
                    evidence=(Evidence(source="file", path=".devcontainer/devcontainer.json",
                                       excerpt="not found"),),
                    component="devcontainer",
                    remediation_hint="Add .devcontainer/devcontainer.json to the repository.",
                )
            )
    findings.extend(tool_findings(ctx, pack="containers", tool="docker"))
    return findings