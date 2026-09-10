"""The three compliance commands, driven through the CLI rather than around it.

`devrepro ci-diff` crashed for months on a colour name click does not define,
and every unit test passed the whole time, because they all called the function
and none of them ran the command. These three produce documents people attach
to tickets, so the rendering path is the part that has to work.

Each command is scanned-out here: `run_scan` is replaced with a fixed report so
a test asserts on rendering rather than on whatever happens to be installed on
the machine running the suite.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from devrepro.cli.app import app
from devrepro.core.exit_codes import ExitCode
from devrepro.core.models import PlatformInfo, ScanReport, ToolInstallation
from devrepro.snapshots.signing import sign_bytes
from typer.testing import CliRunner

if TYPE_CHECKING:
    from devrepro.core.models import Policy

runner = CliRunner()

REPORT = ScanReport(
    schema_version="1.0",
    devrepro_version="0.2.0",
    created_at=datetime(2026, 7, 8, tzinfo=UTC),
    platform=PlatformInfo(os_name="Linux", os_version="6.8.0", arch="x86_64"),
    tools=(
        ToolInstallation(name="git", version="2.44.0", is_active=True),
        ToolInstallation(name="go", version="1.22.0", is_active=True),
    ),
)


@pytest.fixture(autouse=True)
def fixed_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the scan so these assertions describe rendering, not this machine."""

    def scan(*, policy: Policy | None = None) -> ScanReport:
        return REPORT

    monkeypatch.setattr("devrepro.cli.pipeline.run_scan", scan)


# --------------------------------------------------------------------- attest


def test_attest_writes_a_statement_and_prints_the_signing_command(tmp_path: Path) -> None:
    """Everything up to the irreversible step, and then the user's own decision."""
    subject = tmp_path / "snap.json"
    subject.write_text("{}", encoding="utf-8")
    out = tmp_path / "statement.json"

    result = runner.invoke(app, ["attest", str(subject), "-o", str(out)])

    assert result.exit_code == ExitCode.READY
    statement = json.loads(out.read_text(encoding="utf-8"))
    assert statement["_type"].endswith("Statement/v1")
    assert "cosign attest-blob" in result.output


def test_attest_emits_json_when_asked(tmp_path: Path) -> None:
    subject = tmp_path / "snap.json"
    subject.write_text("{}", encoding="utf-8")

    result = runner.invoke(app, ["attest", str(subject), "--json"])

    assert result.exit_code == ExitCode.READY
    assert json.loads(result.output)["predicate"]["toolchain"]


def test_attest_refuses_an_unknown_kind(tmp_path: Path) -> None:
    subject = tmp_path / "snap.json"
    subject.write_text("{}", encoding="utf-8")

    result = runner.invoke(app, ["attest", str(subject), "--kind", "nonsense"])

    assert result.exit_code == ExitCode.USAGE_ERROR


def test_a_reproduction_statement_without_its_link_is_a_usage_error(tmp_path: Path) -> None:
    """The link between artefact and environment is the entire content of the claim."""
    subject = tmp_path / "app.tar"
    subject.write_bytes(b"x")

    result = runner.invoke(app, ["attest", str(subject), "--kind", "reproduction"])

    assert result.exit_code == ExitCode.USAGE_ERROR
    assert "environment-digest" in result.output


def test_provenance_is_produced_for_an_artefact(tmp_path: Path) -> None:
    subject = tmp_path / "image.tar"
    subject.write_bytes(b"x")

    result = runner.invoke(app, ["attest", str(subject), "--kind", "provenance", "--json"])

    assert result.exit_code == ExitCode.READY
    assert json.loads(result.output)["predicateType"].startswith("https://slsa.dev/")


# ------------------------------------------------------------------- evidence


def test_evidence_leads_with_what_it_is_not() -> None:
    """The likeliest harm is somebody reading this as a conformance report."""
    result = runner.invoke(app, ["evidence"])

    assert result.exit_code == ExitCode.READY
    assert "not a conformance assessment" in result.output


def test_evidence_renders_for_humans_not_as_a_python_dict() -> None:
    """The `check`/`generate`/`rules` fault: a dict repr is not a human interface."""
    result = runner.invoke(app, ["evidence", "--framework", "slsa"])

    assert not result.output.lstrip().startswith("{")
    assert "SLSA/Provenance" in result.output


def test_evidence_refuses_an_unknown_framework() -> None:
    result = runner.invoke(app, ["evidence", "--framework", "sox"])

    assert result.exit_code == ExitCode.USAGE_ERROR
    assert "cra" in result.output


def test_evidence_writes_a_file_when_asked(tmp_path: Path) -> None:
    out = tmp_path / "pack.json"

    result = runner.invoke(app, ["evidence", "-o", str(out)])

    assert result.exit_code == ExitCode.READY
    assert json.loads(out.read_text(encoding="utf-8"))["controls"]


def test_the_license_inventory_shows_the_obligation_beside_the_identifier() -> None:
    """`GPL-2.0-only` beside git, with no note, tells a legal team the wrong thing."""
    result = runner.invoke(app, ["evidence", "--licenses"])

    assert result.exit_code == ExitCode.READY
    assert "git 2.44.0: GPL-2.0-only [redistribution-only]" in result.output


# ----------------------------------------------------------------- advisories


def test_advisories_names_what_it_has_no_data_for() -> None:
    """Silence and a clean result are different answers and must read differently."""
    result = runner.invoke(app, ["advisories"])

    assert result.exit_code in {ExitCode.READY, ExitCode.READY_WITH_WARNINGS}
    assert "No advisory data for: go" in result.output
    assert "not a clean result" in result.output


def test_a_match_warns_and_never_blocks() -> None:
    """git 2.44.0 is below 2.44.1, which is where the fix landed on that branch."""
    result = runner.invoke(app, ["advisories", "--json"])

    assert result.exit_code == ExitCode.READY_WITH_WARNINGS
    payload = json.loads(result.output)
    assert [row["id"] for row in payload["affected"]] == ["CVE-2024-32002"]


def test_the_bundle_reports_its_own_age() -> None:
    result = runner.invoke(app, ["advisories", "--json"])
    assert json.loads(result.output)["bundle"]["published"]


def test_an_unsigned_external_bundle_is_refused_at_the_cli(tmp_path: Path) -> None:
    db = tmp_path / "db.json"
    db.write_text(
        json.dumps({"schema_version": "1.0", "published": "2026-01-01", "advisories": []}),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["advisories", "--db", str(db)])

    assert result.exit_code == ExitCode.USAGE_ERROR
    assert "--trust-unsigned" in result.output


def test_a_signed_external_bundle_replaces_the_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The air-gapped path: an organisation's own set, carried in on disk."""
    db = tmp_path / "db.json"
    raw = json.dumps(
        {
            "schema_version": "1.0",
            "published": "2026-08-08",
            "advisories": [
                {
                    "id": "ORG-1",
                    "tool": "go",
                    "summary": "internal",
                    "fixed": ["1.23.0"],
                    "reference": "https://example.invalid/org-1",
                }
            ],
        }
    ).encode("utf-8")
    db.write_bytes(raw)
    (tmp_path / "db.json.sig").write_text(sign_bytes(raw, b"k"), encoding="utf-8")
    monkeypatch.setenv("DEVREPRO_ADVISORY_KEY", "k")

    result = runner.invoke(app, ["advisories", "--db", str(db), "--json"])

    payload = json.loads(result.output)
    assert payload["bundle"]["signed"] is True
    assert [row["id"] for row in payload["affected"]] == ["ORG-1"]


# --------------------------------------------------------------------- history


def test_history_verify_reports_the_head_to_anchor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One short value, recorded elsewhere, is what makes the chain worth having."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    result = runner.invoke(app, ["history", "--verify", "--json"])

    assert result.exit_code == ExitCode.READY
    assert json.loads(result.output)["head"] == "genesis"


def test_a_declined_control_prints_why_it_was_declined() -> None:
    """The reason is the substance of declining; the status alone is a gap."""
    result = runner.invoke(app, ["evidence", "--framework", "slsa"])

    assert "[out-of-scope] SLSA/Build.L2" in result.output
    assert "Why: Level 2 requires a build service" in result.output
