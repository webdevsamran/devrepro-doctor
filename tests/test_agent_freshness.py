"""Stale manifest commands, manifests that disagree, and the readiness score.

A manifest ages differently from the code it describes. Someone renames an npm
script and `AGENTS.md` keeps naming the old one. `npm` still resolves, so a
PATH check passes it, and the agent finds out by running it.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from devrepro.agents import discover_manifests
from devrepro.agents.freshness import (
    compare_manifests,
    project_script_names,
    stale_commands,
)
from devrepro.agents.score import score_readiness
from devrepro.cli.app import app
from typer.testing import CliRunner

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()
NL = chr(10)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _manifest(root: Path, *commands: str) -> None:
    body = NL.join(["```bash", *commands, "```"])
    _write(root / "AGENTS.md", body + NL)


# ------------------------------------------------------------ script sources


def test_npm_scripts_are_read(tmp_path: Path) -> None:
    _write(tmp_path / "package.json", json.dumps({"scripts": {"build": "x", "test": "y"}}))
    assert project_script_names(tmp_path)["npm"] == ("build", "test")


def test_make_targets_are_read(tmp_path: Path) -> None:
    _write(tmp_path / "Makefile", "setup:" + NL + "\techo hi" + NL + "lint:" + NL + "\techo x" + NL)
    assert project_script_names(tmp_path)["make"] == ("lint", "setup")


def test_a_makefile_variable_is_not_a_target(tmp_path: Path) -> None:
    """`CFLAGS := -O2` is an assignment, not something `make` can run."""
    _write(tmp_path / "Makefile", "CFLAGS := -O2" + NL + "build:" + NL + "\tcc" + NL)
    assert project_script_names(tmp_path)["make"] == ("build",)


def test_malformed_package_json_is_survived(tmp_path: Path) -> None:
    _write(tmp_path / "package.json", "{not json")
    assert "npm" not in project_script_names(tmp_path)


def test_a_project_with_no_script_sources_reports_nothing(tmp_path: Path) -> None:
    assert project_script_names(tmp_path) == {}


# ------------------------------------------------------------------- staleness


def test_a_renamed_npm_script_is_caught(tmp_path: Path) -> None:
    """The failure this module exists for: `npm` resolves, the target does not."""
    _write(tmp_path / "package.json", json.dumps({"scripts": {"build": "vite build"}}))
    _manifest(tmp_path, "npm run bundle")

    stale = stale_commands(discover_manifests(tmp_path)[0].commands, tmp_path)

    assert len(stale) == 1
    assert stale[0].target == "bundle"
    assert stale[0].available == ("build",)
    assert "does not define" in stale[0].summary


def test_a_current_command_is_not_reported(tmp_path: Path) -> None:
    _write(tmp_path / "package.json", json.dumps({"scripts": {"build": "vite build"}}))
    _manifest(tmp_path, "npm run build")
    assert stale_commands(discover_manifests(tmp_path)[0].commands, tmp_path) == []


def test_a_missing_make_target_is_caught(tmp_path: Path) -> None:
    _write(tmp_path / "Makefile", "setup:" + NL + "\techo hi" + NL)
    _manifest(tmp_path, "make check")
    stale = stale_commands(discover_manifests(tmp_path)[0].commands, tmp_path)
    assert [s.target for s in stale] == ["check"]


def test_a_runner_with_no_declared_targets_is_skipped(tmp_path: Path) -> None:
    """No package.json means the check has nothing to say, not that all is wrong."""
    _manifest(tmp_path, "npm run build", "make test")
    assert stale_commands(discover_manifests(tmp_path)[0].commands, tmp_path) == []


def test_targets_are_resolved_in_the_directory_the_command_runs_in(tmp_path: Path) -> None:
    """`cd web && npm run x` must be checked against web/package.json.

    Splitting the chain without carrying the directory forward would look in
    the root, find no package.json, and silently pass everything -- which is
    exactly the shape of a monorepo.
    """
    _write(tmp_path / "web" / "package.json", json.dumps({"scripts": {"build": "vite"}}))
    _manifest(tmp_path, "cd web && npm run build", "cd web && npm run bundle")

    stale = stale_commands(discover_manifests(tmp_path)[0].commands, tmp_path)

    assert [s.target for s in stale] == ["bundle"], "the nested package.json was not consulted"


def test_cd_does_not_leak_between_lines(tmp_path: Path) -> None:
    """Each line is independently runnable from the root, and CI runs them so.

    Carrying the directory across lines turned a second `cd web` into
    `web/web`.
    """
    _write(tmp_path / "web" / "package.json", json.dumps({"scripts": {"a": "x", "b": "y"}}))
    _manifest(tmp_path, "cd web && npm run a", "cd web && npm run b")

    commands = discover_manifests(tmp_path)[0].commands
    assert {c.cwd for c in commands if c.program == "npm"} == {"web"}
    assert stale_commands(commands, tmp_path) == []


# ------------------------------------------------------------- disagreements


def test_two_manifests_that_differ_are_reported(tmp_path: Path) -> None:
    _write(tmp_path / "AGENTS.md", NL.join(["```bash", "make test", "make lint", "```"]) + NL)
    _write(tmp_path / "CLAUDE.md", NL.join(["```bash", "make test", "```"]) + NL)

    disagreements = compare_manifests(discover_manifests(tmp_path))

    assert len(disagreements) == 1
    assert disagreements[0].command == "make lint"
    assert disagreements[0].present_in == ("AGENTS.md",)
    assert disagreements[0].absent_from == ("CLAUDE.md",)


def test_matching_manifests_are_quiet(tmp_path: Path) -> None:
    body = NL.join(["```bash", "make test", "```"]) + NL
    _write(tmp_path / "AGENTS.md", body)
    _write(tmp_path / "CLAUDE.md", body)
    assert compare_manifests(discover_manifests(tmp_path)) == []


def test_a_single_manifest_cannot_disagree(tmp_path: Path) -> None:
    _manifest(tmp_path, "make test")
    assert compare_manifests(discover_manifests(tmp_path)) == []


# ------------------------------------------------------------------- scoring


def _score(**kwargs: object):
    defaults: dict[str, object] = {
        "manifests": [],
        "checks": [],
        "drift": [],
        "stale": [],
        "disagreements": [],
    }
    defaults.update(kwargs)
    return score_readiness(**defaults)  # type: ignore[arg-type]


def test_a_repository_with_no_manifest_scores_poorly() -> None:
    result = _score()
    assert result.total < result.possible
    assert result.grade in {"unprepared", "rough"}
    assert any(f.name == "manifest-present" and f.earned == 0 for f in result.factors)


def test_every_factor_explains_itself() -> None:
    """A score whose derivation you cannot see is one you cannot act on."""
    for factor in _score().factors:
        assert factor.explanation.strip()
        assert len(factor.explanation) > 15
        assert factor.earned <= factor.possible


def test_percent_and_grade_are_consistent() -> None:
    result = _score()
    assert 0 <= result.percent <= 100
    assert result.grade in {"ready", "workable", "rough", "unprepared"}


def test_ci_drift_costs_points(tmp_path: Path) -> None:
    clean = _score(drift=[])
    drifted = _score(drift=["python scripts/gate.py"])
    assert drifted.total < clean.total
    assert any(f.name == "matches-ci" and f.earned == 0 for f in drifted.factors)


# ---------------------------------------------------------------------- CLI


def test_agent_check_reports_readiness_and_staleness(tmp_path: Path) -> None:
    _write(tmp_path / "package.json", json.dumps({"scripts": {"build": "vite"}}))
    _manifest(tmp_path, "npm run bundle")

    result = runner.invoke(app, ["agent-check", str(tmp_path), "--json"])
    payload = json.loads(result.output)

    assert payload["stale_commands"][0]["target"] == "bundle"
    assert payload["readiness"]["possible"] > 0
    assert payload["readiness"]["grade"]
    assert any(f["name"] == "commands-current" for f in payload["readiness"]["factors"])


@pytest.mark.parametrize("flag", [[], ["--no-blast-radius"]])
def test_the_human_output_renders(tmp_path: Path, flag: list[str]) -> None:
    _manifest(tmp_path, "python --version")
    result = runner.invoke(app, ["agent-check", str(tmp_path), *flag])
    assert "Agent readiness:" in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)
