"""Two fleet questions, and the line between process metrics and surveillance.

**How long does it take a new machine to become usable?** Every engineering
organisation quotes an onboarding time and almost none measures one. The number
that matters is the gap between a machine enrolling and the first scan that
comes back READY -- which this server already has the data for, because it
stores enrolment times and snapshots.

**What would this policy change break?** A paved road is rolled out by editing
a policy and finding out. The fleet's stored snapshots answer it in advance:
apply the proposed policy to the last snapshot from every machine and count who
newly fails. Cheap, exact, and the difference between a Tuesday and a week of
people being blocked.

---

The first of those is the one that can go wrong, and the way it goes wrong is
not technical.

A per-person onboarding time is a performance metric. It will be read as one
whatever the dashboard calls it, it will be wrong -- somebody spent three days
of their first week in orientation, somebody else inherited a working laptop --
and once it exists somebody will ask for it broken down by name. That is
surveillance built out of diagnostic data, and the fact that it is technically
easy is exactly why the decision has to be made here rather than left to
whoever writes the query.

So: **aggregates only, with a floor.** Below a handful of machines a
distribution identifies individuals, so nothing is reported. No machine key, no
user, no label appears in the output -- only counts and percentiles. A caller
who wants per-machine timing has to go to the database and write it themselves,
which is a deliberate speed bump rather than a lock, and the honest place to
put the friction.

The percentile is the median and the 90th, not the mean. One machine that took
three weeks because somebody was on holiday moves a mean and does not move a
median, and a process metric that a holiday can swing is one nobody trusts
twice.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

    from devrepro.core.models import Policy

__all__ = [
    "MINIMUM_COHORT",
    "OnboardingStats",
    "PolicySimulation",
    "onboarding_stats",
    "simulate_policy",
]

#: Below this many machines, no distribution is reported. A percentile over
#: four machines identifies individuals, which is the thing this refuses to be.
MINIMUM_COHORT = 5


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile: `ceil(fraction * n)`, one-indexed.

    Nearest-rank rather than interpolated, because every value here is a real
    machine's real elapsed time and inventing one between two of them to
    satisfy a formula reports a duration nobody experienced.

    `ceil`, not `round`. With six values `round(0.9 * 6) - 1` lands on index
    four -- the fifth of six -- so the one machine that took three weeks never
    reaches the p90 at all. A tail metric that systematically excludes the tail
    is the number this exists to expose, quietly wrong in the flattering
    direction, and it reads as a healthy fleet forever.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = math.ceil(fraction * len(ordered))
    index = max(0, min(len(ordered) - 1, rank - 1))
    return ordered[index]


@dataclass(frozen=True)
class OnboardingStats:
    """How long machines take to become usable, as a distribution and nothing else."""

    cohort: int
    median_hours: float | None
    p90_hours: float | None
    #: Machines that enrolled and have never reported READY. The number people
    #: most want and least expect: an onboarding metric computed only over
    #: successes hides everybody still stuck.
    never_ready: int = 0
    withheld_because: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "cohort": self.cohort,
            "median_hours": self.median_hours,
            "p90_hours": self.p90_hours,
            "never_ready": self.never_ready,
            "withheld_because": self.withheld_because,
            "scope": (
                "Aggregate only. No machine, user or label appears here, and nothing "
                "is reported below a cohort of "
                f"{MINIMUM_COHORT}: a distribution over a handful of machines "
                "identifies individuals. This is a process metric, not a "
                "performance one."
            ),
        }


def onboarding_stats(
    machines: Sequence[dict[str, Any]],
    snapshots: Sequence[dict[str, Any]],
) -> OnboardingStats:
    """Time from enrolment to the first READY snapshot, per machine, aggregated.

    `machines` need `id` and `created_at`; `snapshots` need `machine_id`,
    `created_at` and `verdict`. Both come from the fleet database as rows, so
    this stays testable without one.
    """
    first_ready: dict[Any, datetime] = {}
    for snapshot in snapshots:
        if str(snapshot.get("verdict", "")).upper() != "READY":
            continue
        stamp = _parse(snapshot.get("created_at"))
        machine = snapshot.get("machine_id")
        if stamp is None or machine is None:
            continue
        existing = first_ready.get(machine)
        if existing is None or stamp < existing:
            first_ready[machine] = stamp

    durations: list[float] = []
    never = 0
    for machine in machines:
        enrolled = _parse(machine.get("created_at"))
        if enrolled is None:
            continue
        ready = first_ready.get(machine.get("id"))
        if ready is None:
            never += 1
            continue
        hours = (ready - enrolled).total_seconds() / 3600
        if hours >= 0:
            durations.append(hours)

    cohort = len(durations)
    if cohort < MINIMUM_COHORT:
        return OnboardingStats(
            cohort=cohort,
            median_hours=None,
            p90_hours=None,
            never_ready=never,
            withheld_because=(
                f"{cohort} machine(s) have reached READY; no distribution is reported "
                f"below {MINIMUM_COHORT}, because one over a handful identifies "
                "individuals."
            ),
        )

    return OnboardingStats(
        cohort=cohort,
        median_hours=round(_percentile(durations, 0.5), 2),
        p90_hours=round(_percentile(durations, 0.9), 2),
        never_ready=never,
    )


@dataclass(frozen=True)
class PolicySimulation:
    """Who a proposed policy would newly break, before it is rolled out."""

    evaluated: int
    newly_failing: int
    #: Which requirement caused each new failure, counted. The number alone
    #: says how bad; this says which line of the policy to soften.
    causes: dict[str, int]
    #: Machines with no usable snapshot. Reported rather than dropped: a
    #: simulation over half a fleet that presents itself as a full one is the
    #: way this feature would mislead.
    unevaluated: int = 0

    @property
    def safe(self) -> bool:
        return self.newly_failing == 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "evaluated": self.evaluated,
            "unevaluated": self.unevaluated,
            "newly_failing": self.newly_failing,
            "causes": dict(sorted(self.causes.items(), key=lambda kv: (-kv[1], kv[0]))),
            "safe": self.safe,
            "caveat": (
                "Simulated against each machine's most recent stored snapshot, which "
                "may be old. A machine that has not reported since the change it "
                "needs will show as failing when it is not, and one that has drifted "
                "since its last scan will show as passing when it is not."
            ),
        }


def simulate_policy(
    policy: Policy,
    latest_snapshots: Sequence[dict[str, Any]],
) -> PolicySimulation:
    """Apply a proposed policy to the fleet's last-known state.

    Each snapshot needs a `tools` mapping of name to version. Anything without
    one is counted as unevaluated rather than assumed to pass, because a
    simulation that quietly narrows its own denominator reports a smaller blast
    radius than the rollout will have.
    """
    from devrepro.core.versioning import satisfies

    required: dict[str, str] = {**policy.required_runtimes, **policy.required_tools}

    evaluated = 0
    unevaluated = 0
    failing = 0
    causes: dict[str, int] = {}

    for snapshot in latest_snapshots:
        tools = snapshot.get("tools")
        if not isinstance(tools, dict) or not tools:
            unevaluated += 1
            continue
        evaluated += 1

        broke = False
        for name, spec in sorted(required.items()):
            version = tools.get(name)
            if version is None:
                causes[f"{name} (absent)"] = causes.get(f"{name} (absent)", 0) + 1
                broke = True
                continue
            try:
                if not satisfies(str(version), spec):
                    key = f"{name} {spec}"
                    causes[key] = causes.get(key, 0) + 1
                    broke = True
            except (ValueError, TypeError):
                # An unparseable version is not evidence of a failure. Counting
                # it as one would inflate the blast radius and get a sensible
                # policy rejected.
                continue
        if broke:
            failing += 1

    return PolicySimulation(
        evaluated=evaluated,
        newly_failing=failing,
        causes=causes,
        unevaluated=unevaluated,
    )
