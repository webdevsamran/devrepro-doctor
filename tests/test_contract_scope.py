"""Diff-scoped gating: when is the machine worth re-checking?

`devrepro guard` called itself "designed for a pre-commit hook" and gated on
every finding anywhere, so a stopped Docker daemon blocked a commit touching
only Python source. That is a gate people delete.

Scoping to "changed files" the way a linter does is meaningless for a tool that
scans a machine -- a machine has no per-file technical debt. What changes is
the **environment contract**: the lockfiles, manifests, pins, workflows and
policy that declare what a machine must provide.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from devrepro.cli.app import app
from devrepro.core.exit_codes import ExitCode
from devrepro.core.runner import CommandResult, RecordingRunner
from devrepro.project.contract import (
    ContractChange,
    changed_files,
    classify_contract_path,
    contract_changes,
    relevant_rule_prefixes,
)
from typer.testing import CliRunner

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()
NL = chr(10)


# ---------------------------------------------------------- classification


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        # Root-level files. `fnmatch` has no recursive wildcard, so `**/x`
        # requires a literal separator and these matched nothing at first.
        ("package-lock.json", "lockfile"),
        ("uv.lock", "lockfile"),
        ("pyproject.toml", "manifest"),
        ("Cargo.toml", "manifest"),
        # Dotfiles. `lstrip("./")` strips characters, not a prefix, and turned
        # every one of these into something else.
        (".nvmrc", "toolchain-pin"),
        (".devrepro.toml", "policy"),
        (".github/workflows/ci.yml", "ci"),
        (".tool-versions", "toolchain-pin"),
        # Nested.
        ("web/package-lock.json", "lockfile"),
        ("services/api/pyproject.toml", "manifest"),
        (".devcontainer/devcontainer.json", "container"),
        # Agent instructions are an environment contract for an agent.
        ("AGENTS.md", "agent-manifest"),
    ],
)
def test_contract_files_are_classified(path: str, kind: str) -> None:
    assert classify_contract_path(path) == kind


@pytest.mark.parametrize(
    "path",
    [
        "devrepro/core/models.py",
        "web/src/App.tsx",
        "README.md",
        "tests/test_thing.py",
        "docs/RULES.md",
        # `.env` holds values. This project reads names only, and a gate that
        # reacted to it would invite someone to point the tool at secrets.
        ".env",
    ],
)
def test_ordinary_source_is_not_a_contract_change(path: str) -> None:
    assert classify_contract_path(path) is None


# --------------------------------------------------------------- git reading


def test_untracked_files_are_listed_individually() -> None:
    """`git status --porcelain` collapses a new directory to its name.

    A brand-new `.devcontainer/devcontainer.json` appeared as `.devcontainer/`,
    which matches no pattern -- so the change most worth gating on was the one
    that went unseen. `--untracked-files=all` is what fixes it, and this pins
    the flag.
    """
    recording = RecordingRunner(
        {"git": CommandResult(("git",), 0, "?? .devcontainer/devcontainer.json" + NL, "")}
    )
    files = changed_files(".", runner=recording)

    assert files == [".devcontainer/devcontainer.json"]
    assert any("--untracked-files=all" in call for call in recording.calls), (
        "the untracked-files flag was dropped; new directories will be missed"
    )


def test_a_rename_reports_the_new_path() -> None:
    recording = RecordingRunner(
        {"git": CommandResult(("git",), 0, "R  old.lock -> package-lock.json" + NL, "")}
    )
    assert changed_files(".", runner=recording) == ["package-lock.json"]


def test_a_base_ref_uses_a_three_dot_diff() -> None:
    """Three dots: what this branch changed, not what also landed on base."""
    recording = RecordingRunner({"git": CommandResult(("git",), 0, "uv.lock" + NL, "")})
    changed_files(".", base="origin/main", runner=recording)
    assert any("origin/main...HEAD" in " ".join(call) for call in recording.calls)


def test_a_non_repository_is_not_an_error() -> None:
    assert changed_files(".", runner=RecordingRunner()) == []


def test_only_contract_files_survive_the_filter() -> None:
    recording = RecordingRunner(
        {
            "git": CommandResult(
                ("git",),
                0,
                NL.join([" M devrepro/core/models.py", " M uv.lock", "?? README.md"]) + NL,
                "",
            )
        }
    )
    changes = contract_changes(".", runner=recording)
    assert [c.path for c in changes] == ["uv.lock"]


# ------------------------------------------------------------- relevance


def test_a_manifest_change_does_not_make_docker_relevant() -> None:
    """The point of the filter.

    Changing a Python manifest while Docker happens to be stopped must not
    block the commit. Scoping decided whether to look; this decides where.
    """
    prefixes = relevant_rule_prefixes([ContractChange("pyproject.toml", "manifest")])
    assert prefixes is not None
    assert "python" in prefixes
    assert "containers" not in prefixes


def test_a_container_change_does_make_docker_relevant() -> None:
    prefixes = relevant_rule_prefixes(
        [ContractChange(".devcontainer/devcontainer.json", "container")]
    )
    assert prefixes is not None
    assert "containers" in prefixes


def test_a_policy_change_makes_everything_relevant() -> None:
    """The policy declares what the machine must provide, so it re-opens all."""
    assert relevant_rule_prefixes([ContractChange(".devrepro.toml", "policy")]) is None


def test_no_changes_means_nothing_is_relevant() -> None:
    assert relevant_rule_prefixes([]) == set()


def test_mixed_changes_take_the_union() -> None:
    prefixes = relevant_rule_prefixes(
        [
            ContractChange("pyproject.toml", "manifest"),
            ContractChange(".devcontainer/devcontainer.json", "container"),
        ]
    )
    assert prefixes is not None
    assert {"python", "containers"} <= prefixes


# ---------------------------------------------------------------------- CLI


def test_a_clean_tree_passes_without_scanning() -> None:
    """The property that makes the hook survivable.

    Most commits touch no contract file, and for those the gate must be a
    near-instant no-op -- a hook that runs a full machine scan on every commit
    is a hook that gets removed.
    """
    result = runner.invoke(app, ["guard", "--scope", "changed", "--json"])
    assert result.exit_code == ExitCode.READY
    payload = json.loads(result.output)
    assert payload["contract_changes"] == []
    assert payload["blockers"] == []


def test_an_unknown_scope_is_a_usage_error() -> None:
    result = runner.invoke(app, ["guard", "--scope", "nonsense"])
    assert result.exit_code == ExitCode.USAGE_ERROR


def test_machine_scope_is_still_the_default(tmp_path: Path) -> None:
    """The existing behaviour must not change for anyone relying on it."""
    result = runner.invoke(app, ["guard", "--json"])
    payload = json.loads(result.output)
    assert payload["scope"] == "machine"
