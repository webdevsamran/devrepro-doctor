"""Whether a build cache is earning its place, and how much disk is left.

A compiler cache with a 15% hit rate is not saving time, it is spending it:
every miss pays the lookup, the write and the eviction on top of the compile.
The usual cause is a cache smaller than the working set, and the symptom is
"builds got slower after we turned caching on" -- which nobody attributes to
the cache. Both `ccache` and `sccache` publish the numbers and nothing reads
them.

The other half is that nothing here walks a cache directory. A Gradle cache is
routinely tens of gigabytes and sizing one on every scan would undo the
performance work outright, so the inventory is presence-only and reports the
command instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from devrepro.core.models import FindingState, PlatformInfo
from devrepro.core.runner import CommandResult
from devrepro.platforms.caches import (
    MIN_CALLS_FOR_A_VERDICT,
    CompilerCacheStats,
    cache_locations,
    parse_ccache_stats,
    parse_sccache_stats,
    sizing_command,
)
from devrepro.probes.base import ProbeContext
from devrepro.probes.caches import CacheProbe

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

NL = chr(10)

CCACHE_4 = (
    "Cacheable calls:   1234 / 2000 (61.70 %)"
    + NL
    + "  Hits:             900 / 1234 (72.93 %)"
    + NL
    + "    Direct:         800 /  900 (88.89 %)"
    + NL
    + "    Preprocessed:   100 /  900 (11.11 %)"
    + NL
    + "  Misses:           334 / 1234 (27.07 %)"
    + NL
    + "Local storage:"
    + NL
    + "  Cache size (GB):   4.20 /  5.00 (84.00 %)"
    + NL
)

CCACHE_4_POOR = (
    "Cacheable calls:   1000 / 1000 (100.0 %)"
    + NL
    + "  Hits:             100 / 1000 (10.00 %)"
    + NL
    + "  Misses:           900 / 1000 (90.00 %)"
    + NL
    + "Local storage:"
    + NL
    + "  Cache size (GB):   5.00 /  5.00 (100.0 %)"
    + NL
)

CCACHE_3 = (
    "cache hit (direct)                   800"
    + NL
    + "cache hit (preprocessed)             100"
    + NL
    + "cache miss                           334"
    + NL
    + "cache size                           4.2 GB"
    + NL
    + "max cache size                       5.0 GB"
    + NL
)

SCCACHE = (
    "Compile requests                1000"
    + NL
    + "Cache hits                       700"
    + NL
    + "Cache misses                     300"
    + NL
    + "Cache size                       2 GiB"
    + NL
    + "Max cache size                  10 GiB"
    + NL
)


class ArgvRunner:
    def __init__(self, table: dict[str, CommandResult]) -> None:
        self.table = table
        self.calls: list[tuple[str, ...]] = []

    def run(
        self,
        args: Sequence[str],
        *,
        timeout: float = 15.0,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
    ) -> CommandResult:
        argv = tuple(str(a) for a in args)
        self.calls.append(argv)
        joined = " ".join(argv)
        for token, result in self.table.items():
            if token in joined:
                return result
        return CommandResult(argv, 127, "", "not found")


def probe(table: dict[str, CommandResult] | None = None, **env: str) -> CacheProbe:
    ctx = ProbeContext(
        runner=ArgvRunner(table or {}),
        platform="linux",
        platform_info=PlatformInfo(os_name="Linux", os_version="1", arch="x86_64"),
        env={"PATH": "/usr/bin", **env},
    )
    return CacheProbe(ctx)


def ok(stdout: str) -> CommandResult:
    return CommandResult(("x",), 0, stdout, "")


def ids(table: dict[str, CommandResult] | None = None) -> list[str]:
    return [f.rule_id for f in probe(table).run().findings]


# ------------------------------------------------------------------ parsing


def test_ccache_4_totals_are_read() -> None:
    stats = parse_ccache_stats(CCACHE_4)
    assert stats.hits == 900
    assert stats.misses == 334
    assert stats.hit_rate == pytest.approx(0.7293, rel=0.01)


def test_ccache_3_counters_are_read() -> None:
    """Version 3 prints separate counters and no totals at all.

    A parser written against version 4 returns nothing here, and "nothing"
    reads as "this cache is fine" -- which is why both layouts are handled
    rather than the newer one alone.
    """
    stats = parse_ccache_stats(CCACHE_3)
    assert stats.hits == 900
    assert stats.misses == 334
    assert stats.size_bytes == 4_200_000_000
    assert stats.max_size_bytes == 5_000_000_000


def test_ccache_4_size_units_are_honoured() -> None:
    stats = parse_ccache_stats(CCACHE_4)
    assert stats.size_bytes == 4_200_000_000
    assert stats.max_size_bytes == 5_000_000_000


def test_sccache_stats_are_read_including_binary_units() -> None:
    stats = parse_sccache_stats(SCCACHE)
    assert stats.hits == 700
    assert stats.misses == 300
    assert stats.size_bytes == 2 * 1024**3


@pytest.mark.parametrize("text", ["", "no stats here", "garbage"])
def test_unparseable_stats_yield_no_verdict(text: str) -> None:
    stats = parse_ccache_stats(text)
    assert stats.hit_rate is None
    assert stats.calls is None


def test_a_cache_at_its_ceiling_is_detected() -> None:
    assert parse_ccache_stats(CCACHE_4_POOR).near_capacity is True
    assert parse_ccache_stats(CCACHE_4).near_capacity is False


def test_capacity_is_unknown_without_both_numbers() -> None:
    assert CompilerCacheStats("ccache", 1, 1).near_capacity is None


# ----------------------------------------------------------------- findings


def test_a_poor_hit_rate_is_reported_with_the_reason() -> None:
    findings = probe({"ccache -s": ok(CCACHE_4_POOR)}).run().findings
    match = next(f for f in findings if f.rule_id == "caches/compiler-cache-ineffective")

    assert match.state is FindingState.WARN
    assert "10%" in match.summary
    assert "smaller than the working set" in (match.remediation_hint or "")


def test_a_healthy_hit_rate_is_recorded_as_a_pass() -> None:
    assert "caches/compiler-cache-effective" in ids({"ccache -s": ok(CCACHE_4)})


def test_a_full_cache_is_reported_alongside_the_rate() -> None:
    """The ceiling is the cause; the rate is the symptom."""
    found = ids({"ccache -s": ok(CCACHE_4_POOR)})
    assert "caches/compiler-cache-full" in found
    assert "caches/compiler-cache-ineffective" in found


def test_a_fresh_cache_is_not_reported_as_ineffective() -> None:
    """0% on the first build is arithmetic, not a problem.

    Reporting it would train people to ignore the finding that matters.
    """
    fresh = (
        "Cacheable calls:   10 / 10 (100.0 %)"
        + NL
        + "  Hits:             0 / 10 (0.00 %)"
        + NL
        + "  Misses:          10 / 10 (100.0 %)"
        + NL
    )
    assert "caches/compiler-cache-ineffective" not in ids({"ccache -s": ok(fresh)})


def test_the_threshold_is_a_number_a_test_can_see() -> None:
    assert MIN_CALLS_FOR_A_VERDICT > 1


def test_sccache_is_read_as_well_as_ccache() -> None:
    found = ids({"sccache --show-stats": ok(SCCACHE)})
    assert "caches/compiler-cache-effective" in found


def test_no_compiler_cache_installed_says_nothing() -> None:
    assert [i for i in ids({}) if "compiler-cache" in i] == []


# --------------------------------------------------------------------- disk


def test_low_disk_is_a_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("devrepro.probes.caches._free_bytes", lambda: 3 * 1000**3)
    findings = probe().run().findings
    match = next(f for f in findings if f.rule_id == "caches/disk-low")
    assert match.state is FindingState.WARN


def test_critically_low_disk_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("devrepro.probes.caches._free_bytes", lambda: 500 * 1000**2)
    findings = probe().run().findings
    match = next(f for f in findings if f.rule_id == "caches/disk-critical")
    assert match.state is FindingState.BLOCKED
    assert "no space left on device" in (match.remediation_hint or "")


def test_ample_disk_says_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("devrepro.probes.caches._free_bytes", lambda: 400 * 1000**3)
    assert [i for i in ids() if "disk" in i] == []


def test_unknown_free_space_is_not_reported_as_low(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed measurement is not a measurement of zero."""
    monkeypatch.setattr("devrepro.probes.caches._free_bytes", lambda: None)
    assert [i for i in ids() if "disk" in i] == []


# ---------------------------------------------------------------- inventory


def test_a_cache_in_its_default_place_is_found(tmp_path: Path) -> None:
    (tmp_path / ".cache" / "pip").mkdir(parents=True)
    found = cache_locations(home=tmp_path, local_app_data=None, env={}, platform="linux")
    assert [entry.tool for entry in found] == ["pip"]
    assert not found[0].relocated


def test_an_environment_variable_wins_and_is_marked(tmp_path: Path) -> None:
    """A cache on a network share is a common, invisible cause of slow builds."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tmp_path / ".cache" / "pip").mkdir(parents=True)

    found = cache_locations(
        home=tmp_path,
        local_app_data=None,
        env={"PIP_CACHE_DIR": str(elsewhere)},
        platform="linux",
    )

    assert found[0].relocated
    assert found[0].path == str(elsewhere)


def test_a_cache_that_does_not_exist_is_not_reported(tmp_path: Path) -> None:
    assert cache_locations(home=tmp_path, local_app_data=None, env={}, platform="linux") == ()


def test_a_relocated_cache_is_a_finding(tmp_path: Path) -> None:
    """A cache where it belongs is not news; one moved by a variable is."""
    elsewhere = tmp_path / "on-a-network-share"
    elsewhere.mkdir()

    findings = probe({}, PIP_CACHE_DIR=str(elsewhere)).run().findings
    match = next(f for f in findings if f.rule_id == "caches/relocated")

    assert match.state is FindingState.INFO
    assert "pip" in match.summary


def test_caches_in_their_default_places_produce_no_finding() -> None:
    """Presence alone is not worth a line in a report."""
    assert "caches/relocated" not in ids({})


def test_the_sizing_command_matches_the_platform() -> None:
    """Reporting the command rather than the number is the whole design.

    Walking these directories is the expensive part; someone who wants the
    figure can spend the seconds deliberately.
    """
    assert sizing_command("/x", "linux").startswith("du -sh")
    assert "Measure-Object" in sizing_command("C:/x", "windows")


def test_no_cache_directory_is_walked() -> None:
    """The performance guarantee, asserted rather than assumed.

    A Gradle cache is routinely tens of gigabytes. Sizing one on every scan
    would cost more than the entire rest of the scan.
    """
    from pathlib import Path as _Path

    import devrepro.probes.caches as module

    source = module.__file__
    assert source is not None
    text = _Path(source).read_text(encoding="utf-8")
    for walker in ("rglob", "os.walk", "iterdir()"):
        assert walker not in text, f"{walker} would walk a cache directory"
