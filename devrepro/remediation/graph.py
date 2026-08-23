"""Remediation dependency graphs, dry-run transactions and confirmation gates.

A remediation plan is expressed as a DAG: steps declare prerequisites so
ordered safe changes are explicit. A ``DryRunTransaction`` simulates a plan
and enforces confirmation boundaries: MEDIUM/HIGH risk steps require an
explicit ``confirmed=True`` token per step even when the overall plan was
approved. Rollback metadata and post-fix verification checks ride along.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from devrepro.core.models import RiskLevel

__all__ = ["DryRunTransaction", "PlanCycleError", "RemediationStep", "build_execution_order"]


@dataclass(frozen=True)
class RemediationStep:
    id: str
    title: str
    risk: RiskLevel
    commands: tuple[str, ...] = ()
    prerequisites: tuple[str, ...] = ()  # ids of steps that must run first
    rollback: str | None = None
    post_checks: tuple[str, ...] = ()  # verification commands/descriptions


class PlanCycleError(ValueError):
    """The remediation graph contains a prerequisite cycle."""


def build_execution_order(steps: tuple[RemediationStep, ...]) -> tuple[RemediationStep, ...]:
    """Topologically order steps by prerequisites (stable, deterministic).

    Raises PlanCycleError when prerequisites form a cycle or reference
    unknown steps.
    """
    by_id = {s.id: s for s in steps}
    for s in steps:
        for p in s.prerequisites:
            if p not in by_id:
                msg = f"step {s.id!r} depends on unknown step {p!r}"
                raise PlanCycleError(msg)
    order: list[RemediationStep] = []
    done: set[str] = set()
    visiting: set[str] = set()

    def visit(step: RemediationStep) -> None:
        if step.id in done:
            return
        if step.id in visiting:
            msg = f"prerequisite cycle involving {step.id!r}"
            raise PlanCycleError(msg)
        visiting.add(step.id)
        for p in step.prerequisites:
            visit(by_id[p])
        visiting.discard(step.id)
        done.add(step.id)
        order.append(step)

    for s in sorted(steps, key=lambda x: x.id):
        visit(s)
    return tuple(order)


@dataclass
class DryRunTransaction:
    """Simulates plan execution with explicit confirmation boundaries."""

    steps: tuple[RemediationStep, ...]
    executed: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (id, reason)
    confirmed_ids: frozenset[str] = frozenset()

    def run(self) -> dict[str, object]:
        """Execute the dry-run. Nothing external happens; risk gates apply."""
        ordered = build_execution_order(self.steps)
        completed: set[str] = set()
        for step in ordered:
            unmet = [p for p in step.prerequisites if p not in completed]
            if unmet:
                self.skipped.append((step.id, f"prerequisites not satisfied: {unmet}"))
                continue
            needs_confirmation = step.risk in (RiskLevel.MEDIUM, RiskLevel.HIGH)
            if needs_confirmation and step.id not in self.confirmed_ids:
                self.skipped.append(
                    (step.id, f"{step.risk.value}-risk action requires explicit confirmation")
                )
                continue
            self.executed.append(step.id)
            completed.add(step.id)
        return {
            "executed": list(self.executed),
            "skipped": [list(s) for s in self.skipped],
            "total": len(ordered),
            "note": "dry-run only; no commands were executed",
        }
