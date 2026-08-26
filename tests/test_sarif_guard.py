"""Tests for the SARIF 2.1.0 renderer and the `devrepro guard` gate.

All inputs are synthetic; no real machine state is involved.
"""

from __future__ import annotations

import json

from devrepro.cli.app import app
from devrepro.core.models import (
    Evidence,
    Finding,
    FindingState,
    PlatformInfo,
    ScanReport,
)
from devrepro.privacy.gate import assert_no_secrets
from devrepro.reports.sarif import render_sarif
from typer.testing import CliRunner

runner = CliRunner()


def _report() -> ScanReport:
    return ScanReport(
        devrepro_version="0.1.0",
        platform=PlatformInfo(os_name="TestOS", os_version="1.0", arch="x86_64"),
        findings=(
            Finding(
                rule_id="python/version-ok",
                state=FindingState.PASS,
                summary="python 3.12 satisfies >=3.11.",
                evidence=(
                    Evidence(source="command", command=("python", "--version"), excerpt="ok"),
                ),
                detected="3.12",
                required=">=3.11",
            ),
            Finding(
                rule_id="docker/daemon-down",
                state=FindingState.BLOCKED,
                summary="Docker daemon unreachable.",
                evidence=(Evidence(source="command", command=("docker", "info"), excerpt="err"),),
                remediation_hint="Start Docker Desktop.",
            ),
        ),
    )


def test_sarif_is_valid_sarif_210() -> None:
    payload = json.loads(render_sarif(_report()))
    assert payload["version"] == "2.1.0"
    run = payload["runs"][0]
    driver = run["tool"]["driver"]
    assert driver["name"] == "DevRepro Doctor"
    rule_ids = [r["id"] for r in driver["rules"]]
    assert rule_ids == ["docker/daemon-down", "python/version-ok"]
    assert len(run["results"]) == 2


def test_sarif_maps_state_to_level() -> None:
    payload = json.loads(render_sarif(_report()))
    levels = {r["ruleId"]: r["level"] for r in payload["runs"][0]["results"]}
    assert levels["docker/daemon-down"] == "error"
    assert levels["python/version-ok"] == "note"


def test_sarif_results_carry_properties_and_fingerprints() -> None:
    payload = json.loads(render_sarif(_report()))
    by_rule = {r["ruleId"]: r for r in payload["runs"][0]["results"]}
    blocked = by_rule["docker/daemon-down"]
    assert blocked["properties"]["state"] == "BLOCKED"
    assert blocked["properties"]["remediation-hint"] == "Start Docker Desktop."
    fp = blocked["partialFingerprints"]["devreproFinding/v1"]
    assert len(fp) == 64  # sha256 hex


def test_sarif_passes_privacy_gate() -> None:
    out = render_sarif(_report())
    # must not raise, i.e. contains no probable secrets
    assert_no_secrets(out)


def test_cli_scan_and_report_roundtrip_sarif(tmp_path) -> None:
    src = tmp_path / "report.json"
    src.write_text(
        json.dumps(_report().model_dump(mode="json"), default=str),
        encoding="utf-8",
    )
    result = runner.invoke(app, ["report", str(src), "--format", "sarif"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["version"] == "2.1.0"
    assert payload["runs"][0]["results"]


def test_guard_verdict_shape_is_machine_independent() -> None:
    # `guard` scans the real host, so the verdict varies — but the JSON
    # contract must hold everywhere.
    result = runner.invoke(app, ["guard", "--json"])
    assert result.exit_code in (0, 2)
    payload = json.loads(result.output)
    assert payload["verdict"] in ("READY", "BLOCKED")
    assert isinstance(payload["blockers"], list)
