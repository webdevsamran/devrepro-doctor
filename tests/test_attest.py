"""Attestations: the shape verifiers expect, and the line this tool will not cross.

An HMAC signature proves a file did not change to whoever holds the key -- who
is also whoever could have forged it. That is fine for detecting your own
accidents and worth nothing as evidence to anybody else. An in-toto statement
is the shape the rest of the supply-chain world reads, and the value of
emitting it is that signing becomes cosign's problem rather than this
project's.

The two properties worth testing are that the document is the shape a verifier
expects, and that nothing in this module ever performs the signing step itself.
Sigstore signing opens an OIDC flow and writes to a public, permanent
transparency log; a diagnostic command has no business starting that.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from devrepro.compliance.attest import (
    ENVIRONMENT_PREDICATE_TYPE,
    REPRODUCTION_PREDICATE_TYPE,
    SLSA_PREDICATE_TYPE,
    STATEMENT_TYPE,
    build_environment_statement,
    build_reproduction_statement,
    build_slsa_provenance,
    cosign_command,
    render_statement,
    subject_for_bytes,
    subject_for_file,
    verify_subject,
)
from devrepro.core.models import (
    Evidence,
    Finding,
    FindingState,
    PlatformInfo,
    ReproducibilityPoint,
    ReproducibilityScore,
    ScanReport,
    ToolInstallation,
)

MODULE = Path(__file__).resolve().parent.parent / "devrepro" / "compliance" / "attest.py"


def tool(name: str, version: str = "1.0.0", *, active: bool = True) -> ToolInstallation:
    return ToolInstallation(
        name=name,
        version=version,
        exe_path="/home/someone/.local/bin/" + name,
        install_source="version-manager",
        is_active=active,
    )


def finding(state: FindingState) -> Finding:
    return Finding(
        rule_id="x/y",
        state=state,
        summary="s",
        evidence=(Evidence(source="system", excerpt="e"),),
    )


def report(
    tools: list[ToolInstallation] | None = None,
    findings: list[Finding] | None = None,
    *,
    score: ReproducibilityScore | None = None,
) -> ScanReport:
    return ScanReport(
        schema_version="1.0",
        devrepro_version="0.2.0",
        created_at=datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC),
        platform=PlatformInfo(os_name="Linux", os_version="6.8.0", arch="x86_64"),
        findings=tuple(findings or []),
        tools=tuple(tools or []),
        score=score,
    )


# ------------------------------------------------------------------ subjects


def test_a_subject_is_a_name_and_a_digest() -> None:
    subject = subject_for_bytes("snapshot.json", b"contents")
    assert subject.name == "snapshot.json"
    assert len(subject.digest) == 64


def test_a_file_subject_carries_the_basename_not_the_path(tmp_path: Path) -> None:
    """A full path names a user's home directory, and this document leaves the machine."""
    nested = tmp_path / "home" / "someone" / "snap.json"
    nested.parent.mkdir(parents=True)
    nested.write_text("{}", encoding="utf-8")

    subject = subject_for_file(nested)

    assert subject.name == "snap.json"
    assert "someone" not in json.dumps(dict(subject))


def test_verify_subject_catches_a_swapped_file() -> None:
    """A signature proves the statement is intact and nothing about the file beside it."""
    subject = subject_for_bytes("snap.json", b"the real one")
    assert verify_subject(subject, b"the real one")
    assert not verify_subject(subject, b"a different one")


def test_a_subject_with_no_digest_never_verifies() -> None:
    assert not verify_subject({"name": "x"}, b"anything")
    assert not verify_subject({"name": "x", "digest": {"sha256": ""}}, b"anything")


# ---------------------------------------------------------------- statements


def test_the_statement_is_in_toto_v1() -> None:
    """v0.1 spelled the field `predicate_type`; current verifiers read `predicateType`."""
    statement = build_environment_statement(report(), subject_for_bytes("s", b""))

    assert statement["_type"] == STATEMENT_TYPE
    assert statement["predicateType"] == ENVIRONMENT_PREDICATE_TYPE
    assert "predicate_type" not in statement
    assert isinstance(statement["subject"], list)


def test_only_the_tools_that_actually_resolve_are_attested() -> None:
    """An attestation listing every installation describes the disk, not the build."""
    statement = build_environment_statement(
        report([tool("python", "3.12.1"), tool("python", "3.9.0", active=False)]),
        subject_for_bytes("s", b""),
    )
    names = [t["version"] for t in statement["predicate"]["toolchain"]]
    assert names == ["3.12.1"]


def test_the_verdict_is_carried_not_recomputable() -> None:
    """Finding counts and the score cannot be derived from a version list later."""
    statement = build_environment_statement(
        report(
            [tool("go")],
            [finding(FindingState.WARN), finding(FindingState.WARN), finding(FindingState.PASS)],
            score=ReproducibilityScore(
                total=6,
                possible=9,
                points=(
                    ReproducibilityPoint(criterion="c", earned=6, possible=9, explanation="e"),
                ),
            ),
        ),
        subject_for_bytes("s", b""),
    )
    predicate = statement["predicate"]
    assert predicate["findings"] == {"PASS": 1, "WARN": 2}
    assert predicate["reproducibilityScore"] == {"earned": 6, "possible": 9}


def test_the_toolchain_order_is_stable() -> None:
    """An evidence file that reorders on every run cannot be diffed."""
    tools = [tool("rustc"), tool("cargo"), tool("go")]
    first = build_environment_statement(report(tools), subject_for_bytes("s", b""))
    second = build_environment_statement(report(list(reversed(tools))), subject_for_bytes("s", b""))
    assert first["predicate"]["toolchain"] == second["predicate"]["toolchain"]


def test_a_reproduction_statement_links_two_digests() -> None:
    """The subject is what was produced; the predicate names the environment it came from."""
    statement = build_reproduction_statement(
        report(),
        subject_for_bytes("app.tar", b"artefact"),
        environment_digest="a" * 64,
        reproduced=True,
        steps=("docker build .",),
    )
    assert statement["predicateType"] == REPRODUCTION_PREDICATE_TYPE
    assert statement["predicate"]["environmentDigest"]["sha256"] == "a" * 64
    assert statement["predicate"]["steps"] == ["docker build ."]


def test_slsa_provenance_has_the_v1_field_names() -> None:
    """`buildDefinition` and `runDetails`; the v0.2 names would silently fail to verify."""
    statement = build_slsa_provenance(
        subject_for_bytes("image.tar", b"x"),
        builder_id="devrepro/0.2.0",
        started_at="2026-03-04T05:06:07+00:00",
        finished_at="2026-03-04T05:07:07+00:00",
        resolved_dependencies=({"uri": "pkg:oci/python", "digest": {"sha256": "b" * 64}},),
    )
    predicate = statement["predicate"]
    assert statement["predicateType"] == SLSA_PREDICATE_TYPE
    assert set(predicate) == {"buildDefinition", "runDetails"}
    assert predicate["runDetails"]["metadata"]["finishedOn"].endswith("05:07:07+00:00")
    assert predicate["buildDefinition"]["resolvedDependencies"][0]["uri"] == "pkg:oci/python"


def test_provenance_omits_a_finish_time_it_does_not_have() -> None:
    statement = build_slsa_provenance(
        subject_for_bytes("i", b"x"), builder_id="b", started_at="2026-01-01T00:00:00+00:00"
    )
    assert "finishedOn" not in statement["predicate"]["runDetails"]["metadata"]


def test_the_rendered_statement_leads_with_its_type() -> None:
    """Sorting keys would put `_type` last, which reads as broken."""
    rendered = render_statement(build_environment_statement(report(), subject_for_bytes("s", b"")))
    assert rendered.lstrip().splitlines()[1].strip().startswith('"_type"')
    assert rendered.endswith("\n")
    json.loads(rendered)


# ------------------------------------------------------------------ the line


def test_the_cosign_command_is_produced_not_run() -> None:
    argv = cosign_command("statement.json", "snap.json")
    assert argv[0] == "cosign"
    assert "--predicate" in argv
    assert ENVIRONMENT_PREDICATE_TYPE in argv


def test_nothing_in_this_module_can_execute_or_reach_the_network() -> None:
    """The guarantee, asserted rather than assumed.

    Signing with Sigstore opens a browser for OIDC and writes a permanent
    public transparency-log entry. That is the single most irreversible thing
    anywhere near this project, and the module that builds the payload must not
    be able to take the step.
    """
    source = MODULE.read_text(encoding="utf-8")
    for forbidden in ("subprocess", "urllib", "requests", "socket", "os.system", "httpx"):
        assert forbidden not in source, f"{forbidden} would let this module sign or send"
