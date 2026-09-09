"""`devrepro --version` has to work, and report the real version.

`__version__` was already derived from installed metadata (see
`devrepro/__init__.py`), but nothing exposed it on the command line: the flag
exited 2 with "No such option". A version you cannot ask the tool for is not
much use to a bug reporter.
"""

from __future__ import annotations

import pathlib
import tomllib

from devrepro import __version__
from devrepro.cli.app import app
from typer.testing import CliRunner

runner = CliRunner()
PYPROJECT = pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml"


def _declared_version() -> str:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def test_package_version_matches_pyproject() -> None:
    assert __version__ == _declared_version()


def test_version_flag_exits_zero_and_prints_the_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0, result.output
    assert __version__ in result.output


def test_version_flag_does_not_require_a_subcommand() -> None:
    """The app is `no_args_is_help=True`; an eager callback must still answer."""
    result = runner.invoke(app, ["--version"])
    assert "Usage:" not in result.output


def test_adding_the_callback_did_not_hide_the_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for expected in ("doctor", "check", "preflight", "snapshot"):
        assert expected in result.output
