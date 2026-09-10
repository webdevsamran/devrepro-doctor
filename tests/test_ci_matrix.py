"""A CI matrix is a set of versions, not a wildcard.

`${{ matrix.python-version }}` is a template rather than a version, and the
parser normalised every template to `"*"`. So this repository's own workflow --
three operating systems by four Python versions -- reached the local-vs-CI
check as "CI declares anything", and the check that exists to catch "CI passes,
my machine fails" said nothing about the twelve legs most likely to catch it.

These tests cover both YAML sequence styles, `include:` legs that sit outside
the cross-product, and the case that matters most for honesty: a reference the
parser cannot resolve stays a wildcard rather than being guessed at.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from devrepro.project.ci_parsers import (
    collect_ci_toolchains,
    parse_workflow_matrices,
)

if TYPE_CHECKING:
    from pathlib import Path

NL = chr(10)


def workflow(tmp_path: Path, body: str, name: str = "ci.yml") -> Path:
    directory = tmp_path / ".github" / "workflows"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(body, encoding="utf-8")
    return path


FLOW_STYLE = """
name: CI
on: [push]
jobs:
  test:
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest, macos-latest]
        python-version: ["3.11", "3.12", "3.13", "3.14"]
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-python@v6
        with:
          python-version: ${{ matrix.python-version }}
"""

BLOCK_STYLE = """
name: CI
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version:
          - "3.11"
          - "3.12"
        node-version:
          - 20
          - 22
    steps:
      - uses: actions/setup-python@v6
        with:
          python-version: ${{ matrix.python-version }}
      - uses: actions/setup-node@v7
        with:
          node-version: ${{ matrix.node-version }}
"""


# ------------------------------------------------------------ matrix parsing


def test_a_flow_sequence_is_read() -> None:
    axes = parse_workflow_matrices(FLOW_STYLE.splitlines())
    assert axes["test"]["python-version"] == ("3.11", "3.12", "3.13", "3.14")
    assert axes["test"]["os"] == ("ubuntu-latest", "windows-latest", "macos-latest")


def test_quotes_survive_the_comma_split() -> None:
    """The bug this feature found in a helper older than it.

    `_unquote` stripped quotes before whitespace, so splitting
    `["3.11", "3.12"]` on commas produced ` "3.12"`, whose first character is a
    space -- only the trailing quote came off, leaving `"3.12`.
    """
    axes = parse_workflow_matrices(FLOW_STYLE.splitlines())
    for value in axes["test"]["python-version"]:
        assert '"' not in value
        assert value == value.strip()


def test_a_block_sequence_is_read() -> None:
    axes = parse_workflow_matrices(BLOCK_STYLE.splitlines())
    assert axes["test"]["python-version"] == ("3.11", "3.12")
    assert axes["test"]["node-version"] == ("20", "22")


def test_include_legs_contribute_their_versions() -> None:
    """A version tested only via `include:` is still a version CI tests."""
    body = """
jobs:
  test:
    strategy:
      matrix:
        python-version: ["3.11"]
        include:
          - python-version: "3.14"
            experimental: true
    steps:
      - uses: actions/setup-python@v6
        with:
          python-version: ${{ matrix.python-version }}
"""
    axes = parse_workflow_matrices(body.splitlines())
    assert axes["test"]["python-version"] == ("3.11", "3.14")


def test_fail_fast_is_not_mistaken_for_an_axis() -> None:
    axes = parse_workflow_matrices(FLOW_STYLE.splitlines())
    assert "fail-fast" not in axes["test"]


def test_each_job_keeps_its_own_matrix() -> None:
    body = """
jobs:
  unit:
    strategy:
      matrix:
        python-version: ["3.11", "3.12"]
    steps:
      - run: pytest
  lint:
    strategy:
      matrix:
        python-version: ["3.12"]
    steps:
      - run: ruff check .
"""
    axes = parse_workflow_matrices(body.splitlines())
    assert axes["unit"]["python-version"] == ("3.11", "3.12")
    assert axes["lint"]["python-version"] == ("3.12",)


def test_a_job_without_a_matrix_is_absent_not_empty() -> None:
    """ "No matrix" and "a matrix we could not read" are different claims."""
    body = """
jobs:
  docs:
    runs-on: ubuntu-latest
    steps:
      - run: mkdocs build --strict
"""
    assert parse_workflow_matrices(body.splitlines()) == {}


@pytest.mark.parametrize(
    "body",
    ["", "jobs:", "name: CI" + NL + "on: [push]"],
)
def test_a_workflow_with_nothing_to_read_is_not_an_error(body: str) -> None:
    assert parse_workflow_matrices(body.splitlines()) == {}


def test_a_declared_but_unreadable_matrix_is_distinguishable_from_none() -> None:
    """The distinction the return type exists to carry.

    A job with `matrix:` and no axis this parser could read appears with an
    empty mapping; a job with no matrix at all does not appear. Collapsing the
    two would let "we could not read your matrix" be reported as "you have no
    matrix", which is the wrong thing to tell someone debugging a twelve-leg
    workflow.
    """
    declared = "jobs:" + NL + "  test:" + NL + "    strategy:" + NL + "      matrix:"
    assert parse_workflow_matrices(declared.splitlines()) == {"test": {}}

    absent = "jobs:" + NL + "  test:" + NL + "    steps:" + NL + "      - run: pytest"
    assert parse_workflow_matrices(absent.splitlines()) == {}


# ---------------------------------------------------------------- resolution


def test_a_matrix_reference_becomes_the_versions_it_stands_for(tmp_path: Path) -> None:
    workflow(tmp_path, FLOW_STYLE)
    specs = sorted(t.spec for t in collect_ci_toolchains(tmp_path) if t.tool == "python")
    assert specs == ["3.11", "3.12", "3.13", "3.14"]


def test_the_runner_matrix_resolves_into_the_platform_hint(tmp_path: Path) -> None:
    workflow(tmp_path, FLOW_STYLE)
    python = [t for t in collect_ci_toolchains(tmp_path) if t.tool == "python"]
    assert python
    assert "windows-latest" in (python[0].platform or "")


def test_an_unresolvable_reference_stays_a_wildcard(tmp_path: Path) -> None:
    """The honest answer for an axis built by `fromJSON` or a reusable workflow.

    "This is templated and we could not read it" is not the same claim as
    "this accepts any version", but a wildcard is the only one of the two this
    module can currently express -- so it must not be reached by guessing.
    """
    body = """
jobs:
  test:
    strategy:
      matrix:
        python-version: ${{ fromJSON(needs.setup.outputs.versions) }}
    steps:
      - uses: actions/setup-python@v6
        with:
          python-version: ${{ matrix.python-version }}
"""
    workflow(tmp_path, body)
    specs = [t.spec for t in collect_ci_toolchains(tmp_path) if t.tool == "python"]
    assert specs == ["*"]


def test_a_reference_to_an_undeclared_axis_stays_a_wildcard(tmp_path: Path) -> None:
    body = """
jobs:
  test:
    strategy:
      matrix:
        os: [ubuntu-latest]
    steps:
      - uses: actions/setup-python@v6
        with:
          python-version: ${{ matrix.python-version }}
"""
    workflow(tmp_path, body)
    specs = [t.spec for t in collect_ci_toolchains(tmp_path) if t.tool == "python"]
    assert specs == ["*"]


def test_a_literal_pin_is_untouched(tmp_path: Path) -> None:
    body = """
jobs:
  docs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"
"""
    workflow(tmp_path, body)
    specs = [t.spec for t in collect_ci_toolchains(tmp_path) if t.tool == "python"]
    assert specs == ["3.12"]


def test_two_toolchains_in_one_matrix_both_resolve(tmp_path: Path) -> None:
    workflow(tmp_path, BLOCK_STYLE)
    found = collect_ci_toolchains(tmp_path)
    assert sorted(t.spec for t in found if t.tool == "python") == ["3.11", "3.12"]
    assert sorted(t.spec for t in found if t.tool == "node") == ["20", "22"]


def test_this_repository_declares_four_pythons_not_a_wildcard() -> None:
    """The finding that motivated this, checked against the real workflow.

    If someone narrows the matrix to one version, this fails and the reason is
    visible in the diff rather than in a silently weaker check.
    """
    from pathlib import Path as _Path

    root = _Path(__file__).resolve().parent.parent
    specs = {t.spec for t in collect_ci_toolchains(root) if t.tool == "python"}
    assert "*" not in specs
    assert {"3.11", "3.12", "3.13", "3.14"} <= specs
