"""Control mapping and toolchain licenses: two documents that must not overclaim.

Both of these get printed and attached to a ticket, which means both get read
by somebody who did not run the scan and cannot check it. That reader is the
whole design constraint.

For controls, the failure is a green row. A compliance export that reports
coverage across a framework hands somebody a document that is wrong, and the
harm is worse than having shipped nothing. So the tests here spend most of
their effort on the negative space: out-of-scope controls carry a reason, an
absent source produces `not-evidenced` rather than a pass, and the scope
statement is present in the payload rather than in a docstring nobody exports.

For licenses, the failure is the opposite: a table that says `GPL-3.0` next to
a compiler and stops there, frightening a legal team over a build tool that
creates no obligation at all. Every row carries what it actually requires.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from devrepro.compliance.controls import (
    CONTROLS,
    build_evidence_pack,
    controls_for_framework,
    frameworks,
)
from devrepro.compliance.licenses import TOOL_LICENSES, license_for, toolchain_licenses
from devrepro.core.models import (
    ContainerState,
    Evidence,
    Finding,
    FindingState,
    PlatformInfo,
    ProjectRequirement,
    RequirementKind,
    ScanReport,
    ToolInstallation,
)


def tool(name: str, version: str | None = "1.0.0", *, active: bool = True) -> ToolInstallation:
    return ToolInstallation(name=name, version=version, is_active=active)


def report(
    *,
    tools: list[ToolInstallation] | None = None,
    findings: list[Finding] | None = None,
    requirements: list[ProjectRequirement] | None = None,
    containers: ContainerState | None = None,
) -> ScanReport:
    return ScanReport(
        schema_version="1.0",
        devrepro_version="0.2.0",
        created_at=datetime(2026, 5, 6, tzinfo=UTC),
        platform=PlatformInfo(os_name="Linux", os_version="6.8.0", arch="x86_64"),
        tools=tuple(tools or []),
        findings=tuple(findings or []),
        requirements=tuple(requirements or []),
        containers=containers,
    )


def a_finding() -> Finding:
    return Finding(
        rule_id="x/y",
        state=FindingState.WARN,
        summary="s",
        evidence=(Evidence(source="system", excerpt="e"),),
    )


def a_requirement() -> ProjectRequirement:
    return ProjectRequirement(
        ecosystem="python",
        name="python",
        spec=">=3.11",
        kind=RequirementKind.RUNTIME,
        source_file="pyproject.toml",
    )


# ---------------------------------------------------------------- the mapping


def test_every_control_is_either_evidenced_or_explained() -> None:
    """An unexplained gap in a compliance table reads as an oversight."""
    for control in CONTROLS:
        if control.source is None:
            assert control.out_of_scope_because, f"{control.id} declines without saying why"
        else:
            assert control.evidence, f"{control.id} claims a source and describes no evidence"


def test_the_frameworks_are_the_ones_the_cli_offers() -> None:
    assert set(frameworks()) == {"cra", "ssdf", "slsa"}
    for name in frameworks():
        assert controls_for_framework(name)


def test_control_ids_are_unique() -> None:
    ids = [c.id for c in CONTROLS]
    assert len(ids) == len(set(ids))


def test_an_absent_source_is_not_evidenced_rather_than_a_pass() -> None:
    """The reason to run this at all.

    A pack that reports the same thing regardless of what the scan found is a
    template. An empty `requirements` means the project declared nothing, and
    that is the opposite of evidence for it.
    """
    pack = build_evidence_pack(report(), framework="ssdf")
    row = next(r for r in pack["controls"] if r["id"] == "SSDF/PO.3.1")
    assert row["status"] == "not-evidenced"


def test_a_populated_source_is_evidenced_and_counted() -> None:
    pack = build_evidence_pack(
        report(requirements=[a_requirement()]),
        framework="ssdf",
    )
    row = next(r for r in pack["controls"] if r["id"] == "SSDF/PO.3.1")
    assert row["status"] == "evidenced"
    assert "1 record" in row["detail"]


def test_findings_count_toward_the_controls_that_name_them() -> None:
    pack = build_evidence_pack(report(findings=[a_finding()]), framework="cra")
    row = next(r for r in pack["controls"] if r["id"] == "CRA/AnnexI.I.2.a")
    assert row["status"] == "evidenced"


def test_an_out_of_scope_control_carries_its_reason_into_the_export() -> None:
    """The reason has to be in the file, not in the source of the tool that made it."""
    pack = build_evidence_pack(report(), framework="cra")
    row = next(r for r in pack["controls"] if r["id"] == "CRA/Art.14")
    assert row["status"] == "out-of-scope"
    assert "CSIRT" in row["outOfScopeBecause"]


def test_slsa_level_two_is_declined_rather_than_claimed() -> None:
    """Provenance written by the machine that ran the build cannot satisfy L2."""
    pack = build_evidence_pack(report(), framework="slsa")
    row = next(r for r in pack["controls"] if r["id"] == "SLSA/Build.L2")
    assert row["status"] == "out-of-scope"


def test_the_scope_statement_travels_with_the_document() -> None:
    """The likeliest harm is this being read as a conformance report."""
    pack = build_evidence_pack(report())
    assert "not a conformance assessment" in pack["scope"]
    assert "out-of-scope" in pack["scope"]


def test_the_summary_counts_every_status() -> None:
    pack = build_evidence_pack(report())
    assert sum(pack["summary"].values()) == len(pack["controls"])


def test_selecting_one_framework_excludes_the_others() -> None:
    pack = build_evidence_pack(report(), framework="slsa")
    assert pack["frameworks"] == ["slsa"]
    assert {r["framework"] for r in pack["controls"]} == {"slsa"}


def test_a_container_state_evidences_environment_separation() -> None:
    pack = build_evidence_pack(
        report(containers=ContainerState(docker_cli_version="27.0.0", docker_daemon_ok=True)),
        framework="ssdf",
    )
    row = next(r for r in pack["controls"] if r["id"] == "SSDF/PO.5.1")
    assert row["status"] == "evidenced"


# --------------------------------------------------------------------- licenses


def test_the_gpl_toolchain_rows_say_that_building_creates_no_obligation() -> None:
    """The sentence that stops this table being frightening and useless.

    GCC's Runtime Library Exception exists precisely so that compiling with it
    does not place the output under the GPL. A row that shows the identifier
    and omits the exception has told a legal team the wrong thing.
    """
    gcc = license_for("gcc")
    assert gcc is not None
    assert gcc.obligation == "none"
    assert "Exception" in gcc.note

    git = license_for("git")
    assert git is not None
    assert git.obligation == "redistribution-only"


def test_a_tool_that_needs_a_human_is_marked_for_review() -> None:
    """An OpenJDK build and an Oracle JDK are not the same license question."""
    java = license_for("java")
    assert java is not None
    assert java.obligation == "review"


def test_an_unknown_tool_is_not_guessed() -> None:
    """The only property that makes an inventory worth having."""
    assert license_for("some-internal-tool") is None


def test_unknown_tools_are_listed_rather_than_dropped() -> None:
    inventory = toolchain_licenses(report(tools=[tool("python"), tool("some-internal-tool")]))
    assert [row["tool"] for row in inventory["tools"]] == ["python"]
    assert inventory["unknown"] == ["some-internal-tool"]


def test_only_the_active_installation_is_inventoried() -> None:
    """A report listing every python on the disk describes the disk."""
    inventory = toolchain_licenses(
        report(tools=[tool("python", "3.12.1"), tool("python", "3.9.0", active=False)])
    )
    assert [row["version"] for row in inventory["tools"]] == ["3.12.1"]


def test_obligations_present_summarises_what_needs_attention() -> None:
    inventory = toolchain_licenses(report(tools=[tool("git"), tool("go"), tool("java")]))
    assert inventory["obligations_present"] == ["redistribution-only", "review"]


def test_a_permissive_only_toolchain_reports_nothing_to_attend_to() -> None:
    inventory = toolchain_licenses(report(tools=[tool("go"), tool("rustc")]))
    assert inventory["obligations_present"] == []


def test_the_scope_says_this_is_not_a_dependency_report() -> None:
    inventory = toolchain_licenses(report())
    assert "not of this project's dependencies" in inventory["scope"]


@pytest.mark.parametrize("name", sorted(TOOL_LICENSES))
def test_every_license_row_explains_its_obligation(name: str) -> None:
    entry = TOOL_LICENSES[name]
    assert entry.note.strip()
    assert entry.spdx.strip()
    assert entry.obligation in {"none", "redistribution-only", "review"}
