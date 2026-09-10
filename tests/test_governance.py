"""Fleet analytics, team-scoped baselines, chat, MDM and the local monitor.

Five features whose common risk is not a bug but a category error: each is a
step from diagnostics toward something a person could reasonably object to.
Onboarding time is a process metric two lines of SQL away from a performance
review. An MDM script is a diagnostic two fields away from an inventory of
somebody's laptop. A chat bot is a webhook away from a token this project
holds. A monitor is one flag away from a daemon.

So most of these tests are about where each stops, and why.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from devrepro.core.models import (
    Evidence,
    Finding,
    FindingState,
    PlatformInfo,
    Policy,
    ScanReport,
)
from devrepro.drift.monitor import DEFAULT_INTERVAL_HOURS, render_schedule, should_snapshot
from devrepro.exporters.chat import MAX_LISTED, render_chat_payload
from devrepro.platforms.mdm import MDM_PLATFORMS, render_mdm_script
from devrepro.server.analytics import MINIMUM_COHORT, onboarding_stats, simulate_policy

HOUR = 3600.0


def machine(mid: int, enrolled: str) -> dict[str, object]:
    return {"id": mid, "created_at": enrolled}


def snap(mid: int, at: str, verdict: str, tools: dict[str, str] | None = None) -> dict[str, object]:
    return {"machine_id": mid, "created_at": at, "verdict": verdict, "tools": tools or {}}


def report(*findings: Finding) -> ScanReport:
    from datetime import UTC, datetime

    return ScanReport(
        schema_version="1.0",
        devrepro_version="0.2.0",
        created_at=datetime(2026, 6, 7, tzinfo=UTC),
        platform=PlatformInfo(os_name="Linux", os_version="1", arch="x86_64"),
        findings=findings,
    )


def finding(rule_id: str, state: FindingState = FindingState.BLOCKED) -> Finding:
    return Finding(
        rule_id=rule_id,
        state=state,
        summary="s",
        evidence=(Evidence(source="system", excerpt="e"),),
    )


# ==================================================== onboarding analytics


def test_onboarding_time_is_enrolment_to_first_ready() -> None:
    machines = [machine(i, "2026-01-01T00:00:00+00:00") for i in range(1, 7)]
    snapshots = [snap(i, f"2026-01-01T0{i}:00:00+00:00", "READY") for i in range(1, 7)]

    stats = onboarding_stats(machines, snapshots)

    assert stats.cohort == 6
    assert stats.median_hours is not None


def test_the_earliest_ready_wins_not_the_latest() -> None:
    """A machine that stayed ready is still onboarded at the first one."""
    machines = [machine(i, "2026-01-01T00:00:00+00:00") for i in range(1, 6)]
    snapshots = [
        *[snap(i, "2026-01-01T02:00:00+00:00", "READY") for i in range(1, 6)],
        *[snap(i, "2026-01-05T00:00:00+00:00", "READY") for i in range(1, 6)],
    ]

    assert onboarding_stats(machines, snapshots).median_hours == 2.0


def test_a_small_cohort_gets_no_distribution() -> None:
    """A percentile over four machines identifies individuals.

    That is the thing this refuses to be, and refusing it in code rather than
    in a docstring is the point: the query is two lines away for anybody who
    wants it, and the friction is where the decision belongs.
    """
    machines = [machine(i, "2026-01-01T00:00:00+00:00") for i in range(1, 4)]
    snapshots = [snap(i, "2026-01-01T01:00:00+00:00", "READY") for i in range(1, 4)]

    stats = onboarding_stats(machines, snapshots)

    assert stats.median_hours is None
    assert str(MINIMUM_COHORT) in (stats.withheld_because or "")


def test_no_machine_or_user_appears_in_the_output() -> None:
    """A process metric, not a performance one, in the payload as well as the prose."""
    machines = [machine(i, "2026-01-01T00:00:00+00:00") for i in range(1, 8)]
    snapshots = [snap(i, "2026-01-01T01:00:00+00:00", "READY") for i in range(1, 8)]

    payload = onboarding_stats(machines, snapshots).as_dict()

    # Structural, not a substring hunt: the scope paragraph legitimately says
    # the word "machine" while promising not to name one.
    assert set(payload) == {
        "cohort",
        "median_hours",
        "p90_hours",
        "never_ready",
        "withheld_because",
        "scope",
    }
    assert all(isinstance(v, (int, float, str, type(None))) for v in payload.values())
    assert "not a performance one" in payload["scope"]


def test_machines_that_never_became_ready_are_counted() -> None:
    """The number people most want and least expect.

    An onboarding metric computed only over successes hides everybody still
    stuck, which is the population the metric exists to find.
    """
    machines = [machine(i, "2026-01-01T00:00:00+00:00") for i in range(1, 9)]
    snapshots = [snap(i, "2026-01-01T01:00:00+00:00", "READY") for i in range(1, 6)]

    assert onboarding_stats(machines, snapshots).never_ready == 3


def test_the_median_is_used_rather_than_the_mean() -> None:
    """One machine that took three weeks because somebody was on holiday.

    It moves a mean and does not move a median, and a process metric a holiday
    can swing is one nobody trusts twice.
    """
    machines = [machine(i, "2026-01-01T00:00:00+00:00") for i in range(1, 7)]
    snapshots = [
        *[snap(i, "2026-01-01T01:00:00+00:00", "READY") for i in range(1, 6)],
        snap(6, "2026-01-22T00:00:00+00:00", "READY"),
    ]

    stats = onboarding_stats(machines, snapshots)

    assert stats.median_hours == 1.0
    # The outlier must reach the p90. `round` instead of `ceil` put it one rank
    # out of range and reported 1.0 here -- a tail metric excluding the tail.
    assert stats.p90_hours is not None
    assert stats.p90_hours > 100


# ===================================================== policy simulation


def test_a_policy_nobody_fails_is_reported_safe() -> None:
    policy = Policy(required_runtimes={"python": ">=3.11"})
    snapshots = [snap(i, "x", "READY", {"python": "3.12.0"}) for i in range(3)]

    result = simulate_policy(policy, snapshots)

    assert result.safe
    assert result.newly_failing == 0


def test_the_simulation_names_which_requirement_broke_them() -> None:
    """The count says how bad; this says which line of the policy to soften."""
    policy = Policy(required_runtimes={"python": ">=3.13"}, required_tools={"git": ">=2.45"})
    snapshots = [snap(i, "x", "READY", {"python": "3.11.0", "git": "2.46.0"}) for i in range(4)]

    result = simulate_policy(policy, snapshots)

    assert result.newly_failing == 4
    assert "python >=3.13" in result.causes


def test_an_absent_tool_is_distinguished_from_a_wrong_version() -> None:
    policy = Policy(required_tools={"pnpm": ">=9"})
    result = simulate_policy(policy, [snap(1, "x", "READY", {"npm": "10.0.0"})])
    assert "pnpm (absent)" in result.causes


def test_snapshots_with_no_tools_are_unevaluated_not_passing() -> None:
    """A simulation that quietly narrows its denominator under-reports the blast radius."""
    policy = Policy(required_runtimes={"python": ">=3.13"})
    result = simulate_policy(policy, [snap(1, "x", "READY", {}), snap(2, "x", "READY", {})])

    assert result.evaluated == 0
    assert result.unevaluated == 2


def test_an_unparseable_version_does_not_inflate_the_blast_radius() -> None:
    """Counting it as a failure gets a sensible policy rejected."""
    policy = Policy(required_runtimes={"python": ">=3.11"})
    result = simulate_policy(policy, [snap(1, "x", "READY", {"python": "unknown"})])
    assert result.newly_failing == 0


def test_the_simulation_says_its_data_may_be_stale() -> None:
    payload = simulate_policy(Policy(), []).as_dict()
    assert "may be old" in payload["caveat"]


# ================================================================= chat


def test_the_slack_payload_carries_a_notification_preview() -> None:
    """Block Kit does not fill the notification text; a `text` field must."""
    payload = render_chat_payload(report(finding("a/x")), platform="slack")
    assert payload["text"].startswith("devrepro:")
    assert payload["blocks"]


def test_the_teams_payload_is_an_adaptive_card() -> None:
    """Markdown posted into Teams renders as something that looks broken."""
    payload = render_chat_payload(report(), platform="teams")
    card = payload["attachments"][0]["content"]
    assert card["type"] == "AdaptiveCard"
    assert card["$schema"].startswith("http://adaptivecards.io/")


def test_blockers_are_named_and_capped() -> None:
    """A status message that scrolls is one people stop reading past line one."""
    many = report(*[finding(f"r/{i:02d}") for i in range(12)])
    body = render_chat_payload(many, platform="slack")["blocks"][1]["text"]["text"]

    assert body.count("•") == MAX_LISTED
    assert "and 7 more" in body


def test_a_clean_scan_says_so_rather_than_listing_nothing() -> None:
    body = render_chat_payload(report(), platform="slack")["blocks"][1]["text"]["text"]
    assert "No blockers" in body


def test_the_context_is_the_callers_and_never_guessed() -> None:
    """A message that guesses which repository it is about will be wrong in public."""
    payload = render_chat_payload(report(), platform="slack", context="acme/api@main")
    assert "acme/api@main" in payload["text"]

    plain = render_chat_payload(report(), platform="slack")
    assert "—" not in plain["text"]


def test_an_unknown_platform_is_refused() -> None:
    with pytest.raises(ValueError, match="teams"):
        render_chat_payload(report(), platform="irc")


def test_nothing_in_the_module_posts_anything() -> None:
    """A bot would need a token this project would have to hold and be trusted with."""
    source = (
        Path(__file__).resolve().parent.parent / "devrepro" / "exporters" / "chat.py"
    ).read_text(encoding="utf-8")
    for forbidden in ("urllib", "requests", "httpx", "socket"):
        assert forbidden not in source


# ================================================================== MDM


@pytest.mark.parametrize("platform", sorted(MDM_PLATFORMS))
def test_every_mdm_script_reports_a_verdict_and_nothing_else(platform: str) -> None:
    """Your MDM already knows the machine. What it does not know is buildability.

    Sending a toolchain inventory would put a developer's local software list
    in front of an audience it was not collected for.
    """
    _filename, script = render_mdm_script(platform)
    assert "preflight --json" in script
    assert "doctor --json" not in script
    assert "tools" not in script.lower().replace("toolchain", "")


@pytest.mark.parametrize("platform", sorted(MDM_PLATFORMS))
def test_an_absent_devrepro_reports_unknown_not_compliant(platform: str) -> None:
    """A check that reports success when it could not run is worse than a missing one."""
    _filename, script = render_mdm_script(platform)
    assert "UNKNOWN" in script


def test_the_filename_is_the_one_the_vendor_discovers() -> None:
    filename, _script = render_mdm_script("jamf")
    assert filename == MDM_PLATFORMS["jamf"][0]


def test_jamf_uses_its_result_wrapper_and_the_others_do_not() -> None:
    """A Jamf extension attribute is only read from inside `<result>` tags."""
    _f, jamf = render_mdm_script("jamf")
    _f2, kandji = render_mdm_script("kandji")
    assert "<result>" in jamf
    assert "<result>" not in kandji


def test_intune_emits_json_because_that_is_what_it_parses() -> None:
    _filename, script = render_mdm_script("intune")
    assert "ConvertTo-Json" in script


def test_an_unknown_mdm_is_refused_with_the_list() -> None:
    with pytest.raises(ValueError, match="kandji"):
        render_mdm_script("airwatch")


def test_no_mdm_script_changes_anything() -> None:
    """These run on every managed machine on somebody else's schedule.

    Checked against the commands rather than the prose: "install" appears
    inside "not installed", and a substring hunt over a file that explains
    itself finds the explanation.
    """
    mutating = ("devrepro fix", "Set-MpPreference", "rm -", "apt-get", "brew install")
    for platform in MDM_PLATFORMS:
        _f, script = render_mdm_script(platform)
        for forbidden in mutating:
            assert forbidden not in script


# ============================================================== monitor


def test_an_empty_history_takes_the_first_snapshot(tmp_path: Path) -> None:
    """Nobody takes one on a Tuesday, and one snapshot diffs against nothing."""
    decision = should_snapshot(tmp_path, now=1_000_000.0)
    assert decision.snapshot
    assert "No snapshot has ever been stored" in decision.reason


def test_a_recent_snapshot_means_nothing_to_do(tmp_path: Path) -> None:
    path = tmp_path / "a.json"
    path.write_text("{}", encoding="utf-8")
    import os

    os.utime(path, (1_000_000.0, 1_000_000.0))

    decision = should_snapshot(tmp_path, now=1_000_000.0 + 2 * HOUR)

    assert not decision.snapshot
    assert decision.hours_since_last == 2.0


def test_a_stale_history_takes_another(tmp_path: Path) -> None:
    import os

    path = tmp_path / "a.json"
    path.write_text("{}", encoding="utf-8")
    os.utime(path, (1_000_000.0, 1_000_000.0))

    assert should_snapshot(tmp_path, now=1_000_000.0 + 30 * HOUR).snapshot


def test_a_clock_that_moved_backwards_does_not_stall_the_monitor(tmp_path: Path) -> None:
    """A VM restored from a snapshot, or NTP finally starting.

    Treating a negative age as "recent" silently stops the monitor until the
    clock catches up, which can be days.
    """
    import os

    path = tmp_path / "a.json"
    path.write_text("{}", encoding="utf-8")
    os.utime(path, (2_000_000.0, 2_000_000.0))

    decision = should_snapshot(tmp_path, now=1_000_000.0)

    assert decision.snapshot
    assert "moved backwards" in decision.reason


def test_the_chain_file_is_not_mistaken_for_a_snapshot(tmp_path: Path) -> None:
    (tmp_path / "chain.jsonl").write_text("{}", encoding="utf-8")
    assert should_snapshot(tmp_path, now=1_000_000.0).snapshot


def test_the_decision_always_says_why(tmp_path: Path) -> None:
    """This runs unattended: "it did nothing" and "it is broken" look identical."""
    assert should_snapshot(tmp_path, now=1.0).reason.strip()


@pytest.mark.parametrize("platform", ["cron", "windows", "macos"])
def test_the_schedule_is_printed_with_its_removal_instructions(platform: str) -> None:
    """A persistent change to a machine is not something a diagnostic installs."""
    entry = render_schedule(platform=platform)
    assert "emove" in entry  # "Remove with" / "remove by"
    # Each platform spells the invocation its own way -- argv array, cron line,
    # PowerShell arguments -- so the check is that both words are there.
    assert "devrepro" in entry
    assert "monitor" in entry


def test_the_default_interval_is_a_day() -> None:
    """Hourly snapshots fill a history directory with rows that all say the same thing."""
    assert DEFAULT_INTERVAL_HOURS == 24.0
