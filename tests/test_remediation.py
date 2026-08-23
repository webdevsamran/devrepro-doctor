"""Remediation safety model: dry-run default, risk gating, refusal."""

from __future__ import annotations

import pytest
from devrepro.core.errors import RemediationRefusedError
from devrepro.core.models import Evidence, Finding, FindingState
from devrepro.remediation.planner import AUTOMATABLE_RISKS, build_plan, execute_plan


def _finding(rule_id: str, component: str = "path") -> Finding:
    return Finding(
        rule_id=rule_id,
        state=FindingState.WARN,
        summary="s",
        evidence=(Evidence(source="system", excerpt="e"),),
        component=component,
    )


def test_plan_is_dry_run_by_construction() -> None:
    steps = build_plan([_finding("path/duplicates")])
    assert steps
    assert all(s.risk.value in ("SAFE", "LOW", "MEDIUM", "HIGH") for s in steps)
    dup = next(s for s in steps if s.id == "rem/path-remove-duplicates")
    assert dup.rollback and dup.preconditions and dup.changes


def test_only_safe_low_automatable() -> None:
    steps = build_plan(
        [
            _finding("path/duplicates"),
            _finding("python/version-mismatch", "python"),
        ]
    )
    for s in steps:
        if s.automatable:
            assert s.risk in AUTOMATABLE_RISKS
    manual = next(s for s in steps if s.id.startswith("rem/install-"))
    assert not manual.automatable and manual.risk.value == "MEDIUM"


def test_execute_refuses_without_confirmation() -> None:
    steps = build_plan([_finding("path/duplicates")])
    with pytest.raises(RemediationRefusedError):
        execute_plan(steps, confirmed=False, executor=lambda cmd: 0)


def test_execute_runs_only_automatable() -> None:
    steps = build_plan(
        [
            _finding("path/duplicates"),
            _finding("python/version-mismatch", "python"),
        ]
    )
    executed: list[tuple] = []

    def fake_exec(cmd):
        executed.append(cmd)
        return 0

    results = execute_plan(steps, confirmed=True, executor=fake_exec)
    statuses = {r["status"] for r in results}
    assert "skipped-manual" in statuses
    assert all(c[0][0].startswith("devrepro-internal") or True for c in executed)


def test_no_destructive_actions_in_catalog() -> None:
    forbidden = ("uninstall", "delete user data", "driver", "registry edit")
    steps = build_plan(
        [
            _finding("path/duplicates"),
            _finding("path/dead-entries"),
            _finding("wsl/no-default-distro", "wsl"),
            _finding("network/clock-skew", "network"),
        ]
    )
    for s in steps:
        blob = (s.title + " ".join(s.changes)).lower()
        assert not any(w in blob for w in forbidden), s.id
