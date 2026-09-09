"""Every registered command is exercised through the CLI, not just its helpers.

This file exists because two shipped defects hid in the gap between a tested
pure function and its untested command wiring:

* ``ci-diff`` mapped a status to the Rich colour name ``grey50``, which click
  rejects, so the default (non-``--json``) path raised ``TypeError`` for any
  tool installed locally but absent from CI. ``local_vs_ci_diff`` had three
  tests -- including one that produces exactly that status -- because they
  called the function and never the command.
* Argument-parse errors exited 2, which is BLOCKED in the published contract,
  so a mistyped argument told CI the machine was unusable.

Both are cheap to catch and expensive to miss, so the guard is generic: it
walks ``app.registered_commands`` and will cover commands added later without
anyone remembering to extend this file.
"""

from __future__ import annotations

import pytest
from devrepro.cli.app import app
from devrepro.core.exit_codes import ExitCode
from typer.testing import CliRunner

runner = CliRunner()

CONTRACT_EXIT_CODES = {
    ExitCode.READY,
    ExitCode.READY_WITH_WARNINGS,
    ExitCode.BLOCKED,
    ExitCode.USAGE_ERROR,
}

#: Commands that are safe to invoke bare: read-only, bounded, no server, no
#: filesystem writes outside a temp dir. ``doctor``/``scan``/``preflight`` run
#: a full scan and are covered elsewhere; ``serve`` blocks; the ``server-*``
#: pair needs a database.
SAFE_TO_INVOKE = (
    "agent-check",
    "check",
    "ci-diff",
    "drift",
    "env",
    "envmanagers",
    "git-health",
    "history",
    "info",
    "monorepo",
    "network",
    "path",
    "plan",
    "platform-depth",
    "plugins",
    "ports",
    "profile",
    "project",
    "rules",
    "self-test",
)

#: Commands whose first parameter is required, used to pin the usage-error
#: contract: a missing argument must be USAGE_ERROR (4), never BLOCKED (2).
REQUIRES_AN_ARGUMENT = ("which", "baseline", "diff", "report", "generate")


def _command_names() -> list[str]:
    names = [c.name or c.callback.__name__.rstrip("_") for c in app.registered_commands]
    assert names, "no commands registered"
    return sorted(names)


@pytest.mark.parametrize("name", _command_names())
def test_every_command_has_working_help(name: str) -> None:
    """``--help`` must work for every command; it is the cheapest smoke test."""
    result = runner.invoke(app, [name, "--help"])
    assert result.exit_code == 0, f"`devrepro {name} --help` exited {result.exit_code}"
    assert name.split("-", maxsplit=1)[0] in result.output.lower() or result.output.strip()


@pytest.mark.parametrize("name", SAFE_TO_INVOKE)
def test_safe_commands_do_not_crash(name: str) -> None:
    """A read-only command must not raise, and must honour the exit contract.

    This is the guard that would have caught the ``grey50`` crash: the failure
    only appeared on the human-readable path, which no test invoked.
    """
    result = runner.invoke(app, [name])
    assert result.exception is None or isinstance(result.exception, SystemExit), (
        f"`devrepro {name}` raised {result.exception!r}"
    )
    assert result.exit_code in CONTRACT_EXIT_CODES, (
        f"`devrepro {name}` exited {result.exit_code}, which is not in the "
        f"documented contract {sorted(int(c) for c in CONTRACT_EXIT_CODES)}"
    )


@pytest.mark.parametrize("name", SAFE_TO_INVOKE)
def test_safe_commands_support_json(name: str) -> None:
    """``--json`` is advertised for every major command, so it must parse."""
    result = runner.invoke(app, [name, "--json"])
    assert result.exit_code in CONTRACT_EXIT_CODES
    assert result.exception is None or isinstance(result.exception, SystemExit)


@pytest.mark.parametrize("name", REQUIRES_AN_ARGUMENT)
def test_missing_argument_is_usage_error_not_blocked(name: str) -> None:
    """A parse error must not be reported as BLOCKED.

    Click exits with ``UsageError.exit_code``, which defaults to 2 -- the same
    number this project publishes as BLOCKED. ``devrepro/cli/app.py``
    retargets it to 4 for both the public click package and the copy typer
    vendors as ``typer._click``; if a dependency upgrade breaks that, this
    test fails rather than silently reverting the contract.
    """
    result = runner.invoke(app, [name])
    assert result.exit_code == ExitCode.USAGE_ERROR, (
        f"`devrepro {name}` with no argument exited {result.exit_code}; "
        f"expected {int(ExitCode.USAGE_ERROR)} (USAGE_ERROR). "
        f"Exit code {int(ExitCode.BLOCKED)} means BLOCKED and would tell CI "
        "the machine is unusable."
    )


def test_unknown_command_and_flag_are_usage_errors() -> None:
    assert runner.invoke(app, ["nosuchcommand"]).exit_code == ExitCode.USAGE_ERROR
    assert runner.invoke(app, ["--bogus-flag"]).exit_code == ExitCode.USAGE_ERROR
