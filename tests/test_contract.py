"""The consumer contract, and the check a consumer can run against it.

Prose is not a contract a caller can assert against. Somebody writing a CI
wrapper reads `docs/EXIT-CODES.md`, hard-codes `if rc == 2`, and finds out at
the worst moment that their build was doing something else. `devrepro contract`
is that document as data, and `check_report` is the assertion.

The tests below split evenly between the two halves that matter: that the
contract describes what the tool actually does, and that the *not guaranteed*
list is present and specific, because a promise nobody could keep is worse than
a stated limit.
"""

from __future__ import annotations

import json

from devrepro.cli.app import app
from devrepro.core.contract import (
    CONTRACT_VERSION,
    FINDING_STATES,
    GUARANTEED,
    NOT_GUARANTEED,
    check_exit_code,
    check_report,
    contract_document,
)
from devrepro.core.exit_codes import MEANINGS, ExitCode
from devrepro.core.models import FindingState
from typer.testing import CliRunner

runner = CliRunner()


def report(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "devrepro_version": "0.2.0",
        "created_at": "2026-01-01T00:00:00+00:00",
        "platform": {"os_name": "Linux"},
        "findings": [],
        "tools": [],
    }
    payload.update(overrides)
    return payload


def finding(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "rule_id": "x/y",
        "state": "WARN",
        "summary": "s",
        "evidence": [{"source": "system"}],
    }
    payload.update(overrides)
    return payload


# ------------------------------------------------------------------- exit codes


def test_every_documented_code_resolves() -> None:
    for code in ExitCode:
        assert check_exit_code(int(code)) == code.name


def test_a_code_outside_the_contract_is_reported_as_such() -> None:
    """Usually a crash escaping through the interpreter's own exit code."""
    assert check_exit_code(137) is None


def test_the_meanings_cover_every_code() -> None:
    """The mapping exists because Python discards the per-member string literals.

    `ExitCode.BLOCKED.__doc__` returns the *class* docstring -- the same text
    for every member -- so reading it at runtime would have produced a contract
    document giving all five codes the same meaning. Correct-looking, and
    useless. A second copy is the price, and this is the check that keeps it
    honest.
    """
    assert set(MEANINGS) == set(ExitCode)
    assert len(set(MEANINGS.values())) == len(ExitCode)


def test_the_contract_lists_the_codes_with_their_real_meanings() -> None:
    rows = contract_document()["exit_codes"]
    assert [row["code"] for row in rows] == [0, 1, 2, 3, 4]
    assert rows[2]["meaning"] != rows[3]["meaning"]


# --------------------------------------------------------------- report checks


def test_a_conforming_report_produces_no_problems() -> None:
    assert check_report(report(findings=[finding()])) == []


def test_a_missing_required_field_is_named() -> None:
    payload = report()
    del payload["schema_version"]
    assert check_report(payload) == ["report: missing required field 'schema_version'"]


def test_a_wrong_type_is_named_with_what_it_actually_was() -> None:
    problems = check_report(report(findings={}))
    assert any("'findings' is dict" in p for p in problems)


def test_a_finding_with_no_evidence_violates_the_contract() -> None:
    """The one guarantee that separates a finding from an assertion."""
    problems = check_report(report(findings=[finding(evidence=[])]))
    assert problems == ["findings[0]: evidence is empty; every finding must carry some"]


def test_an_unknown_finding_state_is_caught() -> None:
    problems = check_report(report(findings=[finding(state="CATASTROPHE")]))
    assert any("not in the contract" in p for p in problems)


def test_every_problem_is_reported_not_just_the_first() -> None:
    """A consumer running this in their CI wants one round, not four."""
    payload = report(findings=[finding(evidence=[]), finding(state="NOPE")])
    del payload["tools"]
    assert len(check_report(payload)) == 3


def test_the_contract_states_match_the_enum() -> None:
    """A state the tool can emit and the contract omits would fail a consumer."""
    assert set(FINDING_STATES) == {s.value for s in FindingState}


# ------------------------------------------------------------- a real scan


def test_a_real_scan_report_satisfies_the_contract() -> None:
    """The check that makes all of the above worth anything.

    Everything else here asserts against hand-built payloads. This runs the
    tool and holds its actual output to the promise.
    """
    result = runner.invoke(app, ["scan", "--json"])
    assert check_exit_code(result.exit_code) is not None
    assert check_report(json.loads(result.output)) == []


# ------------------------------------------------------------------- honesty


def test_the_not_guaranteed_list_is_present_and_specific() -> None:
    """A compatibility promise nobody could keep is worse than a stated limit."""
    assert len(NOT_GUARANTEED) >= 4
    joined = " ".join(NOT_GUARANTEED).lower()
    assert "human-readable output" in joined
    assert "findings" in joined


def test_the_guarantees_are_things_this_project_actually_holds() -> None:
    joined = " ".join(GUARANTEED).lower()
    assert "append-only" in joined
    assert "evidence" in joined
    assert "network" in joined


def test_the_command_prints_both_halves() -> None:
    result = runner.invoke(app, ["contract"])
    assert result.exit_code == ExitCode.READY
    assert "Guaranteed:" in result.output
    assert "NOT guaranteed" in result.output


def test_the_command_emits_json_a_consumer_can_pin_against() -> None:
    result = runner.invoke(app, ["contract", "--json"])
    document = json.loads(result.output)
    assert document["contract_version"] == CONTRACT_VERSION
    assert document["not_guaranteed"]
