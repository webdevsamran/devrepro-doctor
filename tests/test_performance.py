"""Performance guards for the paths that dominate a scan.

A diagnostic tool competes with the developer's patience. `devrepro doctor`
took 26 seconds on this machine, of which 16 were spent resolving PATH -- and
`docs/MCP-EXPOSURE.md` names exactly that cost as a reason not to expose scans
to an agent: "fine for a CLI and slow for an interactive tool call".

The cause was algorithmic. `resolve_all_on_path` tested each candidate filename
against the filesystem, and on Windows a 45-entry PATH times 14 PATHEXT
variants is 630 filesystem calls per tool, most for paths that do not exist --
and it called `Path.resolve()`, the expensive part, *before* checking existence.
Listing each directory once made the same work 25 times faster with identical
results.

These thresholds are deliberately loose. They exist to catch a return to
per-candidate stat-ing, not to police normal variation on a shared CI runner.
"""

from __future__ import annotations

import os
import time

import pytest
from devrepro.probes.helpers import resolve_all_on_path
from devrepro.probes.toolchains import TOOL_SPECS


def _synthetic_path(entries: int, tmp_path) -> str:
    """A PATH with many real directories, most containing nothing we want."""
    dirs = []
    for i in range(entries):
        d = tmp_path / f"dir{i:03d}"
        d.mkdir()
        (d / f"unrelated{i}.txt").write_text("x", encoding="utf-8")
        dirs.append(str(d))
    return os.pathsep.join(dirs)


@pytest.mark.parametrize("entries", [60])
def test_resolution_scales_with_directories_not_candidates(entries: int, tmp_path) -> None:
    """Resolving many tools over a long PATH must stay cheap.

    Sixty directories and every tool spec is roughly the shape of a developer
    machine. The per-candidate implementation took seconds here; listing each
    directory once takes milliseconds, because the work is now proportional to
    the number of directories rather than directories times candidates.
    """
    path = _synthetic_path(entries, tmp_path)

    start = time.perf_counter()
    for spec in TOOL_SPECS:
        for command in spec.commands:
            resolve_all_on_path(command, path_env=path)
    elapsed = time.perf_counter() - start

    assert elapsed < 5.0, (
        f"resolving {len(TOOL_SPECS)} tool specs over {entries} PATH entries took "
        f"{elapsed:.2f}s. That is the shape of the regression this guards: "
        "stat-ing every candidate rather than listing each directory once."
    )


def test_a_missing_directory_is_skipped_cheaply(tmp_path) -> None:
    """Dead PATH entries are common and must not cost anything."""
    dead = os.pathsep.join(str(tmp_path / f"nope{i}") for i in range(200))

    start = time.perf_counter()
    for _ in range(20):
        resolve_all_on_path("python", path_env=dead)
    elapsed = time.perf_counter() - start

    assert elapsed < 2.0, f"200 dead PATH entries took {elapsed:.2f}s to skip"
    assert resolve_all_on_path("python", path_env=dead) == []


def test_resolution_still_finds_what_is_there(tmp_path) -> None:
    """Speed is worthless if the answer changed.

    The optimisation is only valid because it returns exactly what the previous
    implementation did; this pins the behaviour the timing tests protect.
    """
    first = tmp_path / "a"
    second = tmp_path / "b"
    first.mkdir()
    second.mkdir()
    name = "mytool.exe" if os.name == "nt" else "mytool"
    (first / name).write_text("#!/bin/sh", encoding="utf-8")
    (second / name).write_text("#!/bin/sh", encoding="utf-8")
    if os.name != "nt":
        for d in (first, second):
            (d / name).chmod(0o755)

    found = resolve_all_on_path("mytool", path_env=os.pathsep.join([str(first), str(second)]))

    assert len(found) == 2, f"expected both installations, got {found}"
    assert str(first) in found[0], "precedence order was not preserved"


def test_a_directory_on_path_is_not_matched_as_an_executable(tmp_path) -> None:
    """A subdirectory named like the tool is not the tool."""
    entry = tmp_path / "bin"
    entry.mkdir()
    (entry / "mytool").mkdir()
    assert resolve_all_on_path("mytool", path_env=str(entry)) == []
