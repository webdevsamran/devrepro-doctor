"""How often reproductions actually work, recorded locally and published honestly.

Every tool in this space claims to reproduce environments and none of them
publishes a rate. That is not an accident: the number is going to be
disappointing, because a machine's state includes things no container carries --
a database with rows in it, a credential, a file outside the repository, a
kernel feature, a GPU driver.

Publishing it anyway is the point. A tool that says "reproduces 60% of reported
environment failures, and here is the breakdown of the other 40%" is more
useful than one that implies 100% and is discovered to be wrong by each user
separately. The 40% is also the roadmap.

**Local, and it stays local.** The corpus is a file in the user's own history
directory. Nothing is uploaded, and there is no aggregate anywhere -- that is
the shape the project's anti-goals forbid, and the same reasoning that made the
"State of Dev Environments" report a documented non-goal. The published rate is
whatever *this project's maintainers* record from their own corpus and put in
the docs by hand, which is a smaller claim and a true one.

Recording an outcome is explicit. `devrepro reproduce --record` takes the
verdict from the person who ran it; nothing infers success from an exit code,
because "the container ran" and "the failure reproduced" are different
questions and only a person can answer the second.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "CORPUS_FILENAME",
    "OUTCOMES",
    "Attempt",
    "CorpusSummary",
    "read_corpus",
    "record_attempt",
    "summarise",
]

CORPUS_FILENAME = "reproductions.jsonl"

#: The outcomes worth telling apart. "Reproduced a different failure" is its own
#: answer and the most important one to keep separate: counted as a success it
#: inflates the rate, and counted as a failure it hides the fact that the recipe
#: built and ran.
OUTCOMES: dict[str, str] = {
    "reproduced": "The reported failure happened, with the reported symptom.",
    "not-reproduced": "The command succeeded in the container.",
    "different-failure": (
        "Something failed, but not the reported thing. The recipe ran; it captured the wrong state."
    ),
    "could-not-build": "The recipe did not produce a runnable container.",
    "precondition-unmet": (
        "The reproduction needed something no container carries -- data, a credential, a device."
    ),
}


@dataclass(frozen=True)
class Attempt:
    """One recorded reproduction attempt."""

    outcome: str
    recorded_at: str
    #: What the recipe was for, in the user's own words. Free text, and never
    #: read by anything -- it is here so a corpus is reviewable by the person
    #: who owns it rather than only countable.
    note: str = ""
    base_image: str = ""
    pinned: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "recorded_at": self.recorded_at,
            "note": self.note,
            "base_image": self.base_image,
            "pinned": self.pinned,
        }


class CorpusError(Exception):
    """Raised when the corpus file cannot be read or an outcome is unknown."""


def record_attempt(directory: Path, attempt: Attempt) -> Attempt:
    """Append one outcome. Never rewrites, never aggregates elsewhere."""
    if attempt.outcome not in OUTCOMES:
        raise CorpusError(
            f"unknown outcome {attempt.outcome!r}; expected one of {', '.join(OUTCOMES)}"
        )
    directory.mkdir(parents=True, exist_ok=True)
    line = json.dumps(attempt.as_dict(), sort_keys=True, separators=(",", ":"))
    with (directory / CORPUS_FILENAME).open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    return attempt


def read_corpus(directory: Path) -> tuple[Attempt, ...]:
    """Every recorded attempt, in the order they were recorded."""
    path = directory / CORPUS_FILENAME
    if not path.is_file():
        return ()
    attempts: list[Attempt] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CorpusError(f"cannot read {CORPUS_FILENAME}: {exc}") from exc

    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            attempts.append(
                Attempt(
                    outcome=str(record["outcome"]),
                    recorded_at=str(record["recorded_at"]),
                    note=str(record.get("note", "")),
                    base_image=str(record.get("base_image", "")),
                    pinned=bool(record.get("pinned", False)),
                )
            )
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise CorpusError(f"{CORPUS_FILENAME} line {number} is malformed: {exc}") from exc
    return tuple(attempts)


@dataclass(frozen=True)
class CorpusSummary:
    """The rate, the breakdown, and whether the sample means anything."""

    total: int
    counts: dict[str, int]
    #: `None` below the sample floor. A rate computed from four attempts is a
    #: number with no information in it, and printing one invites somebody to
    #: quote it.
    rate: float | None
    caveat: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "counts": dict(sorted(self.counts.items())),
            "reproduction_rate": self.rate,
            "caveat": self.caveat,
        }


#: Below this many attempts no rate is reported. Ten is not statistical rigour;
#: it is the point below which a percentage is obviously theatre.
MINIMUM_SAMPLE = 10


def summarise(attempts: tuple[Attempt, ...]) -> CorpusSummary:
    """The rate over recorded attempts, with the denominator stated.

    `different-failure` counts as **not** reproduced. That is the choice that
    decides whether the number is honest: a recipe that built, ran and produced
    some other error has not reproduced anything, and counting it as a success
    is how every vendor benchmark ends up at 95%.
    """
    counts: dict[str, int] = {}
    for attempt in attempts:
        counts[attempt.outcome] = counts.get(attempt.outcome, 0) + 1

    total = len(attempts)
    if total < MINIMUM_SAMPLE:
        return CorpusSummary(
            total=total,
            counts=counts,
            rate=None,
            caveat=(
                f"{total} recorded attempt(s); no rate is reported below "
                f"{MINIMUM_SAMPLE}. A percentage from a handful of attempts is a "
                "number somebody will quote and nobody can defend."
            ),
        )

    reproduced = counts.get("reproduced", 0)
    return CorpusSummary(
        total=total,
        counts=counts,
        rate=round(reproduced / total, 3),
        caveat=(
            "Recorded on this machine only; nothing is uploaded and there is no "
            "aggregate anywhere. 'different-failure' counts as not reproduced -- a "
            "recipe that ran and produced some other error has reproduced nothing, "
            "and counting it as success is how a rate reaches 95%."
        ),
    )
