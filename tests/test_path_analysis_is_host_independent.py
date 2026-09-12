"""Reading another machine's PATH must not depend on the machine reading it.

This project's premise is that one machine's report is read somewhere else: a
snapshot diffed on a colleague's laptop, a fleet console rendering Windows
agents from a Linux server, a CI job explaining why a developer's PATH resolves
differently. Every one of those analyses a PATH belonging to a platform that is
not the host's.

Two functions took a `platform` argument and then ignored it:

* `normalize_path` called `os.path`, so a Windows PATH analysed on Linux kept
  its backslashes -- `manager_for_path` stopped recognising `.pyenv/shims`
  entirely -- and a Linux PATH analysed on Windows was lower-cased, making
  `/opt/Tools` and `/opt/tools` look like duplicate entries.
* `analyse_shims` built parent directories with `pathlib.Path`, which is also
  host-flavoured.

They hid each other. Both sides of every comparison were mangled the same way,
so the results matched and the tests passed -- on Windows. On Linux the first
one failed, and fixing it exposed the second.

The assertions below are all of the form "same input, same answer, either
host", which is the only property that would have caught either.
"""

from __future__ import annotations

import ntpath
import posixpath

import pytest
from devrepro.platforms.base import normalize_path, parent_dir
from devrepro.platforms.shims import analyse_shims, manager_for_path

WINDOWS_PATH = r"C:\Windows\System32;C:\Users\dev\.pyenv\shims;C:\Users\dev\.volta\bin"
POSIX_PATH = "/usr/bin:/home/dev/.pyenv/shims:/home/dev/.volta/bin"


@pytest.mark.parametrize(
    ("entry", "platform", "expected"),
    [
        # Windows: separators canonical, case folded -- on any host.
        (r"C:\Users\Dev\.pyenv\shims", "windows", r"c:\users\dev\.pyenv\shims"),
        (r"C:\Users\dev\..\dev\bin", "windows", r"c:\users\dev\bin"),
        ("C:/Users/Dev/bin", "windows", r"c:\users\dev\bin"),
        # POSIX: case preserved, because the filesystem preserves it.
        ("/opt/Tools", "linux", "/opt/Tools"),
        ("/opt/tools", "linux", "/opt/tools"),
        ("/usr/local/../bin", "linux", "/usr/bin"),
        ("/home/dev/.pyenv/shims", "macos", "/home/dev/.pyenv/shims"),
    ],
)
def test_normalize_path_answers_the_same_on_any_host(
    entry: str, platform: str, expected: str
) -> None:
    assert normalize_path(entry, platform) == expected


def test_two_posix_directories_differing_only_in_case_are_not_duplicates() -> None:
    """`ntpath.normcase` lower-cases. A Linux PATH read on Windows lost this."""
    assert normalize_path("/opt/Tools", "linux") != normalize_path("/opt/tools", "linux")


def test_two_windows_directories_differing_only_in_case_are_duplicates() -> None:
    """And the converse: Windows really does fold case, on every host."""
    assert normalize_path(r"C:\Tools", "windows") == normalize_path(r"c:\tools", "windows")


@pytest.mark.parametrize(
    ("path", "platform", "expected"),
    [
        ("/usr/bin/python", "linux", "/usr/bin"),
        (r"C:\Python312\python.exe", "windows", r"C:\Python312"),
        (r"C:\Users\dev\.pyenv\shims\python.exe", "windows", r"C:\Users\dev\.pyenv\shims"),
    ],
)
def test_parent_dir_uses_the_target_platforms_separator(
    path: str, platform: str, expected: str
) -> None:
    assert parent_dir(path, platform) == expected


@pytest.mark.parametrize(
    ("entry", "manager"),
    [
        (r"C:\Users\dev\.pyenv\shims", "pyenv"),
        (r"C:\Users\dev\.volta\bin", "volta"),
        (r"C:\Users\dev\.nvm\versions\node\v20.11.0\bin", "nvm"),
    ],
)
def test_windows_managers_are_recognised_from_a_posix_host(entry: str, manager: str) -> None:
    assert manager_for_path(entry, "windows") == manager


def test_a_windows_shim_conflict_is_found_from_any_host() -> None:
    """The whole failure this module reports, expressed in Windows paths.

    `python.exe` in System32 wins over the pyenv shim further down PATH. A
    Linux host used to return no manager for either directory, so the conflict
    was invisible in exactly the deployment -- a fleet server -- where somebody
    else's machine is the thing being explained.
    """
    resolutions = {
        "python": [
            r"C:\Windows\System32\python.exe",
            r"C:\Users\dev\.pyenv\shims\python.exe",
        ]
    }
    result = analyse_shims(WINDOWS_PATH, resolutions, platform="windows")

    assert result.has_conflict
    shadow = result.shadowed[0]
    assert shadow.manager == "pyenv"
    assert shadow.winning_path == r"C:\Windows\System32\python.exe"
    # Indices resolved: -1 here meant the directory matched no PATH entry,
    # which is what a host-flavoured `Path(...).parent` produced.
    assert shadow.winning_index == 0
    assert shadow.shim_index == 1
    assert shadow.winning_index < shadow.shim_index


def test_a_posix_shim_conflict_is_found_from_any_host() -> None:
    resolutions = {"python": ["/usr/bin/python", "/home/dev/.pyenv/shims/python"]}
    result = analyse_shims(POSIX_PATH, resolutions, platform="linux")

    shadow = result.shadowed[0]
    assert shadow.manager == "pyenv"
    assert shadow.winning_index == 0
    assert shadow.shim_index == 1


def test_the_standard_library_agrees_with_the_expectations_above() -> None:
    """Pins the premise rather than the implementation.

    If these ever stop holding, the table at the top of this file is wrong and
    should be re-derived -- not quietly adjusted until it passes.
    """
    assert ntpath.normcase(r"C:\Users\Dev") == r"c:\users\dev"
    assert posixpath.normcase("/opt/Tools") == "/opt/Tools"
    assert ntpath.dirname(r"C:\a\b.exe") == r"C:\a"
    assert posixpath.dirname("/a/b") == "/a"
