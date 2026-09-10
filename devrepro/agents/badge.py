"""The readiness score as a badge, and the two ways a badge lies.

A README badge is the only measurement most people will ever see of a
repository, which makes it worth getting right and worth being suspicious of.
The two failure modes are opposite and both common:

**A badge that never changes.** Generated once, committed as a static SVG, and
still green two years after the thing it measured stopped being true. This
emits a *shields.io endpoint* payload instead -- a small JSON document that
shields fetches when the badge renders -- so the number comes from a scan
rather than from whenever somebody last thought about it.

**A badge that flatters.** Colour is where this happens: green at 60% is a
choice to make a mediocre score look fine. The thresholds here match
`AgentReadiness.grade`, which the CLI already prints, so the badge and the
command cannot disagree. Anything below "workable" is red, not orange.

The payload is produced and never published. Serving it means either a public
endpoint or a committed file in a branch, and both are the user's decision
about what to publish about their own repository.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from devrepro.agents.score import AgentReadiness

__all__ = ["BADGE_COLOURS", "SHIELDS_SCHEMA_VERSION", "badge_markdown", "badge_payload"]

#: The schema shields.io's endpoint badge expects. Version 1 is the only one it
#: has ever accepted, and it rejects a payload without it outright.
SHIELDS_SCHEMA_VERSION = 1

#: Grade to colour. Deliberately harsh in the middle: "workable" means an agent
#: can get something done here after some flailing, and yellow is an honest
#: description of that. Green is reserved for a repository where the declared
#: commands actually run.
BADGE_COLOURS: dict[str, str] = {
    "ready": "brightgreen",
    "workable": "yellow",
    "rough": "orange",
    "unprepared": "red",
}


def badge_payload(
    readiness: AgentReadiness,
    *,
    label: str = "agent-ready",
) -> dict[str, Any]:
    """A shields.io endpoint payload for this readiness score.

    The message carries the percentage *and* the grade, because a number alone
    invites the reader to supply their own threshold -- and everybody's private
    threshold for "is 62% fine" is different from the one the tool used.
    """
    return {
        "schemaVersion": SHIELDS_SCHEMA_VERSION,
        "label": label,
        "message": f"{readiness.percent}% {readiness.grade}",
        "color": BADGE_COLOURS.get(readiness.grade, "lightgrey"),
    }


def badge_markdown(endpoint_url: str, *, label: str = "agent-ready") -> str:
    """The Markdown to paste, given somewhere the payload will be served.

    Takes the URL rather than inventing one. A badge pointing at a URL this
    tool guessed would render as "invalid" for everybody who did not happen to
    publish it exactly there, and a broken badge is worse than none.
    """
    from urllib.parse import quote

    return (
        f"[![{label}](https://img.shields.io/endpoint?url={quote(endpoint_url, safe='')})]"
        "(https://github.com/webdevsamran/devrepro-doctor)"
    )
