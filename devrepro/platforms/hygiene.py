"""Filesystem and locale hygiene: the environment facts that break checkouts.

These are the problems that do not look like environment problems. A repository
containing both `Config.py` and `config.py` clones fine on Linux and silently
loses a file on macOS. A file named `aux.js` cannot be checked out on Windows
at all. A build that parses dates differently on two machines is usually a
locale, not a bug.

Everything here is read-only, which shapes how it is done. Case sensitivity is
normally detected by writing two files whose names differ only in case; this
module instead asks the filesystem about a path that already exists, because
the project's promise is that a scan does not write. `PRODUCT_GAPS.md` claimed
case-sensitivity diagnostics for some time before any existed -- this is the
code that makes the claim true.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "RESERVED_WINDOWS_NAMES",
    "CaseSensitivity",
    "LocaleInfo",
    "SymlinkSupport",
    "detect_case_sensitivity",
    "locale_info",
    "reserved_name_conflicts",
    "symlink_support",
]

#: Device names DOS reserved, which Windows still refuses as filenames with or
#: without an extension. A repository containing one cannot be checked out
#: there at all -- git reports a cryptic failure rather than naming the file.
RESERVED_WINDOWS_NAMES = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
)

#: Directories never worth walking for a hygiene check.
_SKIP = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".tox"}


@dataclass(frozen=True)
class CaseSensitivity:
    """Whether a path distinguishes `Foo` from `foo`."""

    sensitive: bool | None
    probed_path: str | None
    detail: str


@dataclass(frozen=True)
class SymlinkSupport:
    """Whether this process could create a symlink."""

    supported: bool | None
    detail: str


@dataclass(frozen=True)
class LocaleInfo:
    """The locale and encoding a build will inherit."""

    preferred_encoding: str
    filesystem_encoding: str
    lang: str | None
    lc_all: str | None
    is_utf8: bool
    detail: str


def detect_case_sensitivity(root: Path | str) -> CaseSensitivity:
    """Is this directory's filesystem case-sensitive?

    Determined without writing anything. An existing entry's name is re-cased
    and looked up again: if the re-cased path resolves to *the same file*, the
    filesystem folded the case. If it resolves to a different file, both names
    genuinely exist and the filesystem is case-sensitive.

    That last distinction matters. A case-sensitive directory really can hold
    both `README` and `readme`, and a check that only asked "does the re-cased
    path exist?" would call that case-insensitive -- exactly backwards.
    """
    root = Path(root)
    try:
        entries = list(root.iterdir())
    except OSError as exc:
        return CaseSensitivity(None, None, f"could not read {root}: {exc}")

    for entry in entries:
        name = entry.name
        swapped = name.swapcase()
        if swapped == name:
            continue  # no alphabetic characters to re-case
        other = root / swapped
        if not other.exists():
            return CaseSensitivity(
                True,
                name,
                f"{swapped!r} does not resolve while {name!r} does; names are distinct.",
            )
        try:
            if entry.samefile(other):
                return CaseSensitivity(
                    False,
                    name,
                    f"{name!r} and {swapped!r} are the same file; the filesystem folds case.",
                )
        except OSError:  # pragma: no cover - racy or permission-denied entry
            continue
        return CaseSensitivity(
            True,
            name,
            f"{name!r} and {swapped!r} are different files, so both names exist.",
        )

    return CaseSensitivity(None, None, "no entry with alphabetic characters to test.")


def reserved_name_conflicts(root: Path | str, *, max_depth: int = 4) -> list[str]:
    """Repository paths Windows cannot check out.

    Reserved device names are refused with or without an extension, so `aux.js`
    is as unusable as `aux`. Reported on every platform, not just Windows: the
    point is to warn the person who is about to commit one, who is often not
    the person who will fail to clone it.
    """
    root = Path(root)
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).relative_to(root).parts)
        if depth >= max_depth:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if d not in _SKIP and not d.startswith(".")]
        for name in [*dirnames, *filenames]:
            stem = name.split(".", 1)[0].lower()
            if stem in RESERVED_WINDOWS_NAMES:
                rel = Path(dirpath).relative_to(root) / name
                found.append(rel.as_posix())
    return sorted(found)


def symlink_support() -> SymlinkSupport:
    """Can this process create a symlink?

    On POSIX the answer is yes. On Windows it depends on Developer Mode or the
    SeCreateSymbolicLinkPrivilege, and the usual way to find out is to try --
    which is a write. The registry value Developer Mode sets is documented and
    readable, so it is read instead.

    Git checkouts of repositories containing symlinks silently substitute plain
    text files when this is unavailable, which produces a working tree that
    differs from the commit without anything reporting an error.
    """
    if os.name != "nt":
        return SymlinkSupport(True, "POSIX: symlink creation is unprivileged.")

    try:
        # Windows-only module: present for mypy on Windows, absent on the
        # Linux and macOS legs of the matrix. `unused-ignore` makes the
        # comment correct on all three rather than on whichever one the
        # author happened to be using.
        import winreg  # type: ignore[import-not-found,unused-ignore]

        key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:  # type: ignore[attr-defined]
            value, _ = winreg.QueryValueEx(key, "AllowDevelopmentWithoutDevLicense")  # type: ignore[attr-defined]
        if int(value) == 1:
            return SymlinkSupport(True, "Developer Mode is on, so symlink creation is permitted.")
        return SymlinkSupport(
            False,
            "Developer Mode is off. Git will materialise symlinks as plain files "
            "unless this process holds SeCreateSymbolicLinkPrivilege.",
        )
    except FileNotFoundError:
        return SymlinkSupport(
            False,
            "Developer Mode has never been enabled (registry value absent). Git "
            "will materialise symlinks as plain files.",
        )
    except OSError as exc:
        return SymlinkSupport(None, f"could not read the Developer Mode setting: {exc}")


def locale_info(env: dict[str, str] | None = None) -> LocaleInfo:
    """The text encoding a subprocess will inherit.

    A non-UTF-8 preferred encoding is the reason a build that handles an
    accented filename or a unicode test fixture on one machine raises
    UnicodeDecodeError on another. It is also why this project's own CLI once
    died writing a right-arrow to a Windows console.
    """
    import locale as _locale

    env = dict(os.environ) if env is None else env
    preferred = _locale.getpreferredencoding(False)
    fs_encoding = sys.getfilesystemencoding()
    lang = env.get("LANG")
    lc_all = env.get("LC_ALL")
    is_utf8 = "utf-8" in preferred.lower().replace("_", "-")

    if is_utf8:
        detail = f"Preferred encoding is {preferred}; text handling is UTF-8."
    else:
        detail = (
            f"Preferred encoding is {preferred}, not UTF-8. Tools that write "
            "non-ASCII output can fail with UnicodeEncodeError, and files with "
            "accented names may not round-trip."
        )
    return LocaleInfo(
        preferred_encoding=preferred,
        filesystem_encoding=fs_encoding,
        lang=lang,
        lc_all=lc_all,
        is_utf8=is_utf8,
        detail=detail,
    )
