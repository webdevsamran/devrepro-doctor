"""The documented ways to reach a maintainer must be things that exist.

Two of the four Code of Conduct files in this family of projects told people to
use GitHub features that are not real: "GitHub private message" (there is no
such feature) and "opening a private issue tagged `conduct`" (GitHub has
private *vulnerability reports*, not private issues). A third gave a profile
URL instead of a contact channel.

Someone reporting harassment is the worst possible person to hand a dead end,
so the channels are pinned here. This is a documentation test on purpose: the
defect was never in the code.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_CONTACT = "webdevsamran@users.noreply.github.com"

#: Mechanisms these files have claimed that GitHub does not provide.
_NONEXISTENT = (
    r"private message",
    r"private issue",
    r"report-user function",
)


def _read(name: str) -> str:
    return (_ROOT / name).read_text(encoding="utf-8")


def test_the_code_of_conduct_names_a_channel_that_exists() -> None:
    text = _read("CODE_OF_CONDUCT.md")
    assert _CONTACT in text, "CODE_OF_CONDUCT.md names no working contact address"
    assert "https://github.com/contact/report-abuse" in text, (
        "CODE_OF_CONDUCT.md dropped GitHub's report-abuse form"
    )


def test_no_document_invents_a_github_feature() -> None:
    offenders = []
    for name in ("CODE_OF_CONDUCT.md", "SECURITY.md", "CONTRIBUTING.md"):
        path = _ROOT / name
        if not path.exists():
            continue
        body = path.read_text(encoding="utf-8")
        for pattern in _NONEXISTENT:
            if re.search(pattern, body, re.IGNORECASE):
                offenders.append(f"{name}: {pattern!r}")
    assert not offenders, (
        "these documents point at GitHub features that do not exist: " + ", ".join(offenders)
    )


def test_security_reporting_points_at_private_vulnerability_reporting() -> None:
    """The channel has to be enabled on the repository, not just written down.

    It was documented in all four of these projects and enabled in none, so a
    reporter following the instructions reached a page they could not use.
    Enabling it is a repository setting, which a test cannot assert -- what it
    can assert is that the document keeps naming the real mechanism rather than
    drifting back to an invented one.
    """
    text = _read("SECURITY.md")
    assert re.search(r"security/advisories/new|GitHub Security Advisories", text), (
        "SECURITY.md no longer points at GitHub's private vulnerability reporting"
    )
    # api-verity-lab writes "public GitHub issue", the others "public issue";
    # the first version of this assertion matched only the latter.
    assert re.search(r"public (github )?issue", text, re.IGNORECASE), (
        "SECURITY.md dropped the do-not-file-publicly warning"
    )
