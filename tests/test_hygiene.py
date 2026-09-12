"""Filesystem and locale hygiene.

`PRODUCT_GAPS.md` claimed case-sensitivity diagnostics under "Where we are
ahead" while no such check existed anywhere. These tests cover the code that
makes the claim true, and in particular the branch that is easy to get exactly
backwards.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
from devrepro.platforms.hygiene import (
    RESERVED_WINDOWS_NAMES,
    detect_case_sensitivity,
    locale_info,
    reserved_name_conflicts,
    symlink_support,
)

if TYPE_CHECKING:
    from pathlib import Path

NL = chr(10)


# ------------------------------------------------------- case sensitivity


def test_case_sensitivity_is_detected_without_writing(tmp_path: Path) -> None:
    """The check must not create files. A scan does not write.

    The usual technique is to write `foo` and stat `FOO`; this asks about a
    path that already exists instead.
    """
    (tmp_path / "Readme.md").write_text("x", encoding="utf-8")
    before = sorted(p.name for p in tmp_path.iterdir())

    result = detect_case_sensitivity(tmp_path)

    assert sorted(p.name for p in tmp_path.iterdir()) == before, "the probe created a file"
    assert result.sensitive is not None
    assert result.probed_path == "Readme.md"


def test_reports_case_insensitive_when_recased_path_is_the_same_file(
    tmp_path: Path,
) -> None:
    """On a folding filesystem `Readme.md` and `rEADME.MD` are one file."""
    (tmp_path / "Readme.md").write_text("x", encoding="utf-8")
    result = detect_case_sensitivity(tmp_path)

    on_folding_fs = (tmp_path / "rEADME.MD").exists()
    assert result.sensitive is not on_folding_fs


def test_two_files_differing_only_in_case_means_case_sensitive(tmp_path: Path) -> None:
    """The branch that is easy to invert.

    A case-sensitive directory really can contain both `Alpha` and `alpha`. A
    check that only asked "does the re-cased name exist?" would see the second
    file and conclude the filesystem folds case -- exactly backwards. The real
    question is whether the two names are the *same file*.
    """
    # The pair has to be a `swapcase()` pair, because that is the transform the
    # detector applies. The first version of this test used "Alpha" and "alpha"
    # -- and `"Alpha".swapcase()` is `"aLPHA"`, so the detector never compared
    # the two files this fixture created. On Linux it took the "does not
    # resolve" branch and failed the assertion; on Windows the two names folded
    # together and it skipped. It had never once run green anywhere.
    first, second = "Alpha", "Alpha".swapcase()
    assert second == "aLPHA", "swapcase is what the detector uses; keep them in step"

    (tmp_path / first).write_text("one", encoding="utf-8")
    try:
        (tmp_path / second).write_text("two", encoding="utf-8")
    except OSError:  # pragma: no cover - platform-dependent
        pytest.skip("filesystem refused two names differing only in case")

    both_exist_separately = (tmp_path / first).read_text(encoding="utf-8") == "one"
    if not both_exist_separately:
        pytest.skip("filesystem folded the two names together")

    result = detect_case_sensitivity(tmp_path)
    assert result.sensitive is True
    assert "different files" in result.detail


def test_a_lone_entry_whose_recased_name_is_absent_is_also_case_sensitive(
    tmp_path: Path,
) -> None:
    """The realistic branch, and the one the suite never reached.

    Ordinary directories do not contain `swapcase()` pairs. What they contain
    is one file whose re-cased name simply does not resolve -- which is the
    same verdict by a different route, and was untested because the other test
    was accidentally exercising it while asserting the wrong message.
    """
    (tmp_path / "Alpha").write_text("one", encoding="utf-8")
    if (tmp_path / "aLPHA").exists():
        pytest.skip("filesystem folds case; the re-cased name resolves")

    result = detect_case_sensitivity(tmp_path)
    assert result.sensitive is True
    assert "names are distinct" in result.detail


def test_empty_directory_reports_unknown_rather_than_guessing(tmp_path: Path) -> None:
    result = detect_case_sensitivity(tmp_path)
    assert result.sensitive is None
    assert "no entry" in result.detail


def test_unreadable_directory_reports_unknown(tmp_path: Path) -> None:
    result = detect_case_sensitivity(tmp_path / "does-not-exist")
    assert result.sensitive is None


def test_a_name_with_no_letters_is_skipped(tmp_path: Path) -> None:
    """`1234` re-cases to itself and proves nothing."""
    (tmp_path / "1234").write_text("x", encoding="utf-8")
    assert detect_case_sensitivity(tmp_path).sensitive is None


# --------------------------------------------------------- reserved names


@pytest.mark.parametrize("name", ["aux.js", "CON", "com1.txt", "LPT9", "nul"])
def test_reserved_windows_names_are_found(tmp_path: Path, name: str) -> None:
    """A repository containing one of these cannot be cloned on Windows.

    Some of them cannot even be created here to test with: on Windows `nul`
    resolves to the null device, so the write succeeds and no file appears.
    That is the failure this check exists to predict, so the case is skipped
    rather than asserted -- the host is demonstrating the problem.
    """
    target = tmp_path / name
    target.write_text("x", encoding="utf-8")
    # `Path("nul").exists()` is True on Windows -- it is a device, not a file --
    # so existence proves nothing here. The question is whether a directory
    # entry appeared.
    if name not in {entry.name for entry in tmp_path.iterdir()}:
        pytest.skip(f"this platform cannot create {name!r} at all, which is the point")
    assert name in reserved_name_conflicts(tmp_path)


def test_reserved_name_matching_ignores_extension_and_case() -> None:
    """`aux.js` is as unusable as `AUX`; the rule is on the stem."""
    from devrepro.platforms.hygiene import RESERVED_WINDOWS_NAMES

    for candidate in ("aux.js", "AUX", "Com1.TXT", "lpt9.log"):
        stem = candidate.split(".", 1)[0].lower()
        assert stem in RESERVED_WINDOWS_NAMES
    for safe in ("context.py", "console.js", "auxiliary.md", "com10.txt"):
        stem = safe.split(".", 1)[0].lower()
        assert stem not in RESERVED_WINDOWS_NAMES


def test_ordinary_names_are_not_flagged(tmp_path: Path) -> None:
    for name in ("context.py", "console.js", "auxiliary.md", "component.tsx"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    assert reserved_name_conflicts(tmp_path) == []


def test_dependency_directories_are_not_walked(tmp_path: Path) -> None:
    """`node_modules` is someone else's problem and enormous."""
    buried = tmp_path / "node_modules" / "pkg"
    buried.mkdir(parents=True)
    (buried / "aux.js").write_text("x", encoding="utf-8")
    assert reserved_name_conflicts(tmp_path) == []


def test_nested_conflicts_are_reported_with_a_relative_path(tmp_path: Path) -> None:
    nested = tmp_path / "src" / "lib"
    nested.mkdir(parents=True)
    (nested / "prn.ts").write_text("x", encoding="utf-8")
    assert reserved_name_conflicts(tmp_path) == ["src/lib/prn.ts"]


def test_the_reserved_list_covers_the_documented_device_names() -> None:
    assert {"con", "prn", "aux", "nul"} <= RESERVED_WINDOWS_NAMES
    assert {f"com{i}" for i in range(1, 10)} <= RESERVED_WINDOWS_NAMES
    assert {f"lpt{i}" for i in range(1, 10)} <= RESERVED_WINDOWS_NAMES
    # COM0 and LPT0 are not reserved.
    assert "com0" not in RESERVED_WINDOWS_NAMES


# ---------------------------------------------------------------- symlinks


def test_symlink_support_is_reported_without_creating_one() -> None:
    """Trying to create a symlink is a write; the setting is readable instead."""
    result = symlink_support()
    if os.name != "nt":
        assert result.supported is True
    else:
        assert result.supported in (True, False, None)
    assert result.detail


# ----------------------------------------------------------------- locale


def test_locale_reports_the_encoding_a_subprocess_inherits() -> None:
    info = locale_info()
    assert info.preferred_encoding
    assert info.filesystem_encoding
    assert isinstance(info.is_utf8, bool)


def test_non_utf8_locale_explains_the_consequence() -> None:
    info = locale_info()
    if not info.is_utf8:
        assert "UnicodeEncodeError" in info.detail


def test_locale_reads_the_supplied_environment() -> None:
    info = locale_info({"LANG": "en_GB.UTF-8", "LC_ALL": "C"})
    assert info.lang == "en_GB.UTF-8"
    assert info.lc_all == "C"
