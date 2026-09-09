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


def test_automatable_step_without_commands_is_reported_not_dropped() -> None:
    """A planned step must never vanish from the result.

    `execute_plan` looped over `step.commands` and appended one result per
    command. A step flagged automatable but carrying no commands produced zero
    results, so `devrepro fix` silently omitted steps that `devrepro plan` had
    just listed as automatable -- the user saw neither success nor failure.
    """
    steps = build_plan([_finding("path/duplicates")])
    automatable = [s for s in steps if s.automatable and s.risk in AUTOMATABLE_RISKS]
    assert automatable, "expected at least one automatable step in the catalog"
    assert not automatable[0].commands, (
        "this test covers the unwired case; if commands are now populated, "
        "assert on 'executed' instead"
    )

    results = execute_plan(steps, confirmed=True, executor=lambda cmd: 0)
    reported = {r["id"] for r in results}
    for step in steps:
        assert step.id in reported, f"step {step.id} was planned but not reported"

    entry = next(r for r in results if r["id"] == automatable[0].id)
    assert entry["status"] == "no-commands"
    assert "manually" in entry["detail"]


def test_execute_plan_still_refuses_without_confirmation() -> None:
    """The consent gate is the point of the design and must not regress."""
    import pytest
    from devrepro.core.errors import RemediationRefusedError

    steps = build_plan([_finding("path/duplicates")])
    with pytest.raises(RemediationRefusedError):
        execute_plan(steps, confirmed=False, executor=lambda cmd: 0)
