"""A gate that stops an agent session before it starts, and why it is opt-in.

The failure this exists for is specific and documented: an agent begins work in
an environment nobody verified, spends its first ten turns discovering that the
declared setup command does not run, and either gives up expensively or works
around the problem by doing something nobody sanctioned. The 2026 incidents
that made this a category -- a production database deleted in nine seconds, an
environment recreated during a thirteen-hour outage -- share that shape:
permissions were broad, the environment was unverified, and human approval
arrived after the fact.

The gate is the cheap half of the fix. Before the session starts, ask whether
the commands the repository declares actually run here, and whether this shell
can reach production. If the answer is no, say so *first*, when it costs one
sentence instead of ten turns.

**It is generated, never installed.** Writing into somebody's agent
configuration is exactly the class of action this project makes people ask for
by name -- a hook is code that runs on every session, and installing one on a
user's behalf is a larger permission than any diagnostic needs. `devrepro
agent-check --gate` emits the configuration; the user decides where it goes.

**The exit code is the interface.** A hook that prints a warning is a hook
people stop reading. `--gate` exits BLOCKED when readiness is below the
threshold, which is what an agent runner can actually act on -- and a threshold
rather than "any finding", because a gate that fires on every repository is one
that gets removed in week one, the same reasoning that produced `guard --scope
changed`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from devrepro.agents.blast_radius import BlastRadius
    from devrepro.agents.score import AgentReadiness

__all__ = [
    "DEFAULT_THRESHOLD",
    "GateVerdict",
    "claude_code_hook",
    "evaluate_gate",
    "generic_hook_script",
]

#: Percentage below which a session is gated. Matches the floor of "workable"
#: in `AgentReadiness.grade`: below this an agent is guessing, and above it the
#: declared commands mostly work.
DEFAULT_THRESHOLD = 60


@dataclass(frozen=True)
class GateVerdict:
    """Whether to let a session start, and the reason either way."""

    allowed: bool
    score: int
    threshold: int
    reasons: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "score": self.score,
            "threshold": self.threshold,
            "reasons": list(self.reasons),
        }


def evaluate_gate(
    readiness: AgentReadiness,
    *,
    blast_radius: BlastRadius | None = None,
    threshold: int = DEFAULT_THRESHOLD,
    block_on_production: bool = True,
) -> GateVerdict:
    """Whether an agent session should start in this environment.

    Two independent grounds, and they answer different questions. Readiness asks
    whether the agent can get work done; blast radius asks what it could reach
    if it went wrong. A repository can score well on the first and still be a
    place nobody should start an unattended session -- a clean, well-documented
    checkout with production credentials in the environment is the *worst* case,
    not a safe one, because everything about it invites confidence.
    """
    reasons: list[str] = []

    if readiness.percent < threshold:
        failing = [f.name for f in readiness.factors if f.earned < f.possible]
        reasons.append(
            f"Agent readiness is {readiness.percent}% ({readiness.grade}), below the "
            f"{threshold}% threshold. Weakest: {', '.join(failing[:3]) or 'unknown'}."
        )

    if block_on_production and blast_radius is not None:
        production = [e for e in blast_radius.exposures if "production" in e.kind]
        if production:
            reasons.append(
                "This shell carries production-adjacent context: "
                + "; ".join(e.detail for e in production[:2])
                + ". An agent starting here can reach it."
            )

    return GateVerdict(
        allowed=not reasons,
        score=readiness.percent,
        threshold=threshold,
        reasons=tuple(reasons),
    )


def claude_code_hook(*, threshold: int = DEFAULT_THRESHOLD, path: str = ".") -> str:
    """A Claude Code `SessionStart` hook, as JSON to paste into settings.

    `SessionStart` rather than `PreToolUse`: the point is to answer before any
    work happens, and a per-tool hook that re-scans the machine on every call
    would add seconds to every single tool use. Once per session is the whole
    idea.
    """
    return (
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": (
                                        f"devrepro agent-check {path} --gate "
                                        f"--threshold {threshold}"
                                    ),
                                }
                            ]
                        }
                    ]
                }
            },
            indent=2,
        )
        + "\n"
    )


def generic_hook_script(*, threshold: int = DEFAULT_THRESHOLD, path: str = ".") -> str:
    """A shell wrapper for any agent runner that has no hook system.

    Deliberately a wrapper rather than an edit to the user's shell profile.
    Something that gates every command in every shell is a thing people fight
    with at the worst possible moment; something they invoke on purpose is a
    thing they keep.
    """
    return f"""#!/usr/bin/env bash
# Gate an agent session on this environment. Generated by devrepro; not installed.
#
# Usage:  agent-gate.sh <your agent command...>
#
# Exits before starting the agent if the repository's declared commands do not
# run here, or if this shell can reach production. Both are cheap to find out
# now and expensive to find out on turn ten.
set -euo pipefail

if ! devrepro agent-check {path} --gate --threshold {threshold}; then
  echo "devrepro: refusing to start an agent session in this environment." >&2
  echo "Run 'devrepro agent-check {path}' for the full report." >&2
  exit 2
fi

exec "$@"
"""
