"""Advisories against the toolchain itself, and the two ways this can lie.

Dependency scanners never look at the compiler, because a compiler appears in
no lockfile. So a project can pass `npm audit` cleanly and be built by a `git`
old enough that cloning a repository runs code from it.

Two failure modes matter more than coverage:

**Branch-blind comparison.** A fix released as 2.45.1, 2.44.1 and 2.43.4 means
2.44.0 is affected and 2.44.1 is not. Comparing against the highest number
gets that exactly backwards, and the wrong answer looks entirely reasonable.

**Silence read as coverage.** An offline set that has no data for a tool
produced no answer. Every path here has to keep that distinct from a clean
result, or the feature actively misleads.
"""

from __future__ import annotations

import json
from pathlib import Path  # noqa: TC003 -- pytest resolves fixture annotations

import pytest
from devrepro.compliance.advisories import (
    BUNDLE_SCHEMA_VERSION,
    BUNDLED_ADVISORIES,
    Advisory,
    AdvisoryBundle,
    AdvisoryError,
    affected_tools,
    bundled_bundle,
    is_affected,
    load_bundle,
    parse_bundle,
)
from devrepro.snapshots.signing import sign_bytes

KEY = b"a-test-key"

BACKPORTED = Advisory(
    id="TEST-1",
    tool="git",
    summary="s",
    fixed=("2.45.1", "2.44.1", "2.43.4"),
    reference="https://example.invalid/1",
)

SINGLE = Advisory(
    id="TEST-2",
    tool="openssl",
    summary="s",
    fixed=("3.0.7",),
    introduced="3.0.0",
    reference="https://example.invalid/2",
)


def bundle(*advisories: Advisory) -> AdvisoryBundle:
    return AdvisoryBundle(
        published="2026-01-01",
        source="test",
        advisories=advisories,
        covers=tuple(sorted({a.tool for a in advisories})),
    )


# ------------------------------------------------------------------ matching


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("2.44.0", True),
        ("2.44.1", False),
        ("2.44.2", False),
        ("2.43.3", True),
        ("2.43.4", False),
        ("2.45.0", True),
        ("2.45.1", False),
    ],
)
def test_a_backported_fix_is_matched_on_the_right_branch(version: str, expected: bool) -> None:
    """The whole reason `fixed` is a tuple.

    2.44.1 carries the fix and 2.45.0 does not, even though 2.45.0 is the
    larger number. A single "fixed in" value cannot express that, and the
    version that gets it wrong is the one people are actually running.
    """
    assert is_affected(version, BACKPORTED) is expected


def test_a_version_newer_than_every_listed_fix_is_clear() -> None:
    assert is_affected("2.50.0", BACKPORTED) is False


def test_a_version_on_an_unlisted_old_branch_is_reported() -> None:
    """The documented failure mode, held in place.

    2.30 never received this fix and has no entry, so it compares against the
    highest one and comes back affected. That is usually correct and it is the
    safe direction for a warning -- which is why nothing built on this blocks.
    """
    assert is_affected("2.30.0", BACKPORTED) is True


def test_a_version_below_the_introduction_is_not_affected() -> None:
    """1.1.1 predates the 3.0 punycode code entirely."""
    assert is_affected("1.1.1w", SINGLE) is False
    assert is_affected("3.0.2", SINGLE) is True


def test_an_advisory_with_no_fix_matches_nothing() -> None:
    assert is_affected("1.0.0", Advisory("X", "t", "s", (), "https://example.invalid/x")) is False


def test_an_unparseable_version_is_not_a_match() -> None:
    """Tools report "unknown" and worse; none of it should end a scan."""
    assert is_affected("not a version", BACKPORTED) is False


def test_a_tool_with_no_version_is_skipped_not_guessed() -> None:
    """ "Installed, and I could not tell you which" is not an input to a comparison."""
    assert affected_tools({"git": None}, bundle(BACKPORTED)) == ()


def test_matches_carry_the_tool_the_version_and_the_advisory() -> None:
    hits = affected_tools({"git": "2.44.0", "openssl": "3.0.2"}, bundle(BACKPORTED, SINGLE))
    assert [(name, version, adv.id) for name, version, adv in hits] == [
        ("git", "2.44.0", "TEST-1"),
        ("openssl", "3.0.2", "TEST-2"),
    ]


# -------------------------------------------------------------------- silence


def test_coverage_is_recorded_separately_from_results() -> None:
    """A tool outside `covers` got no answer, and that is not a clean one."""
    active = bundle(BACKPORTED)
    assert active.covers == ("git",)
    assert affected_tools({"node": "18.0.0"}, active) == ()


def test_the_bundled_set_says_when_it_was_reviewed() -> None:
    """An offline database's most important property is its age."""
    shipped = bundled_bundle()
    assert shipped.published
    assert shipped.covers


def test_every_bundled_advisory_can_be_checked_by_a_reader() -> None:
    """An advisory database that cannot be verified is a rumour."""
    for advisory in BUNDLED_ADVISORIES:
        assert advisory.reference.startswith("https://")
        assert advisory.fixed
        assert advisory.summary.strip()


# --------------------------------------------------------------------- trust


def write_bundle(path: Path, advisories: list[dict[str, object]]) -> bytes:
    payload = json.dumps(
        {
            "schema_version": BUNDLE_SCHEMA_VERSION,
            "published": "2026-02-02",
            "advisories": advisories,
        }
    ).encode("utf-8")
    path.write_bytes(payload)
    return payload


def entry(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "EXT-1",
        "tool": "node",
        "summary": "s",
        "fixed": ["20.11.1"],
        "reference": "https://example.invalid/n",
    }
    base.update(overrides)
    return base


def test_the_bundled_set_loads_without_a_key() -> None:
    assert load_bundle(None).source == "bundled"


def test_an_unsigned_external_bundle_is_refused(tmp_path: Path) -> None:
    """The interesting attack is not adding a false entry but removing a true one."""
    path = tmp_path / "advisories.json"
    write_bundle(path, [entry()])

    with pytest.raises(AdvisoryError, match=r"no advisories\.json\.sig"):
        load_bundle(path)


def test_an_unsigned_bundle_loads_when_the_caller_says_so(tmp_path: Path) -> None:
    path = tmp_path / "advisories.json"
    write_bundle(path, [entry()])

    loaded = load_bundle(path, trust_unsigned=True)

    assert loaded.signed is False
    assert loaded.source == "advisories.json"


def test_a_signed_bundle_verifies(tmp_path: Path) -> None:
    path = tmp_path / "advisories.json"
    raw = write_bundle(path, [entry()])
    (tmp_path / "advisories.json.sig").write_text(sign_bytes(raw, KEY), encoding="utf-8")

    loaded = load_bundle(path, key=KEY)

    assert loaded.signed is True
    assert [a.id for a in loaded.advisories] == ["EXT-1"]


def test_a_tampered_bundle_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "advisories.json"
    raw = write_bundle(path, [entry()])
    (tmp_path / "advisories.json.sig").write_text(sign_bytes(raw, KEY), encoding="utf-8")
    write_bundle(path, [])  # the removal that would otherwise be invisible

    with pytest.raises(AdvisoryError, match="signature does not match"):
        load_bundle(path, key=KEY)


def test_a_signed_bundle_with_no_key_is_refused_rather_than_trusted(tmp_path: Path) -> None:
    path = tmp_path / "advisories.json"
    raw = write_bundle(path, [entry()])
    (tmp_path / "advisories.json.sig").write_text(sign_bytes(raw, KEY), encoding="utf-8")

    with pytest.raises(AdvisoryError, match="DEVREPRO_ADVISORY_KEY"):
        load_bundle(path)


# -------------------------------------------------------------------- parsing


def test_a_future_schema_is_refused_rather_than_read_partially() -> None:
    with pytest.raises(AdvisoryError, match="schema"):
        parse_bundle({"schema_version": "2.0", "advisories": []}, source="x", signed=True)


def test_a_malformed_entry_fails_loudly_instead_of_being_skipped() -> None:
    """A silently dropped advisory is one that stops being reported unnoticed."""
    with pytest.raises(AdvisoryError, match="#0"):
        parse_bundle(
            {"schema_version": BUNDLE_SCHEMA_VERSION, "advisories": [{"id": "x"}]},
            source="x",
            signed=True,
        )


def test_a_bundle_with_no_advisories_list_is_refused() -> None:
    with pytest.raises(AdvisoryError, match="advisories"):
        parse_bundle({"schema_version": BUNDLE_SCHEMA_VERSION}, source="x", signed=True)


def test_covers_defaults_to_the_tools_present() -> None:
    parsed = parse_bundle(
        {
            "schema_version": BUNDLE_SCHEMA_VERSION,
            "advisories": [entry(), entry(id="EXT-2", tool="git")],
        },
        source="x",
        signed=True,
    )
    assert parsed.covers == ("git", "node")


# ----------------------------------------------------------------- rule pack


def test_the_rule_pack_reports_its_coverage_even_when_nothing_matched() -> None:
    """Silence has to appear in the report, or it reads as a clean result."""
    from devrepro.core.models import PlatformInfo, ToolInstallation
    from devrepro.rules.base import RuleContext
    from devrepro.rules.packs.advisories import evaluate

    ctx = RuleContext(
        platform_info=PlatformInfo(os_name="Linux", os_version="1", arch="x86_64"),
        tools=(ToolInstallation(name="node", version="20.0.0", is_active=True),),
    )

    findings = evaluate(ctx, bundle(BACKPORTED))

    assert [f.rule_id for f in findings] == ["advisories/coverage"]
    assert "git" in findings[0].summary


def test_a_match_is_a_warning_and_never_a_block() -> None:
    """The branch fallback errs toward reporting; a loud-when-wrong check must not gate."""
    from devrepro.core.models import FindingState, PlatformInfo, ToolInstallation
    from devrepro.rules.base import RuleContext
    from devrepro.rules.packs.advisories import evaluate

    ctx = RuleContext(
        platform_info=PlatformInfo(os_name="Linux", os_version="1", arch="x86_64"),
        tools=(ToolInstallation(name="git", version="2.44.0", is_active=True),),
    )

    findings = evaluate(ctx, bundle(BACKPORTED))
    match = next(f for f in findings if f.rule_id == "git/known-advisory")

    assert match.state is FindingState.WARN
    assert match.detected == "2.44.0"
    assert "2.45.1" in (match.required or "")
    assert "backported" in (match.remediation_hint or "")
