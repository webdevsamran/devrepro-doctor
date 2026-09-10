"""Whether a prebuilt binary can actually load here.

Package managers ship compiled artefacts, and they choose which one to download
from three facts about the machine: its architecture, its C library, and the
version of that library. Get any of them wrong and the failure is loud, late,
and about something else entirely.

* **An x86_64 interpreter on an arm64 host.** Every wheel and every prebuilt
  addon it downloads is x86_64, everything runs under translation, and the
  machine reports itself as arm64 the whole time. `pip install` succeeds. The
  build takes ten times as long, and a native extension compiled here does not
  load in a colleague's arm64 process.
* **musl instead of glibc.** Alpine is the common case. A `manylinux` wheel is
  linked against glibc and simply will not load, so pip silently falls back to
  building from source -- if a compiler is present, which on a slim image it is
  not. The error names a missing header.
* **glibc older than the wheel tag.** `manylinux_2_28` needs glibc 2.28. On an
  older distribution pip skips those wheels for the same silent fallback, and
  `pip install numpy` becomes a fifteen-minute compile that fails.

Everything here is derived from strings the machine already reports. Parsing is
separate from collection, as everywhere else, so a musl host and an arm64 Mac
can both be tested from a machine that is neither.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "MANYLINUX_GLIBC",
    "AbiFacts",
    "compare_arch",
    "normalise_arch",
    "parse_libc",
    "wheel_tags_for_glibc",
]

#: The glibc floor each `manylinux` tag requires. A machine below the floor
#: cannot install wheels carrying that tag, and pip does not say so: it falls
#: back to building from source and reports whatever the compiler reports.
MANYLINUX_GLIBC: tuple[tuple[str, tuple[int, int]], ...] = (
    ("manylinux1", (2, 5)),
    ("manylinux2010", (2, 12)),
    ("manylinux2014", (2, 17)),
    ("manylinux_2_17", (2, 17)),
    ("manylinux_2_24", (2, 24)),
    ("manylinux_2_28", (2, 28)),
    ("manylinux_2_34", (2, 34)),
)

#: The tag most widely published today. A machine below this floor is one where
#: "just pip install it" stops being true for a large part of the ecosystem.
COMMON_MANYLINUX = "manylinux_2_28"

#: Architecture names as each source spells them. Python reports `AMD64` on
#: Windows and `arm64` on Apple silicon; uname says `x86_64` and `aarch64`;
#: Node says `x64` and `arm64`. Comparing any two raw is how a tool ends up
#: reporting every Windows machine as mismatched with itself.
_ARCH_ALIASES: dict[str, str] = {
    "amd64": "x86_64",
    "x86_64": "x86_64",
    "x64": "x86_64",
    "x86-64": "x86_64",
    "i386": "x86",
    "i686": "x86",
    "x86": "x86",
    "ia32": "x86",
    "win32": "x86",
    "arm64": "aarch64",
    "aarch64": "aarch64",
    "armv8": "aarch64",
    "arm": "arm",
    "armv7l": "arm",
    "ppc64le": "ppc64le",
    "s390x": "s390x",
    "riscv64": "riscv64",
}


def normalise_arch(arch: str | None) -> str | None:
    """One spelling per architecture, or None when the name is unknown.

    Returning None for an unrecognised name is deliberate: an unknown
    architecture compared against a known one must not look like a mismatch.
    """
    if not arch:
        return None
    return _ARCH_ALIASES.get(arch.strip().lower())


def compare_arch(a: str | None, b: str | None) -> bool | None:
    """True if the same, False if genuinely different, None if unknowable."""
    left, right = normalise_arch(a), normalise_arch(b)
    if left is None or right is None:
        return None
    return left == right


@dataclass(frozen=True)
class LibcInfo:
    flavour: str | None  # glibc | musl | None
    version: tuple[int, ...] | None = None
    raw: str | None = None

    @property
    def version_text(self) -> str | None:
        return ".".join(str(part) for part in self.version) if self.version else None


_FLAVOUR = re.compile(r"(musl|glibc|GNU libc)", re.IGNORECASE)

#: musl announces itself as `musl libc (x86_64)` and puts the version on the
#: *next* line, after the word `Version`.
_MUSL_VERSION = re.compile(r"^Version\s+([0-9]+(?:\.[0-9]+)*)", re.IGNORECASE | re.MULTILINE)

#: glibc's banner ends with the version: `ldd (Ubuntu GLIBC 2.39-0ubuntu8.3) 2.39`.
#: Anchored on a word boundary and requiring a dot, so it cannot match the `86`
#: inside `x86_64` -- which is exactly what a looser pattern did, reporting
#: musl 86 on every Alpine machine.
_DOTTED_VERSION = re.compile(r"(?<![\w.])([0-9]+\.[0-9]+(?:\.[0-9]+)?)(?![\w.])")


def parse_libc(text: str | None) -> LibcInfo:
    """Read a libc flavour and version out of `ldd --version`.

    musl prints its banner to *stderr* and exits non-zero, which is why the
    caller has to pass both streams: a check that only reads stdout on success
    concludes there is no libc at all on exactly the systems where knowing
    matters most.

    The two formats need separate patterns. glibc puts its version at the end
    of the first line; musl puts it on the second, and its first line contains
    `x86_64` -- so a pattern that simply looks for the next digits after the
    flavour name finds the `86` and reports musl 86.
    """
    if not text or not text.strip():
        return LibcInfo(None)

    first_line = text.strip().splitlines()[0][:120]
    flavour_match = _FLAVOUR.search(text)
    if not flavour_match:
        return LibcInfo(None, raw=first_line)

    flavour = "musl" if "musl" in flavour_match.group(1).lower() else "glibc"
    raw_version: str | None = None
    if flavour == "musl":
        musl = _MUSL_VERSION.search(text)
        raw_version = musl.group(1) if musl else None
    else:
        # The last dotted number on the banner line: the Ubuntu form carries a
        # packaging version first and the libc version last.
        candidates = _DOTTED_VERSION.findall(first_line)
        raw_version = candidates[-1] if candidates else None

    version = tuple(int(part) for part in raw_version.split(".")) if raw_version else None
    return LibcInfo(flavour, version, first_line)


def wheel_tags_for_glibc(version: tuple[int, ...] | None) -> tuple[str, ...]:
    """Which `manylinux` tags this glibc can install.

    Returns an empty tuple for an unknown version rather than guessing at the
    permissive answer -- claiming a machine supports every tag is the direction
    that produces a silent source build later.
    """
    if not version or len(version) < 2:
        return ()
    current = (version[0], version[1])
    return tuple(tag for tag, floor in MANYLINUX_GLIBC if current >= floor)


@dataclass(frozen=True)
class AbiFacts:
    """What decides which prebuilt artefact a package manager will fetch."""

    host_arch: str | None = None
    #: The architecture of the process asking for packages, which is not
    #: necessarily the machine's.
    interpreter_arch: str | None = None
    translated: bool | None = None
    libc: LibcInfo | None = None
    #: `(runtime name, reported arch)` for each runtime that answered.
    runtime_arches: tuple[tuple[str, str], ...] = ()

    @property
    def arch_matches(self) -> bool | None:
        return compare_arch(self.host_arch, self.interpreter_arch)

    @property
    def supported_wheel_tags(self) -> tuple[str, ...]:
        if not self.libc or self.libc.flavour != "glibc":
            return ()
        return wheel_tags_for_glibc(self.libc.version)
