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

from typing import TYPE_CHECKING

import pytest
from devrepro.cli.app import app
from devrepro.core.exit_codes import ExitCode
from typer.testing import CliRunner

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()

_ROOT_DIR = __import__("pathlib").Path(__file__).resolve().parent.parent

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
    # Added after a manual sweep found `devrepro bundle` raising
    # `AttributeError` on every real report. Nothing invoked it, so nothing
    # could have known -- and its own tests passed against a fixture shaped like
    # the code rather than like the scanner. These are the rest of the bounded,
    # read-only commands that were only ever `--help`-tested.
    "advisories",
    "contract",
    "monitor",
    "notify",
    "pins",
    "repro-rate",
)

#: Safe and bounded, but they write into the working directory, so they run
#: inside a temporary one. Excluding them for that reason is how `bundle` stayed
#: uninvoked; a fixture directory is cheaper than a crash nobody sees.
SAFE_BUT_WRITES = (
    "bundle",
    "evidence",
    "init",
    "reproduce",
    "snapshot",
)

#: Commands that block when invoked bare, with the bounded mode that does not.
#:
#: "It runs until interrupted" is a reason to leave the bare form out of the
#: list above. It is not a reason for the bounded form to go untested, and that
#: conflation is how `bundle` and the two `server-*` commands stayed uninvoked
#: long enough to ship a crash and a Python dict printed at a human.
BOUNDED_MODES = (
    ("watch", ("--once",)),
    ("monitor", ("--schedule", "cron")),
)

#: Commands whose first parameter is required, used to pin the usage-error
#: contract: a missing argument must be USAGE_ERROR (4), never BLOCKED (2).
REQUIRES_AN_ARGUMENT = ("which", "baseline", "diff", "report", "generate", "attest")


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


@pytest.mark.parametrize("name", SAFE_BUT_WRITES)
def test_commands_that_write_do_not_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """The same guard, in a directory they are allowed to write to.

    `devrepro bundle` raised `AttributeError` here and exited 1 -- which this
    project publishes as READY_WITH_WARNINGS, so a crash reported itself to CI
    as a run that had gone fine with notes.
    """
    manifest = chr(10).join(["[project]", 'name = "probe"', 'version = "0"', ""])
    # Something to detect, so these exercise the real path rather than the
    # "no project here" early return.
    (tmp_path / "pyproject.toml").write_text(manifest, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, [name])

    assert result.exception is None or isinstance(result.exception, SystemExit), (
        f"`devrepro {name}` raised {result.exception!r}"
    )
    assert result.exit_code in CONTRACT_EXIT_CODES, (
        f"`devrepro {name}` exited {result.exit_code}, which is not in the "
        f"documented contract {sorted(int(c) for c in CONTRACT_EXIT_CODES)}"
    )


@pytest.mark.parametrize(
    ("name", "args"), BOUNDED_MODES, ids=lambda v: v if isinstance(v, str) else ""
)
def test_a_blocking_command_still_has_a_mode_that_returns(name: str, args: tuple[str, ...]) -> None:
    result = runner.invoke(app, [name, *args])
    assert result.exception is None or isinstance(result.exception, SystemExit), (
        f"`devrepro {name} {' '.join(args)}` raised {result.exception!r}"
    )
    assert result.exit_code in CONTRACT_EXIT_CODES
    assert result.output.strip(), "a bounded mode that prints nothing proves nothing"


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


def test_python_m_devrepro_goes_through_main() -> None:
    """The two entry points have to be the same program.

    `devrepro` (the installed script) is `devrepro.cli.app:main`. `python -m
    devrepro` used to call `app()` directly, so it skipped everything `main()`
    does: the Windows console encoding fix -- shipped because one U+2192 in a
    remediation hint ended `devrepro check` in a `UnicodeEncodeError` -- and the
    mapping of an unhandled exception to `INTERNAL_ERROR` rather than to the
    interpreter's 1, which this project publishes as READY_WITH_WARNINGS.

    And `python -m devrepro` is the form this repository's own documentation
    uses throughout, because it works without installing the package. The entry
    point people actually type was the one without the error handling.

    Asserted by parsing rather than by searching for a substring: this file
    would otherwise pass on the sentence above, which names both functions.
    """
    import ast

    source = (_ROOT_DIR / "devrepro" / "__main__.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "devrepro.cli.app"
        for alias in node.names
    }
    assert "main" in imported, "__main__ must import main, not app"
    assert "app" not in imported, "importing app invites calling it"

    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "main" in called
    assert "app" not in called
