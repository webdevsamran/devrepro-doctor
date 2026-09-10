"""Build caches: where they are, and whether they are helping.

Two questions, and only the second one is interesting.

The first is "how big is it", which every disk-usage tool answers and which is
expensive to answer here -- walking a 40 GB Gradle cache on every scan would
undo the performance work outright. So the cache inventory is presence-only,
and each entry carries the command that sizes it. Reporting a path and a
one-line command is more useful than a number nobody asked for and slower than
both.

The second is **whether the cache is earning its place**, and nothing reports
it. A compiler cache with a 15% hit rate is not saving time, it is spending it:
every miss pays the lookup, the write, and the eviction on top of the compile.
The usual cause is a cache smaller than the working set, so it evicts what it
is about to need -- and the symptom is "builds got slower after we enabled
caching", which nobody attributes to the cache. `ccache` and `sccache` both
publish those numbers; this reads them.

Parsing is separate from collection so both stat formats -- ccache 3 and
ccache 4 changed the layout completely -- can be tested from a machine with
neither installed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "CACHE_LOCATIONS",
    "MIN_CALLS_FOR_A_VERDICT",
    "CacheLocation",
    "CompilerCacheStats",
    "parse_ccache_stats",
    "parse_sccache_stats",
    "sizing_command",
]

#: Below this many cacheable calls, a hit rate is noise. A fresh cache on its
#: first build is 0% by definition, and reporting that as a problem would train
#: people to ignore the finding that matters.
MIN_CALLS_FOR_A_VERDICT = 50

#: A hit rate below this is costing more than it saves. Deliberately low: a
#: cache doing genuine work sits far above it, so a finding here means
#: something is actually wrong rather than merely suboptimal.
POOR_HIT_RATE = 0.30


@dataclass(frozen=True)
class CompilerCacheStats:
    """What a compiler cache says about its own effectiveness."""

    tool: str
    hits: int | None = None
    misses: int | None = None
    size_bytes: int | None = None
    max_size_bytes: int | None = None

    @property
    def calls(self) -> int | None:
        if self.hits is None or self.misses is None:
            return None
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float | None:
        total = self.calls
        if not total:
            return None
        return (self.hits or 0) / total

    @property
    def near_capacity(self) -> bool | None:
        """A cache at its ceiling evicts what it is about to need again.

        This is usually the *cause* of a low hit rate rather than a separate
        problem, which is why both are reported: the rate is the symptom and
        the ceiling is the thing to change.
        """
        if not self.size_bytes or not self.max_size_bytes:
            return None
        return self.size_bytes / self.max_size_bytes >= 0.95


_UNITS = {
    "b": 1,
    "kb": 1000,
    "mb": 1000**2,
    "gb": 1000**3,
    "tb": 1000**4,
    "kib": 1024,
    "mib": 1024**2,
    "gib": 1024**3,
    "tib": 1024**4,
}


def _size(value: str | None, unit: str | None = None) -> int | None:
    if not value:
        return None
    try:
        number = float(value.replace(",", ""))
    except ValueError:
        return None
    return int(number * _UNITS.get((unit or "b").strip().lower(), 1))


#: ccache 4: `  Hits:  900 / 1234 (72.93 %)`
_CC4_HITS = re.compile(r"^\s*Hits:\s+([\d,]+)\s*/\s*([\d,]+)", re.MULTILINE)
#: ccache 4: `  Cache size (GB): 4.20 / 5.00 (84.00 %)`
_CC4_SIZE = re.compile(r"Cache size \((\w+)\):\s*([\d.,]+)\s*/\s*([\d.,]+)", re.IGNORECASE)

#: ccache 3: separate lines, no totals.
_CC3_HIT_DIRECT = re.compile(r"^cache hit \(direct\)\s+([\d,]+)", re.MULTILINE)
_CC3_HIT_PRE = re.compile(r"^cache hit \(preprocessed\)\s+([\d,]+)", re.MULTILINE)
_CC3_MISS = re.compile(r"^cache miss\s+([\d,]+)", re.MULTILINE)
_CC3_SIZE = re.compile(r"^cache size\s+([\d.,]+)\s*(\w+)", re.MULTILINE)
_CC3_MAX = re.compile(r"^max cache size\s+([\d.,]+)\s*(\w+)", re.MULTILINE)


def parse_ccache_stats(text: str) -> CompilerCacheStats:
    """Read `ccache -s`, in either the version 3 or version 4 layout.

    The two are not variations on a theme: version 4 prints totals with a
    percentage and version 3 prints separate counters with no totals at all. A
    parser written against one silently returns nothing on the other, and
    "nothing" here reads as "this cache is fine".
    """
    hits = misses = size = max_size = None

    modern = _CC4_HITS.search(text or "")
    if modern:
        hits = int(modern.group(1).replace(",", ""))
        total = int(modern.group(2).replace(",", ""))
        misses = max(total - hits, 0)
        size_match = _CC4_SIZE.search(text)
        if size_match:
            unit = size_match.group(1)
            size = _size(size_match.group(2), unit)
            max_size = _size(size_match.group(3), unit)
        return CompilerCacheStats("ccache", hits, misses, size, max_size)

    direct = _CC3_HIT_DIRECT.search(text or "")
    pre = _CC3_HIT_PRE.search(text or "")
    miss = _CC3_MISS.search(text or "")
    if direct or pre or miss:
        hits = int((direct.group(1) if direct else "0").replace(",", "")) + int(
            (pre.group(1) if pre else "0").replace(",", "")
        )
        misses = int((miss.group(1) if miss else "0").replace(",", ""))
        size_match = _CC3_SIZE.search(text)
        max_match = _CC3_MAX.search(text)
        if size_match:
            size = _size(size_match.group(1), size_match.group(2))
        if max_match:
            max_size = _size(max_match.group(1), max_match.group(2))

    return CompilerCacheStats("ccache", hits, misses, size, max_size)


_SCCACHE_HITS = re.compile(r"^Cache hits\s+([\d,]+)", re.MULTILINE)
_SCCACHE_MISSES = re.compile(r"^Cache misses\s+([\d,]+)", re.MULTILINE)
_SCCACHE_SIZE = re.compile(r"^Cache size\s+([\d.,]+)\s*(\w+)", re.MULTILINE)
_SCCACHE_MAX = re.compile(r"^Max cache size\s+([\d.,]+)\s*(\w+)", re.MULTILINE)


def parse_sccache_stats(text: str) -> CompilerCacheStats:
    """Read `sccache --show-stats`."""
    hits = _SCCACHE_HITS.search(text or "")
    misses = _SCCACHE_MISSES.search(text or "")
    size = _SCCACHE_SIZE.search(text or "")
    max_size = _SCCACHE_MAX.search(text or "")
    return CompilerCacheStats(
        "sccache",
        int(hits.group(1).replace(",", "")) if hits else None,
        int(misses.group(1).replace(",", "")) if misses else None,
        _size(size.group(1), size.group(2)) if size else None,
        _size(max_size.group(1), max_size.group(2)) if max_size else None,
    )


@dataclass(frozen=True)
class CacheLocation:
    """A build cache that exists on this machine."""

    tool: str
    path: str
    #: Whether an environment variable moved it from the default. Worth
    #: knowing: a cache redirected to a network share or a slow volume is a
    #: common and invisible cause of "builds are slow on this machine only".
    relocated: bool = False


#: Where each ecosystem keeps its cache, by platform. Presence only -- these
#: are never walked, because a Gradle cache is routinely tens of gigabytes and
#: the answer would cost more than the whole rest of the scan.
CACHE_LOCATIONS: tuple[tuple[str, str, str | None, str], ...] = (
    # (tool, posix path relative to home, windows path relative to LOCALAPPDATA, env var)
    ("pip", ".cache/pip", "pip/Cache", "PIP_CACHE_DIR"),
    ("uv", ".cache/uv", "uv/cache", "UV_CACHE_DIR"),
    ("poetry", ".cache/pypoetry", "pypoetry/Cache", "POETRY_CACHE_DIR"),
    ("npm", ".npm", "npm-cache", "npm_config_cache"),
    ("yarn", ".cache/yarn", "Yarn/Cache", "YARN_CACHE_FOLDER"),
    ("pnpm", ".local/share/pnpm/store", "pnpm/store", "PNPM_HOME"),
    ("cargo", ".cargo/registry", None, "CARGO_HOME"),
    ("go", ".cache/go-build", "go-build", "GOCACHE"),
    ("gradle", ".gradle/caches", None, "GRADLE_USER_HOME"),
    ("maven", ".m2/repository", None, "MAVEN_OPTS"),
    ("nuget", ".nuget/packages", None, "NUGET_PACKAGES"),
    ("composer", ".cache/composer", "Composer", "COMPOSER_CACHE_DIR"),
    ("bazel", ".cache/bazel", None, "TEST_TMPDIR"),
    ("ccache", ".cache/ccache", "ccache", "CCACHE_DIR"),
    ("turbo", ".turbo", "turbo", "TURBO_CACHE_DIR"),
)


def sizing_command(path: str, platform: str) -> str:
    """The one-liner that answers "how big is it", for the caller to run.

    Reporting the command rather than the number is the whole design: walking
    these directories is the expensive part, and a person who wants the figure
    can spend the seconds deliberately.
    """
    if platform == "windows":
        return f'Get-ChildItem -Recurse -File "{path}" | Measure-Object -Sum Length'
    return f'du -sh "{path}"'


def cache_locations(
    *, home: Path, local_app_data: Path | None, env: dict[str, str], platform: str
) -> tuple[CacheLocation, ...]:
    """Which caches exist here, and which were moved by an environment variable."""
    found: list[CacheLocation] = []
    for tool, posix_rel, windows_rel, env_var in CACHE_LOCATIONS:
        override = env.get(env_var)
        candidates: list[tuple[Path, bool]] = []
        if override:
            candidates.append((Path(override), True))
        if platform == "windows" and windows_rel and local_app_data:
            candidates.append((local_app_data / windows_rel, False))
        candidates.append((home / posix_rel, False))

        for candidate, relocated in candidates:
            try:
                if candidate.is_dir():
                    found.append(CacheLocation(tool, str(candidate), relocated))
                    break
            except OSError:  # pragma: no cover - permission-denied on a parent
                continue
    return tuple(found)
