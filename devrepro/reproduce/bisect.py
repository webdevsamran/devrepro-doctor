"""`git bisect` for a machine, and delta debugging on top of it.

Two snapshots, one where the build worked and one where it did not, and forty
differences between them. Everybody's instinct is to read the diff and pick the
suspicious-looking line, which works when the cause is a runtime version and
fails completely when it is a locale, a PATH order or an environment variable
nobody thinks about. Bisection does not care what looks suspicious.

The interface is `git bisect`'s on purpose, because it is the one everybody
already knows: the tool proposes a candidate, you answer good or bad, it halves
the space. What differs is what is being halved -- not commits but *dimensions
of an environment*, each of which the caller has to actually apply before
answering.

**The verdict comes from outside.** This module never applies a change and
never runs a test. It cannot: applying an environment dimension means editing a
PATH, installing a version, or setting a variable on somebody's machine, and
that is the whole class of action this project does not take unasked. The
caller supplies a callback -- a person answering a prompt, or a command whose
exit code decides -- and the search does the halving.

**Bisect finds a boundary; minimisation finds a set.** They answer different
questions and both are here. Bisect assumes one dimension is responsible and
converges in log(n) verdicts. Delta debugging assumes several might be, costs
more verdicts, and returns the smallest combination that still fails -- which is
the honest answer when two changes only break things together, and that case is
common enough to be worth the extra rounds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

__all__ = [
    "BisectResult",
    "Dimension",
    "MinimisationResult",
    "Verdict",
    "bisect_dimensions",
    "minimise_dimensions",
]

#: What the caller answers. `True` means "still broken with this applied".
#: Phrased as `fails` rather than `ok` because every search here is looking for
#: the failure, and a callback named `ok` inverts under the reader's nose.
Verdict = "Callable[[tuple[Dimension, ...]], bool]"


@dataclass(frozen=True)
class Dimension:
    """One difference between the working and broken environments."""

    name: str
    working_value: str | None
    broken_value: str | None

    def describe(self) -> str:
        return f"{self.name}: {self.working_value!r} -> {self.broken_value!r}"


@dataclass(frozen=True)
class BisectResult:
    """What the search concluded, and how much it cost to conclude it."""

    culprit: Dimension | None
    verdicts: int
    #: Every (candidate set, answer) pair, in order. Kept because a bisect that
    #: reaches a surprising answer is one somebody will want to audit, and "it
    #: said so" is not an audit trail.
    trail: tuple[tuple[tuple[str, ...], bool], ...] = ()
    #: Set when the search could not converge, saying why. There are two ways
    #: for that to happen and they mean opposite things.
    inconclusive_because: str | None = None


def bisect_dimensions(
    dimensions: Sequence[Dimension],
    fails: Callable[[tuple[Dimension, ...]], bool],
) -> BisectResult:
    """Halve the dimension set until one dimension is responsible.

    The two sanity checks first, because skipping them is how a bisect returns
    a confident wrong answer:

    * If applying **nothing** already fails, the cause is not in this diff at
      all -- the "working" snapshot does not work either, and every subsequent
      verdict is noise.
    * If applying **everything** does not fail, the diff does not contain the
      cause, and the search would otherwise converge on whichever dimension
      happened to be last.

    Both are reported as inconclusive rather than as a culprit. A bisect that
    names a dimension it has not actually implicated is worse than one that
    admits the diff was the wrong place to look.
    """
    trail: list[tuple[tuple[str, ...], bool]] = []
    verdicts = 0

    def ask(candidate: tuple[Dimension, ...]) -> bool:
        nonlocal verdicts
        verdicts += 1
        answer = fails(candidate)
        trail.append((tuple(d.name for d in candidate), answer))
        return answer

    if not dimensions:
        return BisectResult(
            culprit=None,
            verdicts=0,
            inconclusive_because="The two environments do not differ in any dimension.",
        )

    if ask(()):
        return BisectResult(
            culprit=None,
            verdicts=verdicts,
            trail=tuple(trail),
            inconclusive_because=(
                "The baseline already fails with nothing applied. The 'working' "
                "environment does not work either, so the cause is outside this "
                "diff and every further verdict would be noise."
            ),
        )

    if not ask(tuple(dimensions)):
        return BisectResult(
            culprit=None,
            verdicts=verdicts,
            trail=tuple(trail),
            inconclusive_because=(
                "Applying every difference does not reproduce the failure. Whatever "
                "causes it is not in this diff -- state on disk, a service, a remote "
                "change -- and bisecting further would converge on whichever "
                "dimension happened to come last."
            ),
        )

    lower: list[Dimension] = []
    remaining = list(dimensions)

    while len(remaining) > 1:
        half = len(remaining) // 2
        candidate = (*lower, *remaining[:half])
        if ask(candidate):
            remaining = remaining[:half]
        else:
            lower = [*lower, *remaining[:half]]
            remaining = remaining[half:]

    return BisectResult(culprit=remaining[0], verdicts=verdicts, trail=tuple(trail))


@dataclass(frozen=True)
class MinimisationResult:
    """The smallest set of dimensions that still reproduces the failure."""

    minimal: tuple[Dimension, ...] = ()
    verdicts: int = 0
    trail: tuple[tuple[tuple[str, ...], bool], ...] = field(default=())
    inconclusive_because: str | None = None

    @property
    def interacting(self) -> bool:
        """Whether more than one dimension is needed together.

        The answer bisection structurally cannot give. Two changes that are
        each harmless and break things in combination are common -- a version
        bump plus a flag, a locale plus a filename -- and a bisect run against
        that will name one of them and be wrong in a way that reads as right.
        """
        return len(self.minimal) > 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "minimal": [d.describe() for d in self.minimal],
            "verdicts": self.verdicts,
            "interacting": self.interacting,
            "inconclusive_because": self.inconclusive_because,
        }


def minimise_dimensions(
    dimensions: Sequence[Dimension],
    fails: Callable[[tuple[Dimension, ...]], bool],
    *,
    max_verdicts: int = 200,
) -> MinimisationResult:
    """The smallest subset that still fails, by delta debugging.

    Zeller's ddmin, in the shape that matters here: split into `n` chunks, try
    each chunk alone, then try each complement. A chunk that fails alone becomes
    the new candidate; a complement that fails means the removed chunk was
    irrelevant. When neither works, granularity doubles.

    `max_verdicts` is a real bound, not a formality. Every verdict here is a
    human applying an environment change and running a build -- minutes, not
    milliseconds -- so an unbounded search is one that gets abandoned halfway
    with nothing to show. The bound is reported when it bites, because a
    truncated search returning its current best as "minimal" would be the
    dishonest version.
    """
    trail: list[tuple[tuple[str, ...], bool]] = []
    verdicts = 0

    def ask(candidate: tuple[Dimension, ...]) -> bool:
        nonlocal verdicts
        verdicts += 1
        answer = fails(candidate)
        trail.append((tuple(d.name for d in candidate), answer))
        return answer

    current = list(dimensions)
    if not current:
        return MinimisationResult(
            inconclusive_because="The two environments do not differ in any dimension."
        )
    if not ask(tuple(current)):
        return MinimisationResult(
            verdicts=verdicts,
            trail=tuple(trail),
            inconclusive_because=(
                "Applying every difference does not reproduce the failure, so there "
                "is nothing here to minimise."
            ),
        )

    granularity = 2
    while len(current) > 1:
        if verdicts >= max_verdicts:
            return MinimisationResult(
                minimal=tuple(current),
                verdicts=verdicts,
                trail=tuple(trail),
                inconclusive_because=(
                    f"Stopped after {max_verdicts} verdicts. The set below still "
                    "reproduces the failure but may not be minimal -- each verdict "
                    "costs a human applying a change and running a build, so the "
                    "search is bounded rather than exhaustive."
                ),
            )

        size = max(1, len(current) // granularity)
        chunks = [current[i : i + size] for i in range(0, len(current), size)]

        reduced = False
        for chunk in chunks:
            if chunk and ask(tuple(chunk)):
                current = chunk
                granularity = 2
                reduced = True
                break
        if reduced:
            continue

        for chunk in chunks:
            complement = [d for d in current if d not in chunk]
            if complement and ask(tuple(complement)):
                current = complement
                granularity = max(2, granularity - 1)
                reduced = True
                break
        if reduced:
            continue

        if granularity >= len(current):
            break
        granularity = min(len(current), granularity * 2)

    return MinimisationResult(minimal=tuple(current), verdicts=verdicts, trail=tuple(trail))
