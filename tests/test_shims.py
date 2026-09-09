"""Version-manager shims that are installed but bypassed.

A manager works by putting its shims early on PATH. When something prepends
itself, the manager keeps reporting the right version when asked directly while
every actual command resolves elsewhere -- `pyenv version` says 3.12 and
`python --version` says 3.9, with nothing anywhere reporting a problem.

Every case here is synthetic and platform-parameterised, so a Windows layout is
tested on Linux and vice versa.
"""

from __future__ import annotations

import pytest
from devrepro.platforms.shims import SHIM_MARKERS, analyse_shims, manager_for_path


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        ("/home/dev/.pyenv/shims", "pyenv"),
        ("/home/dev/.asdf/shims", "asdf"),
        ("/home/dev/.local/share/mise/shims", "mise"),
        ("/home/dev/.rbenv/shims", "rbenv"),
        ("/home/dev/.volta/bin", "volta"),
        ("/home/dev/.nvm/versions/node/v20.11.0/bin", "nvm"),
        ("/home/dev/.cargo/bin", "rustup"),
        ("/home/dev/miniconda3/bin", "conda"),
        ("/usr/bin", None),
        ("/usr/local/bin", None),
        ("/opt/company/tools", None),
    ],
)
def test_manager_is_identified_from_a_path_entry(entry: str, expected: str | None) -> None:
    assert manager_for_path(entry) == expected


def test_windows_layouts_are_recognised_on_any_host() -> None:
    """A Windows PATH is analysed correctly from a Linux CI leg."""
    assert manager_for_path(r"C:\\Users\\dev\\.pyenv\\shims", "windows") == "pyenv"
    assert manager_for_path(r"C:\\Users\\dev\\.volta\\bin", "windows") == "volta"


def test_every_marker_resolves_to_its_own_manager() -> None:
    """A marker that matched the wrong manager would misreport the cause."""
    for manager, markers in SHIM_MARKERS.items():
        for marker in markers:
            # Build a plausible entry around the marker. Trailing separators are
            # deliberately not added: `normalize_path` strips them, so a marker
            # that only matches with one is a marker that never matches.
            fragment = marker.replace(chr(92), "/").strip("/")
            entry = f"/home/dev/{fragment}/bin"
            assert manager_for_path(entry) == manager, (
                f"marker {marker!r} did not identify {manager!r} in {entry!r}"
            )


# ------------------------------------------------------------------ shadowing


def test_a_system_install_shadowing_a_shim_is_reported() -> None:
    """The failure this module exists for."""
    path = "/usr/bin:/home/dev/.pyenv/shims"
    resolutions = {"python": ["/usr/bin/python", "/home/dev/.pyenv/shims/python"]}

    result = analyse_shims(path, resolutions)

    assert result.has_conflict
    shadow = result.shadowed[0]
    assert shadow.tool == "python"
    assert shadow.manager == "pyenv"
    assert shadow.winning_path == "/usr/bin/python"
    assert shadow.winning_index < shadow.shim_index


def test_a_manager_that_wins_is_not_a_conflict() -> None:
    """Correct ordering is the normal case and must stay quiet."""
    path = "/home/dev/.pyenv/shims:/usr/bin"
    resolutions = {"python": ["/home/dev/.pyenv/shims/python", "/usr/bin/python"]}
    assert not analyse_shims(path, resolutions).has_conflict


def test_a_single_resolution_is_never_a_conflict() -> None:
    resolutions = {"python": ["/usr/bin/python"]}
    assert not analyse_shims("/usr/bin", resolutions).has_conflict


def test_a_manager_that_does_not_provide_the_tool_is_not_reported() -> None:
    """rustup owning .cargo/bin says nothing about `python`.

    Reporting every manager on PATH as conflicting with every tool would make
    the check noise, and noise gets switched off.
    """
    path = "/usr/bin:/usr/local/bin:/home/dev/.cargo/bin"
    resolutions = {"python": ["/usr/bin/python", "/usr/local/bin/python"]}
    assert not analyse_shims(path, resolutions).has_conflict


def test_one_report_per_tool() -> None:
    """Two shadowed shims for one tool is still one thing to fix."""
    path = "/usr/bin:/home/dev/.pyenv/shims:/home/dev/.asdf/shims"
    resolutions = {
        "python": [
            "/usr/bin/python",
            "/home/dev/.pyenv/shims/python",
            "/home/dev/.asdf/shims/python",
        ]
    }
    assert len(analyse_shims(path, resolutions).shadowed) == 1


def test_managers_on_path_records_precedence() -> None:
    path = "/usr/bin:/home/dev/.pyenv/shims:/home/dev/.volta/bin"
    result = analyse_shims(path, {})
    assert result.managers_on_path == {"pyenv": 1, "volta": 2}


def test_several_tools_are_each_reported() -> None:
    path = "/usr/bin:/home/dev/.pyenv/shims:/home/dev/.nvm/versions/node/v20/bin"
    resolutions = {
        "python": ["/usr/bin/python", "/home/dev/.pyenv/shims/python"],
        "node": ["/usr/bin/node", "/home/dev/.nvm/versions/node/v20/bin/node"],
    }
    result = analyse_shims(path, resolutions)
    assert {s.tool for s in result.shadowed} == {"python", "node"}
    assert {s.manager for s in result.shadowed} == {"pyenv", "nvm"}


def test_the_summary_names_both_paths() -> None:
    """A finding a reader can act on without opening the JSON."""
    resolutions = {"python": ["/usr/bin/python", "/home/dev/.pyenv/shims/python"]}
    shadow = analyse_shims("/usr/bin:/home/dev/.pyenv/shims", resolutions).shadowed[0]
    assert "/usr/bin/python" in shadow.summary
    assert "pyenv" in shadow.summary
    assert "/home/dev/.pyenv/shims/python" in shadow.summary


def test_an_empty_path_is_handled() -> None:
    result = analyse_shims("", {})
    assert result.managers_on_path == {}
    assert not result.has_conflict
