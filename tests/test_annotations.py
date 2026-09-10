"""Findings as GitHub annotations, and the anchor this must not invent.

SARIF already ships and is the better format, but uploading it from a private
repository needs GitHub Advanced Security, which most teams do not have.
Workflow commands cost nothing and work on every plan.

The interesting problem is not rendering. It is that **a machine scan produces
findings that are not about any file**. `docker/daemon-not-running` has no
line in the diff, and the tempting implementation anchors it to line 1 of
something so the API stops complaining. That puts "Docker is not running" on a
line of somebody's source, which is how a reviewer learns to ignore every
annotation in the run. Most of the tests here are about that boundary, and
about the escaping rules, which are GitHub's own and are not URL encoding.
"""

from __future__ import annotations

from datetime import UTC, datetime

from devrepro.core.models import Evidence, Finding, FindingState, PlatformInfo, ScanReport
from devrepro.reports.annotations import (
    annotations_for,
    render_check_run,
    render_workflow_commands,
)


def finding(
    rule_id: str = "x/y",
    state: FindingState = FindingState.WARN,
    *,
    path: str | None = None,
    summary: str = "something happened",
    hint: str | None = None,
) -> Finding:
    return Finding(
        rule_id=rule_id,
        state=state,
        summary=summary,
        evidence=(Evidence(source="file" if path else "system", path=path, excerpt="e"),),
        remediation_hint=hint,
    )


def report(*findings: Finding) -> ScanReport:
    return ScanReport(
        schema_version="1.0",
        devrepro_version="0.2.0",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        platform=PlatformInfo(os_name="Linux", os_version="6.8.0", arch="x86_64"),
        findings=findings,
    )


# ------------------------------------------------------------------ anchoring


def test_a_finding_about_a_repository_file_is_anchored() -> None:
    annotations = annotations_for(report(finding(path="web/package.json")))
    assert annotations[0].path == "web/package.json"
    assert annotations[0].anchored


def test_a_machine_finding_is_not_anchored_to_anything() -> None:
    """The whole point. A stopped daemon is not a property of a line of code."""
    annotations = annotations_for(report(finding("docker/daemon-not-running")))
    assert annotations[0].path is None
    assert not annotations[0].anchored


def test_an_absolute_path_is_not_used_as_an_anchor() -> None:
    """`/usr/bin/python3` is a real path and not a line in anybody's diff."""
    assert annotations_for(report(finding(path="/usr/bin/python3")))[0].path is None


def test_a_windows_home_path_is_not_leaked_into_a_pull_request() -> None:
    """It would also be meaningless as an anchor, but the leak is the worse half."""
    annotations = annotations_for(report(finding(path="C:\\Users\\someone\\.nvm\\node")))
    assert annotations[0].path is None


def test_a_windows_relative_path_is_normalised() -> None:
    assert annotations_for(report(finding(path="web\\src\\x.ts")))[0].path == "web/src/x.ts"


# --------------------------------------------------------------------- levels


def test_only_blocking_states_render_as_failures() -> None:
    """A red annotation on an INFO finding teaches people to ignore red ones."""
    annotations = annotations_for(
        report(
            finding("a/blocked", FindingState.BLOCKED),
            finding("b/error", FindingState.ERROR),
            finding("c/warn", FindingState.WARN),
            finding("d/info", FindingState.INFO),
            finding("e/unknown", FindingState.UNKNOWN),
        )
    )
    assert [a.level for a in annotations] == [
        "failure",
        "failure",
        "warning",
        "notice",
        "notice",
    ]


def test_passing_findings_are_not_annotated() -> None:
    assert annotations_for(report(finding("a/ok", FindingState.PASS))) == ()


def test_the_worst_findings_come_first() -> None:
    """The cap bites from the bottom, so ordering decides what survives it."""
    annotations = annotations_for(
        report(finding("z/info", FindingState.INFO), finding("a/blocked", FindingState.BLOCKED))
    )
    assert [a.title for a in annotations] == ["a/blocked", "z/info"]


def test_the_remediation_hint_travels_with_the_message() -> None:
    annotations = annotations_for(report(finding(hint="do the thing")))
    assert "do the thing" in annotations[0].message


# ------------------------------------------------------------------- escaping


def test_a_message_keeps_its_colons_and_commas() -> None:
    """Reusing the property escaper here renders `%3A` to the reader."""
    rendered = render_workflow_commands(report(finding(summary="found: a, b")))
    assert "found: a, b" in rendered


def test_a_newline_in_a_message_is_escaped_not_emitted() -> None:
    """A raw newline ends the workflow command and drops the rest of the message."""
    rendered = render_workflow_commands(report(finding(hint="line two")))
    assert "\n" not in rendered.rstrip("\n")
    assert "%0A" in rendered


def test_a_colon_in_a_property_is_escaped() -> None:
    """An unescaped colon truncates the command at that point, silently."""
    rendered = render_workflow_commands(report(finding("a:b/c", path="x.json")))
    assert "title=a%3Ab/c" in rendered


def test_a_percent_is_escaped_first() -> None:
    """Escaping `%` after the others would double-escape what they produced."""
    rendered = render_workflow_commands(report(finding(summary="100% done")))
    assert "100%25 done" in rendered


def test_an_unanchored_annotation_carries_no_file_property() -> None:
    rendered = render_workflow_commands(report(finding("docker/down")))
    assert "file=" not in rendered
    assert rendered.startswith("::warning title=docker/down::")


def test_an_empty_report_renders_nothing_rather_than_a_blank_line() -> None:
    assert render_workflow_commands(report()) == ""


# ---------------------------------------------------------------- truncation


def test_the_cap_is_reported_rather_than_applied_silently() -> None:
    """GitHub stops rendering past the cap, so a truncated list reads as complete."""
    many = report(*[finding(f"rule/{i:02d}") for i in range(15)])

    rendered = render_workflow_commands(many, limit=10)

    warnings = [line for line in rendered.splitlines() if line.startswith("::warning")]
    assert len(warnings) == 10
    assert "5 further warning finding(s) were not annotated" in rendered


def test_the_cap_is_per_level_not_overall() -> None:
    mixed = report(
        *[finding(f"w/{i:02d}", FindingState.WARN) for i in range(4)],
        *[finding(f"n/{i:02d}", FindingState.INFO) for i in range(4)],
    )
    rendered = render_workflow_commands(mixed, limit=3)
    assert rendered.count("::warning") == 3
    # Three notices, plus the two lines announcing what was dropped.
    assert rendered.count("::notice") == 5


# ------------------------------------------------------------------ check run


def test_the_check_run_annotates_only_what_it_can_honestly_anchor() -> None:
    payload = render_check_run(
        report(finding("a/file", path="pyproject.toml"), finding("b/machine"))
    )
    annotations = payload["output"]["annotations"]
    assert [a["path"] for a in annotations] == ["pyproject.toml"]
    assert "b/machine" in payload["output"]["text"]


def test_machine_findings_are_explained_rather_than_dropped() -> None:
    payload = render_check_run(report(finding("docker/down")))
    text = payload["output"]["text"]
    assert "Machine state" in text
    assert "not of any file in the diff" in text


def test_a_blocking_finding_fails_the_check() -> None:
    payload = render_check_run(report(finding("a/x", FindingState.BLOCKED)))
    assert payload["conclusion"] == "failure"


def test_warnings_are_neutral_not_failures() -> None:
    payload = render_check_run(report(finding("a/x", FindingState.WARN)))
    assert payload["conclusion"] == "neutral"


def test_a_clean_report_succeeds() -> None:
    assert render_check_run(report())["conclusion"] == "success"


def test_the_fifty_annotation_limit_is_stated_in_the_summary() -> None:
    """Paginating silently would mean the check says less than it found."""
    many = report(*[finding(f"r/{i:03d}", path=f"f{i}.json") for i in range(60)])

    payload = render_check_run(many)

    assert len(payload["output"]["annotations"]) == 50
    assert "10 further file-anchored finding(s)" in payload["output"]["summary"]
