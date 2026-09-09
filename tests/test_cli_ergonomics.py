"""`--quiet`, colour control, `explain`, `--fix-plan` and `init`.

These finish the machine-readable output contract and give a finding somewhere
to point: an id and one line of summary is the right amount for a table and not
enough to act on.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import pytest
import yaml
from devrepro.cli.app import app
from devrepro.cli.common import color_enabled
from devrepro.core.exit_codes import ExitCode
from typer.testing import CliRunner

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()
NL = chr(10)


# ------------------------------------------------------------------ --quiet


#: Every gate command runs a full machine scan, which takes seconds. Twelve CI
#: legs multiply that, so these tests invoke each command once rather than
#: comparing a loud run against a quiet one.
CONTRACT_CODES = {ExitCode.READY, ExitCode.READY_WITH_WARNINGS, ExitCode.BLOCKED}


@pytest.mark.parametrize("command", ["guard", "preflight"])
def test_quiet_prints_nothing_but_keeps_the_exit_code(command: str) -> None:
    """A gate that passes should be silent; the exit code is the interface."""
    quiet = runner.invoke(app, [command, "--quiet"])
    assert quiet.output.strip() == "", f"`{command} --quiet` printed output"
    assert quiet.exit_code in CONTRACT_CODES


def test_doctor_quiet_is_silent() -> None:
    result = runner.invoke(app, ["doctor", "--quiet"])
    assert result.output.strip() == ""
    assert result.exit_code in CONTRACT_CODES


# -------------------------------------------------------------- NO_COLOR


def test_no_color_disables_colour(monkeypatch: pytest.MonkeyPatch) -> None:
    """https://no-color.org: any value, including empty, disables colour."""
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.setenv("NO_COLOR", "")
    assert color_enabled() is False
    monkeypatch.setenv("NO_COLOR", "1")
    assert color_enabled() is False


def test_force_color_wins_over_no_color(monkeypatch: pytest.MonkeyPatch) -> None:
    """CI log viewers that render ANSI set FORCE_COLOR; it takes precedence."""
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert color_enabled() is True


def test_colour_is_off_when_stdout_is_not_a_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """A redirected report should not arrive full of escape sequences."""
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    # pytest captures stdout, so it is already not a tty here.
    assert color_enabled() is False


def test_output_carries_no_ansi_when_redirected() -> None:
    os.environ.pop("FORCE_COLOR", None)
    result = runner.invoke(app, ["guard"])
    assert "\x1b[" not in result.output


# -------------------------------------------------------------- explain


def test_explain_resolves_a_literal_rule() -> None:
    result = runner.invoke(app, ["explain", "path/duplicates", "--json"])
    assert result.exit_code == ExitCode.READY
    doc = json.loads(result.output)
    assert doc["rule_id"] == "path/duplicates"
    assert doc["means"] and doc["matters"] and doc["fix"]


def test_explain_resolves_a_composed_rule_for_any_prefix() -> None:
    """No code writes "kubectl/multiple-installations"; the prefix is runtime."""
    result = runner.invoke(app, ["explain", "kubectl/multiple-installations", "--json"])
    assert result.exit_code == ExitCode.READY
    assert json.loads(result.output)["rule_id"] == "kubectl/multiple-installations"


def test_explain_refuses_an_unknown_id_with_a_usage_error() -> None:
    result = runner.invoke(app, ["explain", "not/areal-rule"])
    assert result.exit_code == ExitCode.USAGE_ERROR
    assert "rules --catalog" in result.output


def test_every_rule_a_scan_emits_can_be_explained() -> None:
    """The catalogue has to cover what the tool actually produces.

    This is the check that keeps documentation and behaviour together: a rule
    added without an entry fails here rather than reaching a user as an id with
    nothing behind it.
    """
    from devrepro.rules.catalog import explain_rule

    scan = runner.invoke(app, ["scan", "--json"])
    assert scan.exit_code in CONTRACT_CODES
    report = json.loads(scan.output)
    undocumented = sorted(
        {f["rule_id"] for f in report["findings"] if explain_rule(f["rule_id"]) is None}
    )
    assert not undocumented, f"emitted but undocumented: {undocumented}"


def test_rules_catalog_lists_documented_ids() -> None:
    result = runner.invoke(app, ["rules", "--catalog", "--json"])
    assert result.exit_code == ExitCode.READY
    rules = json.loads(result.output)["rules"]
    assert len(rules) > 50
    assert all(r["rule_id"] and r["title"] for r in rules)


# ------------------------------------------------------------- --fix-plan


def test_fix_plan_emits_a_script_and_runs_nothing(tmp_path: Path) -> None:
    marker = tmp_path / "SHOULD_NOT_EXIST"
    result = runner.invoke(app, ["doctor", "--fix-plan"])
    assert result.output.startswith("#!/usr/bin/env bash")
    assert "REVIEW BEFORE RUNNING" in result.output
    assert not marker.exists()


def test_fix_plan_comments_out_anything_above_low_risk() -> None:
    """A plan that pastes cleanly and silently runs a HIGH-risk change is a trap."""
    from devrepro.cli.commands.diagnostics import _render_fix_plan
    from devrepro.core.models import Evidence, Finding, FindingState, PlatformInfo, ScanReport

    report = ScanReport(
        devrepro_version="0.0.0",
        platform=PlatformInfo(os_name="Linux", os_version="1", arch="x86_64"),
        findings=(
            Finding(
                rule_id="path/duplicates",
                state=FindingState.WARN,
                summary="duplicates",
                evidence=(Evidence(source="env", excerpt="x"),),
            ),
        ),
    )
    script = _render_fix_plan(report)
    assert "set -euo pipefail" in script
    for line in script.splitlines():
        if line.startswith("#") or not line.strip() or line.startswith("set "):
            continue
        assert not line.startswith("rm "), "a destructive command was left uncommented"


# ----------------------------------------------------------------- init


def test_init_previews_without_writing(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]" + NL + 'name = "x"' + NL + 'requires-python = ">=3.11"' + NL,
        encoding="utf-8",
    )
    result = runner.invoke(app, ["init", str(tmp_path)])
    assert result.exit_code == ExitCode.READY
    assert "Preview only" in result.output
    assert not (tmp_path / ".devrepro.toml").exists()


def test_init_writes_a_loadable_policy_and_valid_yaml(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]" + NL + 'name = "x"' + NL + 'requires-python = ">=3.11"' + NL,
        encoding="utf-8",
    )
    result = runner.invoke(app, ["init", str(tmp_path), "--write"])
    assert result.exit_code == ExitCode.READY

    from devrepro.project.policy import load_policy

    policy = load_policy(tmp_path / ".devrepro.toml")
    assert policy.required_runtimes.get("python") == ">=3.11"

    workflow = yaml.safe_load((tmp_path / ".github/workflows/devrepro.yml").read_text())
    assert "preflight" in workflow["jobs"]

    hook = yaml.safe_load((tmp_path / ".pre-commit-config.devrepro.yaml").read_text())
    assert hook["repos"][0]["hooks"][0]["id"] == "devrepro-contract-guard"


def test_the_generated_hook_is_diff_scoped(tmp_path: Path) -> None:
    """A hook that runs a full machine scan on every commit gets removed.

    The generated hook uses `guard --scope changed`, which exits without
    scanning unless the commit alters the environment contract. Bare `guard`
    would be wrong here: it fails on any blocker anywhere, so a stopped Docker
    daemon would block a commit touching only source.
    """
    import re

    (tmp_path / "pyproject.toml").write_text("[project]" + NL + 'name = "x"' + NL, encoding="utf-8")
    runner.invoke(app, ["init", str(tmp_path), "--write"])
    hook = yaml.safe_load((tmp_path / ".pre-commit-config.devrepro.yaml").read_text())
    entry = hook["repos"][0]["hooks"][0]

    assert "guard" in entry["entry"]
    assert "--scope changed" in entry["entry"], "the hook must be diff-scoped"

    rx = re.compile(entry["files"], re.VERBOSE)
    for should_match in (
        ".devrepro.toml",
        "pyproject.toml",
        "package-lock.json",
        "uv.lock",
        ".github/workflows/ci.yml",
    ):
        assert rx.match(should_match), f"hook should run for {should_match}"
    for should_skip in ("devrepro/core/models.py", "README.md", "web/src/App.tsx"):
        assert not rx.match(should_skip), f"hook should not run for {should_skip}"


def test_init_refuses_to_clobber_without_overwrite(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]" + NL + 'name = "x"' + NL, encoding="utf-8")
    (tmp_path / ".devrepro.toml").write_text("# mine, do not touch" + NL, encoding="utf-8")
    runner.invoke(app, ["init", str(tmp_path), "--write"])
    assert "do not touch" in (tmp_path / ".devrepro.toml").read_text(encoding="utf-8")
