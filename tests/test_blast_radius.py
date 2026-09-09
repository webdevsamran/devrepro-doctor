"""What an agent could reach, assessed before it starts.

The published 2026 incidents -- a production database and its backups deleted
in nine seconds, a thirteen-hour outage after an agent recreated an environment
-- share a shape: the agent had authority nobody had enumerated. These tests
cover the enumeration, and two properties that make it safe to run and safe to
publish.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from devrepro.agents.blast_radius import assess_blast_radius
from devrepro.cli.app import app
from devrepro.core.runner import CommandResult, RecordingRunner
from typer.testing import CliRunner

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()
NL = chr(10)


def _clean_env() -> dict[str, str]:
    """An environment with nothing interesting in it."""
    return {"PATH": "/usr/bin", "HOME": "/home/dev"}


# ------------------------------------------------------------- credentials


def test_credential_values_are_never_read_or_reported() -> None:
    """The whole briefing is safe to paste into an issue, or hand to the agent.

    Names are listed; values are not touched. A blast-radius report that leaked
    the secrets it was warning about would be self-defeating.
    """
    # Shaped like a real GitHub PAT so the redaction path is exercised, but
    # assembled at runtime so no scanner -- ours included -- sees a literal.
    secret = "ghp_" + ("x" * 32)
    env = {**_clean_env(), "GITHUB_TOKEN": secret, "AWS_SECRET_ACCESS_KEY": secret}

    result = assess_blast_radius(".", env=env, runner=RecordingRunner())

    blob = json.dumps(
        {
            "names": list(result.credential_names),
            "exposures": [
                {"summary": e.summary, "detail": e.detail, "evidence": e.evidence}
                for e in result.exposures
            ],
        }
    )
    assert secret not in blob, "a credential value reached the report"
    assert "GITHUB_TOKEN" in result.credential_names
    assert "AWS_SECRET_ACCESS_KEY" in result.credential_names


def test_identifiers_are_not_mistaken_for_credentials() -> None:
    """`SESSION_ID` is an identifier.

    The first version of this check used its own name pattern including a bare
    `SESSION`, and flagged nine variables on the development machine of which
    one was a credential. A briefing that cries wolf is skimmed past, so it now
    shares the privacy module's pattern.
    """
    env = {
        **_clean_env(),
        "CLAUDE_CODE_HOST_SESSION_ID": "abc",
        "BUILD_ID": "123",
        "USER_AGENT": "curl/8",
        "REAL_TOKEN": "x",
    }
    result = assess_blast_radius(".", env=env, runner=RecordingRunner())
    assert result.credential_names == ("REAL_TOKEN",)


# --------------------------------------------------------- production target


@pytest.mark.parametrize(
    ("var", "value"),
    [
        ("NODE_ENV", "production"),
        ("AWS_PROFILE", "prod-admin"),
        ("RAILS_ENV", "PRODUCTION"),
        ("VERCEL_ENV", "production"),
    ],
)
def test_a_production_target_is_reported_as_high_severity(var: str, value: str) -> None:
    result = assess_blast_radius(".", env={**_clean_env(), var: value}, runner=RecordingRunner())
    prod = [e for e in result.exposures if e.kind == "production-target"]
    assert prod, f"{var}={value} was not reported"
    assert prod[0].severity == "high"
    assert var in (prod[0].evidence or "")


def test_a_development_target_is_not_reported() -> None:
    env = {**_clean_env(), "NODE_ENV": "development", "AWS_PROFILE": "sandbox"}
    result = assess_blast_radius(".", env=env, runner=RecordingRunner())
    assert not [e for e in result.exposures if e.kind == "production-target"]


def test_a_production_kubernetes_context_is_high_severity() -> None:
    runner_ = RecordingRunner({"kubectl": CommandResult(("kubectl",), 0, "prod-eu-west-1", "")})
    result = assess_blast_radius(".", env=_clean_env(), runner=runner_)
    ctx = [e for e in result.exposures if e.kind == "kubernetes-context"]
    assert ctx and ctx[0].severity == "high"


def test_a_non_production_context_is_reported_as_context_not_alarm() -> None:
    """Still worth stating -- an agent's kubectl goes somewhere."""
    runner_ = RecordingRunner({"kubectl": CommandResult(("kubectl",), 0, "minikube", "")})
    result = assess_blast_radius(".", env=_clean_env(), runner=runner_)
    ctx = [e for e in result.exposures if e.kind == "kubernetes-context"]
    assert ctx and ctx[0].severity == "info"


def test_absent_kubectl_reports_nothing() -> None:
    result = assess_blast_radius(".", env=_clean_env(), runner=RecordingRunner())
    assert not [e for e in result.exposures if e.kind == "kubernetes-context"]


# ---------------------------------------------------------------- git state


def test_uncommitted_work_is_reported() -> None:
    runner_ = RecordingRunner(
        {"git": [CommandResult(("git",), 0, " M a.py" + NL + "?? b.py" + NL, "")]}
    )
    result = assess_blast_radius(".", env=_clean_env(), runner=runner_)
    assert result.uncommitted_files == 2
    assert [e for e in result.exposures if e.kind == "uncommitted-work"]


def test_a_large_dirty_tree_escalates_to_high() -> None:
    """Twenty uncommitted files is a working session, not a stray edit."""
    lines = NL.join(f" M file{i}.py" for i in range(25))
    runner_ = RecordingRunner({"git": [CommandResult(("git",), 0, lines, "")]})
    result = assess_blast_radius(".", env=_clean_env(), runner=runner_)
    dirty = [e for e in result.exposures if e.kind == "uncommitted-work"]
    assert dirty and dirty[0].severity == "high"


def test_unpushed_commits_are_reported() -> None:
    runner_ = RecordingRunner(
        {
            "git": [
                CommandResult(("git",), 0, "", ""),  # status: clean
                CommandResult(("git",), 0, "7" + NL, ""),  # rev-list
            ]
        }
    )
    result = assess_blast_radius(".", env=_clean_env(), runner=runner_)
    assert result.unpushed_commits == 7
    assert [e for e in result.exposures if e.kind == "unpushed-commits"]


def test_a_clean_synced_repository_reports_no_git_exposure() -> None:
    runner_ = RecordingRunner(
        {"git": [CommandResult(("git",), 0, "", ""), CommandResult(("git",), 0, "0" + NL, "")]}
    )
    result = assess_blast_radius(".", env=_clean_env(), runner=runner_)
    assert result.uncommitted_files == 0
    assert not [e for e in result.exposures if e.kind in {"uncommitted-work", "unpushed-commits"}]


def test_a_directory_that_is_not_a_repository_is_not_an_error() -> None:
    result = assess_blast_radius(".", env=_clean_env(), runner=RecordingRunner())
    assert result.uncommitted_files == 0


def test_git_is_only_ever_read() -> None:
    """No command may touch the index or the working tree.

    An assessment of what an agent might destroy must not destroy anything.
    """
    recording = RecordingRunner(
        {"git": [CommandResult(("git",), 0, " M a.py", ""), CommandResult(("git",), 0, "1", "")]}
    )
    assess_blast_radius(".", env=_clean_env(), runner=recording)

    mutating = {"add", "commit", "reset", "checkout", "clean", "stash", "rm", "push"}
    for call in recording.calls:
        assert not (set(call) & mutating), f"blast radius ran a mutating git command: {call}"


# ------------------------------------------------------------------ severity


def test_highest_severity_summarises_the_briefing() -> None:
    env = {**_clean_env(), "NODE_ENV": "production"}
    assert assess_blast_radius(".", env=env, runner=RecordingRunner()).highest_severity == "high"


def test_a_quiet_machine_reports_none() -> None:
    import devrepro.agents.blast_radius as br

    original = br._AMBIENT_CREDENTIAL_FILES
    br._AMBIENT_CREDENTIAL_FILES = ()
    try:
        result = assess_blast_radius(".", env=_clean_env(), runner=RecordingRunner())
        assert result.highest_severity == "none"
        assert result.exposures == ()
    finally:
        br._AMBIENT_CREDENTIAL_FILES = original


# ---------------------------------------------------------------------- CLI


def _manifest(root: Path) -> None:
    """A minimal AGENTS.md declaring one command that resolves everywhere."""
    (root / "AGENTS.md").write_text(
        "```bash" + NL + "python --version" + NL + "```" + NL, encoding="utf-8"
    )


def test_agent_check_includes_the_briefing(tmp_path: Path) -> None:
    _manifest(tmp_path)
    result = runner.invoke(app, ["agent-check", str(tmp_path), "--json"])
    payload = json.loads(result.output)
    assert "blast_radius" in payload
    assert "highest_severity" in payload["blast_radius"]


def test_the_briefing_can_be_turned_off(tmp_path: Path) -> None:
    _manifest(tmp_path)
    result = runner.invoke(app, ["agent-check", str(tmp_path), "--no-blast-radius", "--json"])
    assert "blast_radius" not in json.loads(result.output)
