"""What a consumer may rely on, in a form a consumer can test against.

Everything in this project that another program reads -- exit codes, the JSON
report shape, rule id spelling -- is already documented in prose across
`docs/EXIT-CODES.md`, `README.md` and three schema files. Prose is not a
contract a caller can assert against. Somebody writing a CI wrapper reads the
docs, hard-codes `if rc == 2`, and finds out at the worst possible moment that
their build of devrepro was doing something else.

So this module is the contract as data, plus the checks a consumer's own test
suite can run:

    from devrepro.core.contract import check_report, contract_document

    def test_our_wrapper_still_matches():
        assert contract_document()["contract_version"] == "1.0"
        assert check_report(json.loads(output)) == []

**What is not in here is not promised.** That is the load-bearing sentence.
Human-readable output is not a contract -- it is reformatted whenever it reads
badly, which has happened three times in this project's short life. Findings
appear and disappear as rules are added. The set of tools probed grows. A
consumer that parses terminal output or counts findings has built on sand, and
saying so here is more useful than a compatibility promise nobody could keep.

The reciprocal obligation is on this project: the version below goes up when
any of this changes in a way that breaks a reader, and
`tests/test_exit_codes_documented.py` already holds the exit codes against
their documentation.
"""

from __future__ import annotations

from typing import Any

from devrepro.core.exit_codes import MEANINGS, ExitCode

__all__ = [
    "CONTRACT_VERSION",
    "GUARANTEED",
    "NOT_GUARANTEED",
    "REQUIRED_REPORT_FIELDS",
    "check_exit_code",
    "check_report",
    "contract_document",
]

#: Bumped when anything below changes in a way that breaks a reader. Adding a
#: new exit code or a new optional field does not break a reader; changing what
#: an existing code means, or removing a field, does.
CONTRACT_VERSION = "1.0"

#: Fields a `--json` scan report always carries, with the type a reader can
#: assume. Anything outside this list may be present and may go away.
REQUIRED_REPORT_FIELDS: dict[str, type | tuple[type, ...]] = {
    "schema_version": str,
    "devrepro_version": str,
    "created_at": str,
    "platform": dict,
    "findings": list,
    "tools": list,
}

#: Fields every finding carries. `evidence` is non-empty by construction: a
#: finding with no evidence is a claim, and the model refuses to build one.
REQUIRED_FINDING_FIELDS: dict[str, type | tuple[type, ...]] = {
    "rule_id": str,
    "state": str,
    "summary": str,
    "evidence": list,
}

#: The finding states a reader may switch on. Append-only, same as exit codes.
FINDING_STATES: tuple[str, ...] = ("PASS", "INFO", "WARN", "ERROR", "BLOCKED", "UNKNOWN")

GUARANTEED: tuple[str, ...] = (
    "Exit codes are append-only. The meaning of an existing code never changes.",
    "Every major command accepts `--json` and writes valid JSON to stdout.",
    "A rule id, once emitted, keeps its spelling. Ids are added, not renamed.",
    "Every finding carries at least one piece of evidence.",
    "The JSON report validates against the published schema for its "
    "`schema_version`, and that version is in the payload.",
    "`--quiet` suppresses stdout entirely and communicates only by exit code.",
    "No command contacts the network unless a flag asks it to by name.",
)

NOT_GUARANTEED: tuple[str, ...] = (
    "Human-readable output. It is reformatted whenever it reads badly, and "
    "parsing it is the most common way an integration breaks.",
    "Which findings a scan produces. Rules are added; a machine that was "
    "clean last release may report a new WARN in this one.",
    "The set of tools probed for, or the order they appear in.",
    "Field ordering in JSON output.",
    "Anything under `privacy`, which describes how sanitisation ran and is "
    "diagnostic rather than structural.",
)


def check_exit_code(code: int) -> str | None:
    """The documented name for an exit code, or `None` if it is not in the contract.

    A caller seeing `None` has hit something this build did not promise --
    usually a crash escaping through the interpreter's own exit code, which is
    exactly the case `docs/EXIT-CODES.md` was written after.
    """
    try:
        return ExitCode(code).name
    except ValueError:
        return None


def _field_problems(
    payload: dict[str, Any],
    required: dict[str, type | tuple[type, ...]],
    where: str,
) -> list[str]:
    problems: list[str] = []
    for field, expected in required.items():
        if field not in payload:
            problems.append(f"{where}: missing required field {field!r}")
        elif not isinstance(payload[field], expected):
            actual = type(payload[field]).__name__
            problems.append(f"{where}: {field!r} is {actual}, contract says {expected}")
    return problems


def check_report(payload: dict[str, Any]) -> list[str]:
    """Every way this payload departs from the contract, or an empty list.

    Every way, not the first: a consumer running this in their own CI wants the
    whole list in one run, and stopping at the first problem turns one fix into
    four rounds.

    This checks the *contract*, which is narrower than the JSON schema. The
    schema describes the full shape; this describes the part a reader is
    promised will not move.
    """
    problems = _field_problems(payload, REQUIRED_REPORT_FIELDS, "report")

    findings = payload.get("findings")
    if isinstance(findings, list):
        for index, finding in enumerate(findings):
            where = f"findings[{index}]"
            if not isinstance(finding, dict):
                problems.append(f"{where}: not an object")
                continue
            problems.extend(_field_problems(finding, REQUIRED_FINDING_FIELDS, where))
            state = finding.get("state")
            if isinstance(state, str) and state not in FINDING_STATES:
                problems.append(f"{where}: state {state!r} is not in the contract")
            evidence = finding.get("evidence")
            if isinstance(evidence, list) and not evidence:
                problems.append(f"{where}: evidence is empty; every finding must carry some")
    return problems


def contract_document() -> dict[str, Any]:
    """The contract as a payload, for `devrepro contract --json`."""
    return {
        "contract_version": CONTRACT_VERSION,
        "exit_codes": [
            {
                "code": int(code),
                "name": code.name,
                "meaning": MEANINGS[code],
            }
            for code in ExitCode
        ],
        "finding_states": list(FINDING_STATES),
        "report_fields": sorted(REQUIRED_REPORT_FIELDS),
        "finding_fields": sorted(REQUIRED_FINDING_FIELDS),
        "guaranteed": list(GUARANTEED),
        "not_guaranteed": list(NOT_GUARANTEED),
    }
