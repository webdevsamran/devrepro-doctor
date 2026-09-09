"""Agent-manifest parsing, command resolution and manifest-vs-CI drift.

The drift check was written because every repository available to test it
against had the same defect: an `AGENTS.md` listing a strict subset of the
gates CI enforces. An agent runs everything the manifest names, sees it pass,
opens a pull request, and is failed by checks it was never told about.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from devrepro.agents import (
    check_declared_commands,
    ci_declared_commands,
    discover_manifests,
    manifest_vs_ci,
    parse_declared_commands,
)
from devrepro.cli.app import app
from devrepro.core.exit_codes import ExitCode
from typer.testing import CliRunner

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()
NL = chr(10)


def _write(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(NL.join(lines) + NL, encoding="utf-8")


# --------------------------------------------------------------- parsing


def test_only_shell_blocks_are_treated_as_commands() -> None:
    """A ```json block is configuration; its contents are not instructions."""
    text = NL.join(
        [
            "# Setup",
            "```bash",
            "pytest -q",
            "```",
            "Config:",
            "```json",
            '{"scripts": {"build": "vite build"}}',
            "```",
        ]
    )
    programs = [c.program for c in parse_declared_commands(text, "AGENTS.md")]
    assert programs == ["pytest"]


def test_prose_outside_a_fence_is_not_a_command() -> None:
    text = "Run pytest before pushing, then ruff check ." + NL
    assert parse_declared_commands(text, "AGENTS.md") == []


def test_chained_commands_are_split() -> None:
    """`cd web && npm ci && npm test` is three commands an agent hits in turn."""
    text = NL.join(["```bash", "cd web && npm ci && npm test", "```"])
    programs = [c.program for c in parse_declared_commands(text, "AGENTS.md")]
    assert programs == ["cd", "npm", "npm"]


def test_prompts_and_comments_are_stripped() -> None:
    text = NL.join(
        [
            "```console",
            "$ pytest -q",
            "# a comment line",
            "ruff check .   # trailing note",
            "```",
        ]
    )
    parsed = parse_declared_commands(text, "AGENTS.md")
    assert [c.program for c in parsed] == ["pytest", "ruff"]
    assert parsed[1].raw == "ruff check ."


def test_environment_prefix_is_not_mistaken_for_the_program() -> None:
    text = NL.join(["```bash", "CI=1 pytest -q", "```"])
    assert [c.program for c in parse_declared_commands(text, "AGENTS.md")] == ["pytest"]


def test_line_numbers_are_recorded_for_reporting() -> None:
    text = NL.join(["intro", "```bash", "pytest", "```"])
    assert parse_declared_commands(text, "AGENTS.md")[0].line == 3


# ----------------------------------------------------------- discovery


def test_discovers_each_known_manifest(tmp_path: Path) -> None:
    _write(tmp_path / "AGENTS.md", ["```bash", "pytest", "```"])
    _write(tmp_path / "CLAUDE.md", ["```bash", "ruff check .", "```"])
    _write(tmp_path / ".github" / "copilot-instructions.md", ["```bash", "mypy .", "```"])

    found = {m.path for m in discover_manifests(tmp_path)}
    assert found == {"AGENTS.md", "CLAUDE.md", ".github/copilot-instructions.md"}


def test_no_manifest_is_not_an_error(tmp_path: Path) -> None:
    assert discover_manifests(tmp_path) == []


# -------------------------------------------------------- resolution


def test_a_present_program_resolves(tmp_path: Path) -> None:
    _write(tmp_path / "AGENTS.md", ["```bash", "python --version", "```"])
    checks = check_declared_commands(discover_manifests(tmp_path)[0].commands, root=tmp_path)
    assert [c.status for c in checks] == ["ok"]
    assert checks[0].resolved


def test_an_absent_program_is_reported_as_missing(tmp_path: Path) -> None:
    _write(tmp_path / "AGENTS.md", ["```bash", "definitely-not-a-real-binary-xyz", "```"])
    checks = check_declared_commands(discover_manifests(tmp_path)[0].commands, root=tmp_path)
    assert checks[0].status == "missing"
    assert not checks[0].ok


def test_installed_but_not_on_path_is_distinguished_from_missing(tmp_path: Path) -> None:
    """The distinction an agent cannot currently make for itself.

    `json.tool` is a stdlib module with no console script, so it stands in for
    the real case: a tool installed to user site-packages while its scripts
    directory is off PATH. `pip install X` is the wrong fix for that; adjusting
    PATH is the right one, and the two failures look identical to an agent.
    """
    _write(tmp_path / "AGENTS.md", ["```bash", "json --help", "```"])
    checks = check_declared_commands(
        discover_manifests(tmp_path)[0].commands, root=tmp_path, path_env=""
    )
    assert checks[0].status == "not-on-path"
    assert "python -m json" in checks[0].detail


def test_shell_builtins_are_not_reported_as_missing(tmp_path: Path) -> None:
    _write(tmp_path / "AGENTS.md", ["```bash", "cd web", "```"])
    checks = check_declared_commands(discover_manifests(tmp_path)[0].commands, root=tmp_path)
    assert checks[0].status == "shell-builtin"
    assert checks[0].ok


def test_a_path_shaped_program_is_checked_against_the_repository(tmp_path: Path) -> None:
    """`.venv/bin/activate` is a file a setup step creates, not a PATH lookup."""
    _write(tmp_path / "AGENTS.md", ["```bash", "./scripts/build.sh", "```"])
    checks = check_declared_commands(discover_manifests(tmp_path)[0].commands, root=tmp_path)
    assert checks[0].status == "path-absent"

    _write(tmp_path / "scripts" / "build.sh", ["echo hi"])
    checks = check_declared_commands(discover_manifests(tmp_path)[0].commands, root=tmp_path)
    assert checks[0].status == "ok"


# ------------------------------------------------------------ CI drift


def _workflow(tmp_path: Path, name: str, body: list[str]) -> None:
    _write(tmp_path / ".github" / "workflows" / name, body)


def test_ci_commands_are_read_from_scalar_and_block_run_steps(tmp_path: Path) -> None:
    _workflow(
        tmp_path,
        "ci.yml",
        [
            "on:",
            "  pull_request:",
            "jobs:",
            "  build:",
            "    steps:",
            "      - run: pytest -q",
            "      - run: |",
            "          ruff check .",
            "          mypy src",
            "      - run: echo done",
        ],
    )
    found = ci_declared_commands(tmp_path)
    assert "pytest -q" in found
    assert "ruff check ." in found
    assert "mypy src" in found


def test_release_only_workflows_are_ignored(tmp_path: Path) -> None:
    """A tag-triggered release job is not a gate an agent's PR will face."""
    _workflow(
        tmp_path,
        "release.yml",
        [
            "on:",
            "  push:",
            '    tags: ["v*"]',
            "jobs:",
            "  x:",
            "    steps:",
            "      - run: twine upload dist/*",
        ],
    )
    assert ci_declared_commands(tmp_path) == []


def test_drift_reports_gates_the_manifest_omits(tmp_path: Path) -> None:
    _write(tmp_path / "AGENTS.md", ["```bash", "pytest -q", "```"])
    _workflow(
        tmp_path,
        "ci.yml",
        [
            "on:",
            "  pull_request:",
            "jobs:",
            "  build:",
            "    steps:",
            "      - run: pytest -q",
            "      - run: python scripts/secret_scan.py",
        ],
    )
    declared = discover_manifests(tmp_path)[0].commands
    drift = manifest_vs_ci(declared, ci_declared_commands(tmp_path))
    assert drift == ["python scripts/secret_scan.py"]


def test_python_dash_m_matches_the_direct_spelling(tmp_path: Path) -> None:
    """`python -m pip install` and `pip install` are the same instruction."""
    _write(tmp_path / "AGENTS.md", ["```bash", 'pip install -e ".[dev]"', "```"])
    _workflow(
        tmp_path,
        "ci.yml",
        [
            "on:",
            "  pull_request:",
            "jobs:",
            "  b:",
            "    steps:",
            "      - run: python -m pip install -e .",
        ],
    )
    declared = discover_manifests(tmp_path)[0].commands
    assert manifest_vs_ci(declared, ci_declared_commands(tmp_path)) == []


def test_shell_plumbing_is_not_reported_as_a_missing_gate(tmp_path: Path) -> None:
    """A `run: |` block is full of grep and sed; none of it is a gate."""
    _write(tmp_path / "AGENTS.md", ["```bash", "pytest", "```"])
    _workflow(
        tmp_path,
        "ci.yml",
        [
            "on:",
            "  pull_request:",
            "jobs:",
            "  b:",
            "    steps:",
            "      - run: |",
            "          pytest",
            "          grep -R TODO .",
            "          VERSION=1.2.3",
            "          sha256sum dist/* > SUMS",
            "          continue",
        ],
    )
    declared = discover_manifests(tmp_path)[0].commands
    assert manifest_vs_ci(declared, ci_declared_commands(tmp_path)) == []


# ---------------------------------------------------------------- CLI


def test_cli_reports_ready_for_a_clean_repository(tmp_path: Path) -> None:
    _write(tmp_path / "AGENTS.md", ["```bash", "python --version", "```"])
    result = runner.invoke(app, ["agent-check", str(tmp_path), "--json"])
    assert result.exit_code == ExitCode.READY, result.output
    assert '"verdict": "READY"' in result.output


def test_cli_blocks_when_a_declared_command_cannot_run(tmp_path: Path) -> None:
    _write(tmp_path / "AGENTS.md", ["```bash", "definitely-not-a-real-binary-xyz", "```"])
    result = runner.invoke(app, ["agent-check", str(tmp_path)])
    assert result.exit_code == ExitCode.BLOCKED, result.output


def test_cli_warns_on_drift_alone(tmp_path: Path) -> None:
    """Drift is a warning: the work can proceed, just not as documented."""
    _write(tmp_path / "AGENTS.md", ["```bash", "python --version", "```"])
    _workflow(
        tmp_path,
        "ci.yml",
        [
            "on:",
            "  pull_request:",
            "jobs:",
            "  b:",
            "    steps:",
            "      - run: python scripts/gate.py",
        ],
    )
    result = runner.invoke(app, ["agent-check", str(tmp_path)])
    assert result.exit_code == ExitCode.READY_WITH_WARNINGS, result.output
    assert "no manifest declares" in result.output


def test_cli_is_ready_when_there_is_no_manifest(tmp_path: Path) -> None:
    """Most repositories have no manifest; that is not a failure."""
    result = runner.invoke(app, ["agent-check", str(tmp_path)])
    assert result.exit_code == ExitCode.READY, result.output
    assert "No agent manifest found" in result.output


def test_cli_does_not_execute_anything_by_default(tmp_path: Path) -> None:
    """The read-only promise cannot be conditional on an untrusted file.

    A manifest's setup step is typically an installer. If `agent-check` ran
    declared commands by default, pointing it at a third-party repository would
    execute whatever that repository asked for.
    """
    marker = tmp_path / "SHOULD_NOT_EXIST"
    _write(
        tmp_path / "AGENTS.md",
        ["```bash", f"python -c open({str(marker)!r},'w')", "```"],
    )
    result = runner.invoke(app, ["agent-check", str(tmp_path), "--json"])
    assert result.exit_code in {ExitCode.READY, ExitCode.READY_WITH_WARNINGS}
    assert not marker.exists(), "agent-check executed a declared command without --run"


@pytest.mark.parametrize("flag", ["--json", None])
def test_cli_output_shapes(tmp_path: Path, flag: str | None) -> None:
    _write(tmp_path / "AGENTS.md", ["```bash", "python --version", "```"])
    args = ["agent-check", str(tmp_path)] + ([flag] if flag else [])
    result = runner.invoke(app, args)
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert result.output.strip()
