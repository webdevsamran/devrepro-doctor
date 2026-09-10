"""A scan verdict as a chat message, built and never sent.

Chat-ops for this is a two-line feature pretending to be an integration. What a
team actually wants is the verdict in the channel where they already are, and
the way to get it is a webhook that CI posts -- not a bot, not an app, not an
OAuth flow, and not a token this tool stores.

So this renders the payload and stops. `curl` posts it, or an existing action
does. The difference matters more than it sounds:

- A bot needs a token with permission to post as itself, which is a credential
  this project would have to hold, refresh and be trusted with. Everything else
  here is built so there is nothing to steal.
- A bot needs to be installed, approved and maintained by whoever administers
  the workspace, which is a different person from whoever wants the message.
- A webhook URL is already the thing every CI system has a secret slot for.

**Slack's Block Kit and Teams' Adaptive Cards, natively.** Not because two
formats are fun, but because posting Markdown into either produces something
that looks broken, and a status message that looks broken is one people stop
reading.

The message is deliberately short: a verdict, a count, and the blockers by name.
Detail belongs behind a link, because a channel message that scrolls is one
nobody reads past the first line -- which is exactly the line that matters.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from devrepro.core.models import FindingState

if TYPE_CHECKING:
    from devrepro.core.models import ScanReport

__all__ = ["CHAT_FORMATS", "MAX_LISTED", "render_chat_payload"]

CHAT_FORMATS: tuple[str, ...] = ("slack", "teams")

#: How many blockers get named. Beyond this the message scrolls, and a status
#: message that scrolls is one people stop reading -- including the first line,
#: which is the one that mattered.
MAX_LISTED = 5

_COLOURS = {
    "BLOCKED": "#d13438",
    "READY_WITH_WARNINGS": "#c19c00",
    "READY": "#107c10",
}


def _verdict(report: ScanReport) -> str:
    worst = report.worst_state()
    if worst in (FindingState.ERROR, FindingState.BLOCKED):
        return "BLOCKED"
    if worst in (FindingState.WARN, FindingState.UNKNOWN):
        return "READY_WITH_WARNINGS"
    return "READY"


def _blockers(report: ScanReport) -> list[str]:
    return [
        f.rule_id for f in report.findings if f.state in (FindingState.ERROR, FindingState.BLOCKED)
    ]


def render_chat_payload(
    report: ScanReport,
    *,
    platform: str = "slack",
    context: str = "",
    link: str | None = None,
) -> dict[str, Any]:
    """Build the webhook body for one chat platform.

    `context` is the caller's -- a repository name, a branch, a machine label.
    Nothing is inferred: a message that guesses which repository it is about is
    a message that will eventually be wrong in a channel, in front of everybody.
    """
    if platform not in CHAT_FORMATS:
        raise ValueError(f"unknown chat platform {platform!r}: {', '.join(CHAT_FORMATS)}")

    verdict = _verdict(report)
    blockers = _blockers(report)
    listed = blockers[:MAX_LISTED]
    remainder = len(blockers) - len(listed)

    headline = f"devrepro: {verdict.replace('_', ' ').lower()}"
    if context:
        headline = f"{headline} — {context}"

    body_lines: list[str] = []
    if blockers:
        body_lines.append(f"{len(blockers)} blocker(s):")
        body_lines.extend(f"• {rule_id}" for rule_id in listed)
        if remainder > 0:
            body_lines.append(f"…and {remainder} more.")
    else:
        counts: dict[str, int] = {}
        for finding in report.findings:
            counts[finding.state.value] = counts.get(finding.state.value, 0) + 1
        warn = counts.get("WARN", 0)
        body_lines.append(
            f"No blockers. {warn} warning(s)." if warn else "No blockers, no warnings."
        )
    if link:
        body_lines.append(link)
    body = "\n".join(body_lines)

    if platform == "slack":
        return {
            "text": headline,  # the notification preview, which Block Kit does not fill
            "blocks": [
                {"type": "header", "text": {"type": "plain_text", "text": headline}},
                {"type": "section", "text": {"type": "mrkdwn", "text": body}},
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": (
                                f"{report.platform.os_name} {report.platform.arch} · "
                                f"devrepro {report.devrepro_version}"
                            ),
                        }
                    ],
                },
            ],
        }

    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {
                            "type": "TextBlock",
                            "text": headline,
                            "weight": "Bolder",
                            "size": "Medium",
                            "wrap": True,
                            "color": (
                                "Attention"
                                if verdict == "BLOCKED"
                                else ("Warning" if verdict != "READY" else "Good")
                            ),
                        },
                        {"type": "TextBlock", "text": body, "wrap": True},
                        {
                            "type": "TextBlock",
                            "text": (
                                f"{report.platform.os_name} {report.platform.arch} · "
                                f"devrepro {report.devrepro_version}"
                            ),
                            "isSubtle": True,
                            "spacing": "Small",
                            "wrap": True,
                        },
                    ],
                },
            }
        ],
        # Kept out of the card because Adaptive Cards have no colour bar; the
        # hex is here for a caller assembling a different surface from the same
        # payload.
        "_devrepro": {"verdict": verdict, "colour": _COLOURS[verdict]},
    }
