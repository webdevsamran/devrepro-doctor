"""Tests for the example pack, in the shape this project asks packs to use.

`RuleContext` is built by hand rather than by scanning. A test that scans the
machine it runs on tests the machine, and every interesting case in a rule pack
is a state the developer's own machine is not in -- the missing tool, the old
version, the one that resolves to a shim.
"""

from __future__ import annotations

from devrepro.core.models import FindingState, PlatformInfo, ToolInstallation
from devrepro.rules.base import RuleContext
from devrepro_rulepack_example import REQUIRED_TOOL, REQUIRED_VERSION, evaluate


def context(*tools: ToolInstallation) -> RuleContext:
    return RuleContext(
        platform_info=PlatformInfo(os_name="Linux", os_version="1", arch="x86_64"),
        tools=tools,
    )


def tool(version: str) -> ToolInstallation:
    return ToolInstallation(name=REQUIRED_TOOL, version=version, is_active=True)


def test_a_missing_tool_blocks() -> None:
    findings = evaluate(context())
    assert [f.rule_id for f in findings] == ["acme/build-tool-missing"]
    assert findings[0].state is FindingState.BLOCKED


def test_the_hint_names_a_next_step() -> None:
    """"Install the required tools" is not a remediation hint."""
    hint = evaluate(context())[0].remediation_hint or ""
    assert REQUIRED_VERSION in hint
    assert "devrepro which" in hint


def test_an_old_version_warns_rather_than_blocks() -> None:
    """It works for most things, which is exactly why it goes unnoticed."""
    findings = evaluate(context(tool("2.39.0")))
    assert findings[0].rule_id == "acme/build-tool-too-old"
    assert findings[0].state is FindingState.WARN


def test_a_satisfied_requirement_is_reported_as_a_pass() -> None:
    """Silence would leave a clean result indistinguishable from an unrun check."""
    findings = evaluate(context(tool("2.47.0")))
    assert findings[0].state is FindingState.PASS


def test_a_tool_with_no_readable_version_is_treated_as_missing() -> None:
    """"Installed, version unknown" cannot satisfy a version requirement."""
    findings = evaluate(context(ToolInstallation(name=REQUIRED_TOOL, is_active=True)))
    assert findings[0].rule_id == "acme/build-tool-missing"


def test_every_finding_carries_evidence() -> None:
    for ctx in (context(), context(tool("2.39.0")), context(tool("2.47.0"))):
        for finding in evaluate(ctx):
            assert finding.evidence


def test_the_pack_passes_the_harness() -> None:
    """The check `devrepro rules-test` runs, as an ordinary test."""
    from devrepro.plugins.testkit import check_pack
    from devrepro.rules.base import PACK_NAMES

    report = check_pack(evaluate, context(tool("2.47.0")), reserved_prefixes=PACK_NAMES)
    assert report.ok, [p.describe() for p in report.problems]
