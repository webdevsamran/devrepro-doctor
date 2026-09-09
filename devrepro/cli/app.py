"""DevRepro Doctor CLI.

All major commands support --json and stable exit codes:
  0 READY · 1 READY_WITH_WARNINGS · 2 BLOCKED · 3 INTERNAL_ERROR · 4 USAGE

The command surface lives in ``devrepro.cli.commands`` — one module per
domain, each exposing a single ``register(app)`` hook. Commands stay flat
(``devrepro doctor``, never ``devrepro diagnostics doctor``) while the code
is split by domain for reviewable, conflict-free contributions.
"""

from __future__ import annotations

import contextlib
import sys

import click
import typer

from devrepro import __version__
from devrepro.cli.commands import register_all
from devrepro.core.exit_codes import ExitCode


def _retarget_usage_error_exit_code() -> None:
    """Make argument-parse errors exit 4 (USAGE_ERROR), not 2 (BLOCKED).

    Click exits with ``UsageError.exit_code``, which defaults to 2 -- and 2
    means BLOCKED in this project's public contract, so a mistyped argument
    told CI the machine was unusable. Commands already raise
    ``ExitCode.USAGE_ERROR`` for input their own logic rejects; parse errors
    never reached it, because click handles them in standalone mode and the
    exception never escapes ``app()``.

    Retargeting the class attribute is the seam both click and typer read
    (``sys.exit(e.exit_code)``), and it covers BadParameter, MissingParameter,
    NoSuchOption and BadOptionUsage at once, since all inherit it.

    Typer vendors its own copy of click as ``typer._click``, so the public
    ``click.UsageError`` is a *different class object* from the one typer
    raises. Both are patched. The lookup is defensive: if a future typer drops
    the vendored module this degrades to patching public click only, and
    ``tests/test_exit_codes_documented.py`` fails loudly rather than silently
    reverting to 2.
    """
    seen: set[int] = set()
    for module in (click, getattr(typer, "_click", None)):
        exceptions = getattr(module, "exceptions", None)
        usage_error = getattr(exceptions, "UsageError", None)
        if usage_error is not None and id(usage_error) not in seen:
            usage_error.exit_code = ExitCode.USAGE_ERROR
            seen.add(id(usage_error))


_retarget_usage_error_exit_code()

app = typer.Typer(
    name="devrepro",
    help="Project-aware developer-environment diagnostics, reproducibility "
    "snapshots, machine-to-machine diffs and explainable safe remediation.",
    no_args_is_help=True,
)

register_all(app)


def _version_callback(value: bool) -> None:
    """Print the installed version and exit.

    Eager, so it answers before Typer demands a subcommand — the bug-report
    template asks reporters for this and it has to work on its own.
    """
    if value:
        typer.echo(f"devrepro {__version__}")
        raise typer.Exit


@app.callback()
def _root(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the installed devrepro version and exit.",
    ),
) -> None:
    """Project-aware developer-environment diagnostics and safe remediation.

    This callback exists so ``--version`` has somewhere to live; Typer needs a
    root callback to hang a group-level option on.
    """


def _make_output_encoding_non_fatal() -> None:
    """Never let an unencodable character kill the CLI.

    The Windows console defaults to a legacy codepage (cp1252 here), which
    cannot represent characters that appear in ordinary output -- a single
    U+2192 in a remediation hint was enough to end `devrepro check` in a
    UnicodeEncodeError raised from deep inside the codecs module.

    Only the error handler is changed; the stream keeps its own encoding, so
    ASCII output is unchanged on every platform and a stray non-ASCII
    character degrades to a replacement character instead of aborting the run.
    Streams that cannot be reconfigured (a pipe wrapper, a captured buffer in
    tests) are left alone.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        # A stream may refuse: an already-detached buffer, or a wrapper
        # without the keyword. Non-fatal by definition.
        with contextlib.suppress(ValueError, OSError):
            reconfigure(errors="replace")


def main() -> None:
    _make_output_encoding_non_fatal()
    try:
        app()
    except SystemExit as exc:
        code = exc.code
        if isinstance(code, int):
            sys.exit(code)
        sys.exit(int(bool(code)))


if __name__ == "__main__":
    main()
