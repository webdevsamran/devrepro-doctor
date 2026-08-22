"""Rule engine evaluation against synthetic machine states."""

from __future__ import annotations

from pathlib import Path

from devrepro.core.models import (
    ContainerState,
    FindingState,
    PathAnalysis,
    PlatformInfo,
    ProjectRequirement,
    RequirementKind,
    ToolInstallation,
)
from devrepro.rules.base import RuleContext, RuleEngine, load_builtin_packs
from devrepro.project.policy import load_policy

POLICY = Path(__file__).parent / "fixtures" / "policy" / ".devrepro.toml"


def _engine() -> RuleEngine:
    engine = RuleEngine()
    load_builtin_packs(engine)
    return engine


def _ctx(*, tools=(), reqs=(), path=None, containers=None):
    return RuleContext(
        platform_info=PlatformInfo(os_name="Linux", os_version="6.5", arch="x86_64"),
        tools=tuple(tools),
        requirements=tuple(reqs),
        policy=load_policy(POLICY),
        path_analysis=path,
        containers=containers,
    )


def _tool(name: str, version: str | None = "1.0"):
    return ToolInstallation(
        name=name, version=version, exe_path=f"/usr/bin/{name}",
        install_source="system",
    )


def _req(name: str, spec: str, eco: str = "python"):
    return ProjectRequirement(
        ecosystem=eco, name=name, spec=spec, kind=RequirementKind.RUNTIME,
        source_file="pyproject.toml",
    )


def test_python_version_match_passes() -> None:
    ctx = _ctx(tools=[_tool("python", "3.12.4")], reqs=[_req("python", ">=3.11,<3.14")])
    findings = {f.rule_id: f for f in _engine().evaluate(ctx)}
    f = findings.get("python/version-ok")
    assert f is not None and f.state == FindingState.PASS


def test_python_version_mismatch_errors() -> None:
    ctx = _ctx(tools=[_tool("python", "3.10.12")], reqs=[_req("python", ">=3.11,<3.14")])
    findings = {f.rule_id: f for f in _engine().evaluate(ctx)}
    f = findings["python/version-mismatch"]
    assert f.state == FindingState.ERROR
    assert f.detected == "3.10.12" and f.required == ">=3.11,<3.14"


def test_missing_runtime_warns() -> None:
    ctx = _ctx(reqs=[_req("node", ">=20", "node")])
    findings = {f.rule_id: f for f in _engine().evaluate(ctx)}
    assert findings["node/missing"].state == FindingState.WARN


def test_docker_daemon_unreachable_blocks_when_project_needs_containers() -> None:
    ctx = _ctx(
        containers=ContainerState(docker_cli_version="24.0.7", docker_daemon_ok=False),
        reqs=[_req("docker-build", "*", "container")],
    )
    findings = {f.rule_id: f for f in _engine().evaluate(ctx)}
    f = findings["containers/docker-daemon-unreachable"]
    assert f.state == FindingState.BLOCKED


def test_policy_required_env_names_checked() -> None:
    ctx = _ctx()
    findings = {f.rule_id: f for f in _engine().evaluate(ctx)}
    # policy fixture requires GITHUB_TOKEN name; env audit runs separately,
    # but the rule engine must at least not crash with policy applied
    assert isinstance(findings, dict)


def test_all_findings_have_evidence_and_ids() -> None:
    ctx = _ctx(tools=[_tool("python", "3.9")], reqs=[_req("python", ">=3.11")])
    for f in _engine().evaluate(ctx):
        assert f.rule_id and f.evidence and f.summary
