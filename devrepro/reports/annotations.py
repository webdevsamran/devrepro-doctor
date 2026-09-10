"""Findings as GitHub annotations, for the repositories SARIF cannot reach.

`devrepro scan --format sarif` already exists, and SARIF is the better format:
richer, standardised, and it feeds the security tab. It also requires GitHub
Advanced Security to upload from a private repository, which most teams reading
this do not have. The result is a feature that works beautifully in the demo
and does nothing in the place it was needed.

Workflow commands cost nothing and work everywhere. Writing
`::warning file=x,line=1::msg` to stdout puts the message on the pull request's
diff, on any plan, with no token and no upload step.

**Most findings do not belong on a line of a diff, and that is the hard part.**
This tool scans a machine. `docker/daemon-not-running` is not a property of any
file, and a naive implementation anchors it to line 1 of whatever file it can
find -- which is how annotation features become the thing everybody turns off.
So a finding is only anchored when its own evidence names a path; everything
else is emitted without a file, which GitHub renders against the workflow run
rather than the diff.

The truncation is reported rather than silent. GitHub stops rendering after ten
annotations of a level from one step, and a tool that quietly drops the
eleventh has told the reader the machine has ten problems.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from devrepro.core.models import FindingState

if TYPE_CHECKING:
    from collections.abc import Iterable

    from devrepro.core.models import Finding, ScanReport

__all__ = [
    "ANNOTATIONS_PER_LEVEL",
    "Annotation",
    "annotations_for",
    "render_check_run",
    "render_workflow_commands",
]

#: GitHub renders at most this many annotations per level from a single step.
#: Beyond it the commands are accepted and never shown, which is worse than an
#: error: the output looks complete.
ANNOTATIONS_PER_LEVEL = 10

AnnotationLevel = Literal["notice", "warning", "failure"]

#: Findings map onto three levels, not six. `failure` is reserved for states
#: that genuinely stop a build, because a red annotation on an INFO finding
#: teaches people to ignore red annotations.
_LEVELS: dict[FindingState, AnnotationLevel] = {
    FindingState.BLOCKED: "failure",
    FindingState.ERROR: "failure",
    FindingState.WARN: "warning",
    FindingState.INFO: "notice",
    FindingState.UNKNOWN: "notice",
}


@dataclass(frozen=True)
class Annotation:
    """One rendered annotation, anchored to a file only when a file is known."""

    level: AnnotationLevel
    title: str
    message: str
    path: str | None = None
    line: int | None = None

    @property
    def anchored(self) -> bool:
        return self.path is not None


def _escape_property(value: str) -> str:
    """Escape a workflow-command property value.

    GitHub's own escaping rules, which are not URL encoding and not shell
    quoting: percent, carriage return, newline, colon and comma each have a
    percent escape, and a colon in an unescaped property silently truncates the
    command at that point.
    """
    return (
        value.replace("%", "%25")
        .replace("\r", "%0D")
        .replace("\n", "%0A")
        .replace(":", "%3A")
        .replace(",", "%2C")
    )


def _escape_message(value: str) -> str:
    """Escape a workflow-command message body.

    Only the three characters that would end or confuse the command. Colons and
    commas are ordinary text here, and escaping them -- the mistake made by
    reusing the property escaper -- renders `%3A` to the reader.
    """
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _path_for(finding: Finding) -> str | None:
    r"""The file this finding is genuinely about, or `None`.

    Only paths that look repository-relative are used. An evidence path may be
    `/usr/bin/python3` or `C:\\Users\\someone\\.nvm`, and annotating a diff with
    a line number inside somebody's home directory is both meaningless and a
    privacy leak into a public pull request.
    """
    for evidence in finding.evidence:
        path = evidence.path
        if not path:
            continue
        if path.startswith(("/", "~")) or (len(path) > 1 and path[1] == ":"):
            continue
        return path.replace("\\", "/")
    return None


def annotations_for(report: ScanReport) -> tuple[Annotation, ...]:
    """Every finding as an annotation, most severe first.

    Ordered by severity because the cap bites from the bottom: if only ten
    survive, they should be the ten worth reading.
    """
    order = {
        FindingState.BLOCKED: 0,
        FindingState.ERROR: 1,
        FindingState.WARN: 2,
        FindingState.INFO: 3,
        FindingState.UNKNOWN: 4,
    }
    interesting = [f for f in report.findings if f.state is not FindingState.PASS]
    interesting.sort(key=lambda f: (order.get(f.state, 9), f.rule_id))

    built: list[Annotation] = []
    for finding in interesting:
        detail = finding.summary
        if finding.remediation_hint:
            detail = f"{detail}\n\n{finding.remediation_hint}"
        built.append(
            Annotation(
                level=_LEVELS.get(finding.state, "notice"),
                title=finding.rule_id,
                message=detail,
                path=_path_for(finding),
            )
        )
    return tuple(built)


def _capped(
    annotations: Iterable[Annotation], limit: int
) -> tuple[list[Annotation], dict[str, int]]:
    kept: list[Annotation] = []
    seen: dict[str, int] = {}
    dropped: dict[str, int] = {}
    for annotation in annotations:
        seen[annotation.level] = seen.get(annotation.level, 0) + 1
        if seen[annotation.level] <= limit:
            kept.append(annotation)
        else:
            dropped[annotation.level] = dropped.get(annotation.level, 0) + 1
    return kept, dropped


def render_workflow_commands(report: ScanReport, *, limit: int = ANNOTATIONS_PER_LEVEL) -> str:
    """Workflow commands for a GitHub Actions step, one per line.

    Written to stdout inside a job; GitHub reads them from the log. Nothing is
    uploaded and no token is needed, which is the entire reason this exists
    alongside SARIF.
    """
    kept, dropped = _capped(annotations_for(report), limit)
    lines: list[str] = []
    for annotation in kept:
        properties = [f"title={_escape_property(annotation.title)}"]
        if annotation.path:
            properties.insert(0, f"file={_escape_property(annotation.path)}")
            if annotation.line is not None:
                properties.insert(1, f"line={annotation.line}")
        lines.append(
            f"::{annotation.level} {','.join(properties)}::{_escape_message(annotation.message)}"
        )

    for level, count in sorted(dropped.items()):
        # Said out loud, in the log, because GitHub silently stops rendering
        # past the cap and a truncated list reads as a complete one.
        lines.append(
            f"::notice title=devrepro::{count} further {level} finding(s) were not "
            f"annotated; GitHub renders at most {limit} per level per step. "
            "Run `devrepro doctor` or read the JSON report for the full list."
        )
    return "\n".join(lines) + ("\n" if lines else "")


def render_check_run(report: ScanReport, *, name: str = "devrepro") -> dict[str, Any]:
    """A Check Run payload, for a caller that holds a token and wants to POST it.

    Built, never sent. Posting means authenticating as an app or with a token
    that can write checks, and a diagnostic command acquiring that is a
    different product. The payload is handed over for `gh api` or an existing
    action to deliver.

    **Only anchored findings become annotations.** The Check Run API requires a
    `path` and a `start_line` on every one, and the tempting move is to invent
    them -- point the machine-state findings at line 1 of some file and let the
    API be happy. That puts "Docker is not running" on a line of somebody's
    source code, which is how a reviewer learns to distrust every annotation in
    the run. The unanchored findings go into `output.text` instead, where they
    read as what they are: facts about the machine, not about the diff.
    """
    annotations = annotations_for(report)
    anchored = [a for a in annotations if a.anchored]
    unanchored = [a for a in annotations if not a.anchored]

    levels = {a.level for a in annotations}
    conclusion = (
        "failure" if "failure" in levels else ("neutral" if "warning" in levels else "success")
    )
    counts: dict[str, int] = {}
    for annotation in annotations:
        counts[annotation.level] = counts.get(annotation.level, 0) + 1

    # The API takes 50 annotations per request and expects the rest in
    # follow-up updates. One request is built, and the remainder is stated
    # rather than paginated silently.
    head = anchored[:50]
    summary = (
        f"{counts.get('failure', 0)} blocking, {counts.get('warning', 0)} warning, "
        f"{counts.get('notice', 0)} informational."
    )
    if len(anchored) > len(head):
        summary += (
            f" {len(anchored) - len(head)} further file-anchored finding(s) are not "
            "in this payload; the Check Run API takes 50 per request."
        )

    text_lines: list[str] = []
    if unanchored:
        text_lines.append("### Machine state")
        text_lines.append("")
        text_lines.append(
            "These are properties of the machine this ran on, not of any file in "
            "the diff, so they are listed rather than annotated."
        )
        text_lines.append("")
        text_lines.extend(f"- **{a.title}** — {a.message.splitlines()[0]}" for a in unanchored)

    return {
        "name": name,
        "status": "completed",
        "conclusion": conclusion,
        "output": {
            "title": f"devrepro: {conclusion}",
            "summary": summary,
            "text": "\n".join(text_lines),
            "annotations": [
                {
                    "path": a.path,
                    "start_line": a.line or 1,
                    "end_line": a.line or 1,
                    "annotation_level": a.level,
                    "title": a.title,
                    "message": a.message,
                }
                for a in head
            ],
        },
    }
