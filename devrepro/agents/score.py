"""How ready is this repository for an AI coding agent?

A single number, and every point explained -- the same contract
`devrepro/rules/score.py` holds for reproducibility. A score whose derivation
you cannot see is a score you cannot act on, and one nobody should trust.

What it measures is deliberately narrow: whether an agent working here has
accurate instructions and a machine that can follow them. It says nothing about
whether the agent will do good work, and claiming otherwise would be the kind
of unfounded number this project's own docs warn against.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from devrepro.agents.freshness import ManifestDisagreement, StaleCommand
    from devrepro.agents.manifest import AgentManifest, CommandCheck

__all__ = ["AgentReadiness", "ReadinessFactor", "score_readiness"]


@dataclass(frozen=True)
class ReadinessFactor:
    """One scored aspect, with the reason for the score it got."""

    name: str
    earned: int
    possible: int
    explanation: str


@dataclass(frozen=True)
class AgentReadiness:
    """The score and its derivation."""

    total: int
    possible: int
    factors: tuple[ReadinessFactor, ...]

    @property
    def percent(self) -> int:
        return round(100 * self.total / self.possible) if self.possible else 0

    @property
    def grade(self) -> str:
        pct = self.percent
        if pct >= 90:
            return "ready"
        if pct >= 60:
            return "workable"
        if pct >= 30:
            return "rough"
        return "unprepared"


def score_readiness(
    *,
    manifests: Iterable[AgentManifest],
    checks: Iterable[CommandCheck],
    drift: list[str],
    stale: Iterable[StaleCommand],
    disagreements: Iterable[ManifestDisagreement],
) -> AgentReadiness:
    """Score a repository from the signals `agent-check` already gathered.

    Weighted by what actually costs an agent time. A command that cannot run at
    all is worth more than one that is merely undocumented, because the first
    ends the turn and the second only misleads.
    """
    manifest_list = list(manifests)
    check_list = list(checks)
    stale_list = list(stale)
    disagreement_list = list(disagreements)

    factors: list[ReadinessFactor] = []

    # 1. Is there a manifest at all? ---------------------------------------
    if manifest_list:
        names = ", ".join(m.path for m in manifest_list)
        factors.append(
            ReadinessFactor("manifest-present", 3, 3, f"Agent instructions found: {names}.")
        )
    else:
        factors.append(
            ReadinessFactor(
                "manifest-present",
                0,
                3,
                "No AGENTS.md, CLAUDE.md or equivalent. An agent has to infer how "
                "to set up, build and test this project, which is where turns and "
                "tokens go.",
            )
        )

    # 2. Does it declare anything runnable? --------------------------------
    runnable = [c for c in check_list if c.command.program not in {"cd", "echo"}]
    if runnable:
        factors.append(
            ReadinessFactor(
                "commands-declared",
                2,
                2,
                f"{len(runnable)} command(s) declared.",
            )
        )
    else:
        factors.append(
            ReadinessFactor(
                "commands-declared",
                0,
                2,
                "The manifest declares no runnable commands, so it tells an agent "
                "nothing it can act on.",
            )
        )

    # 3. Do those commands resolve on this machine? ------------------------
    missing = [c for c in check_list if c.status == "missing"]
    off_path = [c for c in check_list if c.status == "not-on-path"]
    if not runnable:
        earned, explanation = 0, "No commands to resolve."
    elif missing:
        earned = 0
        explanation = (
            f"{len(missing)} declared command(s) name a program that is not "
            f"installed: {', '.join(sorted({c.command.program for c in missing}))}. "
            "An agent fails on these immediately."
        )
    elif off_path:
        earned = 2
        explanation = (
            f"{len(off_path)} program(s) are installed but not on PATH in this "
            "shell. An agent cannot tell that apart from missing, and will try "
            "to install what is already there."
        )
    else:
        earned = 4
        explanation = "Every declared command resolves on this machine."
    factors.append(ReadinessFactor("commands-resolve", earned, 4, explanation))

    # 4. Are the declared targets still real? ------------------------------
    if stale_list:
        factors.append(
            ReadinessFactor(
                "commands-current",
                0,
                3,
                f"{len(stale_list)} declared command(s) name a script or target "
                "this project no longer defines. The program exists, so nothing "
                "catches it until the agent runs it.",
            )
        )
    else:
        factors.append(
            ReadinessFactor("commands-current", 3, 3, "Declared targets all exist in the project.")
        )

    # 5. Does the manifest match what CI enforces? -------------------------
    if drift:
        factors.append(
            ReadinessFactor(
                "matches-ci",
                0,
                3,
                f"CI enforces {len(drift)} gate(s) no manifest mentions. An agent "
                "can run everything it was told to, see green, and still be failed "
                "by the pull request.",
            )
        )
    else:
        factors.append(
            ReadinessFactor("matches-ci", 3, 3, "The manifest covers every gate CI runs.")
        )

    # 6. Do the manifests agree with each other? ---------------------------
    if len(manifest_list) < 2:
        factors.append(
            ReadinessFactor(
                "manifests-agree", 2, 2, "One manifest, so nothing can disagree with it."
            )
        )
    elif disagreement_list:
        factors.append(
            ReadinessFactor(
                "manifests-agree",
                0,
                2,
                f"{len(disagreement_list)} command(s) appear in one manifest and not "
                "another. Which instructions an agent follows depends on its vendor.",
            )
        )
    else:
        factors.append(
            ReadinessFactor("manifests-agree", 2, 2, "All manifests declare the same commands.")
        )

    total = sum(f.earned for f in factors)
    possible = sum(f.possible for f in factors)
    return AgentReadiness(total=total, possible=possible, factors=tuple(factors))
