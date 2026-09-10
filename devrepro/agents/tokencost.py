"""What an unprepared repository costs an agent, in tokens, roughly.

The argument for documenting a project's setup has always been qualitative --
"it helps onboarding" -- and qualitative arguments lose to whatever is urgent.
A number changes the conversation, because tokens have a price and turns have a
latency, and both are on somebody's invoice.

**This is an estimate and the module says so everywhere.** It is not a
measurement, cannot be one without running an agent against the repository many
times, and would be dishonest presented as anything else. What it does is apply
a stated model to signals `agent-check` already collected:

    a command that does not resolve  -> the agent tries it, reads the error,
                                        searches for the real command, tries
                                        again. Several turns.
    a stale declared command         -> the same, plus the misdirection of
                                        having been told something confidently
                                        wrong.
    a CI gate nobody declared        -> discovered when the pull request goes
                                        red, which is a whole extra cycle.
    no manifest at all               -> the agent reconstructs the build from
                                        the source tree.

The per-signal costs below are order-of-magnitude figures, chosen to be
defensible rather than precise, and every one is a named constant a reader can
disagree with. The output rounds hard and leads with the word "roughly",
because a figure like "43,712 tokens" implies a measurement nobody made.

What this deliberately does not do is price it. Model pricing changes monthly,
varies by provider and tier, and a stale dollar figure in a diagnostic tool is
worse than no dollar figure. Tokens are the durable unit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

    from devrepro.agents.freshness import StaleCommand
    from devrepro.agents.manifest import AgentManifest, CommandCheck

__all__ = [
    "COST_MODEL",
    "TOKENS_PER_TURN",
    "TokenEstimate",
    "estimate_token_cost",
]

#: A turn is a request plus a response plus the context carried along. 8k is a
#: deliberately round middle: a small edit turn is well under it, a turn that
#: reads three files is well over, and the estimate is not improved by
#: pretending to know which.
TOKENS_PER_TURN = 8_000

#: (signal, turns wasted, why). Every number here is arguable, which is why
#: each is named and carries its reasoning rather than being buried in a
#: formula.
COST_MODEL: tuple[tuple[str, int, str], ...] = (
    (
        "no-manifest",
        6,
        "With no AGENTS.md the agent reconstructs the build from the source "
        "tree: read the manifest, guess the test command, run it, read the "
        "failure, try again.",
    ),
    (
        "failing-command",
        3,
        "A declared command that does not work here costs the attempt, the "
        "error, and the search for what the command should have been.",
    ),
    (
        "stale-command",
        4,
        "Worse than an absent command: the agent was told something confidently "
        "and has to disbelieve the manifest before it looks elsewhere.",
    ),
    (
        "undeclared-ci-gate",
        5,
        "Discovered when the pull request goes red. That is a full cycle -- push, "
        "wait, read the log, fix, push -- and the agent had no way to know.",
    ),
    (
        "manifest-disagreement",
        2,
        "Two manifests saying different things; the agent picks one and finds out later which.",
    ),
)

_TURNS = {name: turns for name, turns, _why in COST_MODEL}


@dataclass(frozen=True)
class TokenEstimate:
    """Roughly what this repository's gaps cost an agent, and from what."""

    turns: int
    tokens: int
    #: (signal, count, turns each, why) for everything that contributed.
    contributions: tuple[tuple[str, int, int, str], ...] = ()

    @property
    def rounded_tokens(self) -> int:
        """Rounded to the nearest 5k.

        A figure like 43,712 implies a measurement. This is a model applied to
        a count, and the rounding is the honest way to say so in the number
        itself rather than only in a footnote.
        """
        if self.tokens <= 0:
            return 0
        return max(5_000, round(self.tokens / 5_000) * 5_000)

    def as_dict(self) -> dict[str, Any]:
        return {
            "estimated_wasted_turns": self.turns,
            "estimated_wasted_tokens": self.rounded_tokens,
            "tokens_per_turn_assumed": TOKENS_PER_TURN,
            "basis": [
                {"signal": name, "count": count, "turns_each": each, "why": why}
                for name, count, each, why in self.contributions
            ],
            "caveat": (
                "An estimate from a stated model, not a measurement. Every "
                "per-signal cost is a named constant in "
                "devrepro/agents/tokencost.py and is arguable. No price is "
                "attached: model pricing changes monthly and a stale dollar "
                "figure would be worse than none."
            ),
        }


def estimate_token_cost(
    *,
    manifests: Iterable[AgentManifest],
    checks: Iterable[CommandCheck],
    stale: Iterable[StaleCommand],
    drift: Iterable[str],
    disagreements: Iterable[object] = (),
) -> TokenEstimate:
    """Apply the cost model to what `agent-check` found.

    Counts, not severities. Every signal here is one the tool already reports
    individually; this only says what the pile of them adds up to, which is the
    part that gets a documentation task prioritised.
    """
    counts: dict[str, int] = {}

    if not list(manifests):
        counts["no-manifest"] = 1

    # `ok` rather than `resolved`: a command can resolve to a program and
    # still be the wrong one, and the agent pays either way.
    failing = sum(1 for check in checks if not check.ok)
    if failing:
        counts["failing-command"] = failing

    stale_count = len(list(stale))
    if stale_count:
        counts["stale-command"] = stale_count

    drift_count = len(list(drift))
    if drift_count:
        counts["undeclared-ci-gate"] = drift_count

    disagreement_count = len(list(disagreements))
    if disagreement_count:
        counts["manifest-disagreement"] = disagreement_count

    contributions: list[tuple[str, int, int, str]] = []
    total_turns = 0
    for name, turns, why in COST_MODEL:
        count = counts.get(name, 0)
        if not count:
            continue
        contributions.append((name, count, turns, why))
        total_turns += count * turns

    return TokenEstimate(
        turns=total_turns,
        tokens=total_turns * TOKENS_PER_TURN,
        contributions=tuple(contributions),
    )
