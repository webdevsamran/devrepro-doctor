"""DevRepro Doctor CLI.

All major commands support --json and stable exit codes:
  0 READY · 1 READY_WITH_WARNINGS · 2 BLOCKED · 3 INTERNAL_ERROR · 4 USAGE

The command surface lives in ``devrepro.cli.commands`` — one module per
domain, each exposing a single ``register(app)`` hook. Commands stay flat
(``devrepro doctor``, never ``devrepro diagnostics doctor``) while the code
is split by domain for reviewable, conflict-free contributions.
"""

from __future__ import annotations

import sys

import typer

from devrepro.cli.commands import register_all

app = typer.Typer(
    name="devrepro",
    help="Project-aware developer-environment diagnostics, reproducibility "
    "snapshots, machine-to-machine diffs and explainable safe remediation.",
    no_args_is_help=True,
)

register_all(app)


def main() -> None:
    try:
        app()
    except SystemExit as exc:
        code = exc.code
        if isinstance(code, int):
            sys.exit(code)
        sys.exit(int(bool(code)))


if __name__ == "__main__":
    main()
