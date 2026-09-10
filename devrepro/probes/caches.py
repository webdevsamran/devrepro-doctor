"""Disk headroom, and whether the build caches are earning their place.

A compiler cache with a 15% hit rate is not saving time, it is spending it:
every miss pays the lookup, the write and the eviction on top of the compile.
The usual cause is a cache smaller than the working set, so it evicts what it
is about to need next -- and the symptom is "builds got slower after we turned
caching on", which nobody attributes to the cache. Both `ccache` and `sccache`
publish the numbers; nothing reads them.

Disk headroom is the other half of the same story. "No space left on device"
arrives mid-build from a step that has nothing to do with the cause, and by
then the answer is obvious and the hour is gone.

Nothing here walks a cache directory. A Gradle cache is routinely tens of
gigabytes, and sizing one on every scan would undo the performance work
outright -- so the inventory is presence-only and each entry carries the
command that sizes it, for a person who wants the number to spend the seconds
deliberately.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from devrepro.core.models import Evidence, Finding, FindingState
from devrepro.platforms.caches import (
    MIN_CALLS_FOR_A_VERDICT,
    POOR_HIT_RATE,
    CompilerCacheStats,
    cache_locations,
    parse_ccache_stats,
    parse_sccache_stats,
    sizing_command,
)
from devrepro.probes.base import Probe, ProbeResult

__all__ = ["CacheProbe"]

#: Below this, an ordinary `npm ci` or a container build fails partway. It is
#: not a lot of headroom; it is the point past which failure is likely rather
#: than possible.
LOW_DISK_BYTES = 5 * 1000**3
CRITICAL_DISK_BYTES = 1 * 1000**3


class CacheProbe(Probe):
    id = "caches/health"
    version = "1"

    def run(self) -> ProbeResult:
        findings: list[Finding] = []

        free = _free_bytes()
        findings.extend(self._disk_findings(free))

        stats = self._compiler_caches()
        for entry in stats:
            findings.extend(self._effectiveness_findings(entry))

        locations = cache_locations(
            home=Path.home(),
            local_app_data=_local_app_data(self.ctx.env),
            env=dict(self.ctx.env),
            platform=self.ctx.platform,
        )
        findings.extend(self._relocation_findings(locations))

        return ProbeResult(
            self.id,
            findings=tuple(findings),
            data={
                "disk_free_bytes": free,
                # Tool names only. The paths are reported in findings where a
                # person needs them; a snapshot is shared, and a cache path is
                # under a home directory.
                "caches_present": [entry.tool for entry in locations],
                "caches_relocated": [entry.tool for entry in locations if entry.relocated],
                "compiler_caches": [
                    {
                        "tool": entry.tool,
                        "hits": entry.hits,
                        "misses": entry.misses,
                        "hit_rate": round(entry.hit_rate, 3) if entry.hit_rate else None,
                    }
                    for entry in stats
                ],
            },
        )

    # ------------------------------------------------------------------ disk

    def _disk_findings(self, free: int | None) -> list[Finding]:
        if free is None:
            return []
        gigabytes = free / 1000**3
        evidence = (Evidence(source="system", excerpt=f"{gigabytes:.1f} GB free"),)

        if free < CRITICAL_DISK_BYTES:
            return [
                self.finding(
                    "caches/disk-critical",
                    FindingState.BLOCKED,
                    f"{gigabytes:.1f} GB of free disk space remains.",
                    evidence=evidence,
                    detected=f"{gigabytes:.1f} GB",
                    component="disk",
                    remediation_hint="A container build or a dependency install will fail "
                    "partway through with 'no space left on device', from a step unrelated to "
                    "the cause. `devrepro doctor` lists the build caches on this machine and "
                    "how to size them.",
                )
            ]

        if free < LOW_DISK_BYTES:
            return [
                self.finding(
                    "caches/disk-low",
                    FindingState.WARN,
                    f"{gigabytes:.1f} GB of free disk space remains.",
                    evidence=evidence,
                    detected=f"{gigabytes:.1f} GB",
                    component="disk",
                    remediation_hint="Enough for now and not for a container image pull or a "
                    "cold dependency install. Build caches are usually the largest reclaimable "
                    "thing; this scan lists the ones present rather than sizing them, because "
                    "walking them costs more than the whole scan.",
                )
            ]

        return []

    # -------------------------------------------------------- compiler caches

    def _compiler_caches(self) -> list[CompilerCacheStats]:
        found: list[CompilerCacheStats] = []

        ccache = self.ctx.runner.run(("ccache", "-s"), timeout=15)
        if ccache.ok and ccache.stdout.strip():
            found.append(parse_ccache_stats(ccache.stdout))

        sccache = self.ctx.runner.run(("sccache", "--show-stats"), timeout=15)
        if sccache.ok and sccache.stdout.strip():
            found.append(parse_sccache_stats(sccache.stdout))

        return found

    def _effectiveness_findings(self, stats: CompilerCacheStats) -> list[Finding]:
        calls = stats.calls
        rate = stats.hit_rate
        if calls is None or rate is None:
            return []

        if calls < MIN_CALLS_FOR_A_VERDICT:
            # A fresh cache is 0% by definition. Reporting that trains people
            # to ignore the finding that matters.
            return []

        evidence = (
            self.cmd_evidence(
                (stats.tool, "-s"), f"{stats.hits} hits / {calls} calls ({rate:.0%})"
            ),
        )
        out: list[Finding] = []

        if rate < POOR_HIT_RATE:
            out.append(
                self.finding(
                    "caches/compiler-cache-ineffective",
                    FindingState.WARN,
                    f"{stats.tool} hit rate is {rate:.0%} over {calls} calls.",
                    evidence=evidence,
                    detected=f"{rate:.0%}",
                    required=f">={POOR_HIT_RATE:.0%}",
                    component=stats.tool,
                    remediation_hint="Below this the cache costs more than it saves: every "
                    "miss pays a lookup, a write and an eviction on top of the compile. The "
                    "usual cause is a cache smaller than the working set. Raise the size "
                    "limit, or check whether the build varies a compiler flag on every run -- "
                    "an absolute path or a timestamp in the command line defeats it entirely.",
                )
            )
        else:
            out.append(
                self.finding(
                    "caches/compiler-cache-effective",
                    FindingState.PASS,
                    f"{stats.tool} hit rate is {rate:.0%} over {calls} calls.",
                    evidence=evidence,
                    detected=f"{rate:.0%}",
                    component=stats.tool,
                )
            )

        if stats.near_capacity:
            out.append(
                self.finding(
                    "caches/compiler-cache-full",
                    FindingState.WARN,
                    f"{stats.tool} is at its configured size limit.",
                    evidence=evidence,
                    component=stats.tool,
                    remediation_hint="A cache at its ceiling evicts what it is about to need "
                    "again, which is usually the cause of a low hit rate rather than a "
                    "separate problem. Raise `max_size` (ccache) or `SCCACHE_CACHE_SIZE`.",
                )
            )

        return out

    # ------------------------------------------------------------- inventory

    def _relocation_findings(self, locations: tuple[object, ...]) -> list[Finding]:
        """Only relocations are worth a finding; presence alone is not.

        A cache existing where it is supposed to is not news. A cache moved by
        an environment variable is: onto a network share, onto a slow external
        volume, or into a directory a cleanup job empties nightly -- each of
        which produces "builds are slow on this machine only" with nothing in
        the build output to explain it.
        """
        relocated = [entry for entry in locations if getattr(entry, "relocated", False)]
        if not relocated:
            return []

        named = ", ".join(getattr(entry, "tool", "?") for entry in relocated)
        return [
            self.finding(
                "caches/relocated",
                FindingState.INFO,
                f"{len(relocated)} build cache(s) moved by an environment variable: {named}.",
                evidence=(
                    Evidence(
                        source="env",
                        excerpt="; ".join(
                            f"{getattr(e, 'tool', '?')} -> "
                            f"{sizing_command(getattr(e, 'path', ''), self.ctx.platform)}"
                            for e in relocated
                        )[:2000],
                    ),
                ),
                detected=named,
                component="disk",
                remediation_hint="Usually deliberate. It is reported because a cache on a "
                "network share or an external volume is a common cause of 'builds are slow on "
                "this machine only', with nothing in the build output to explain it.",
            )
        ]


def _free_bytes() -> int | None:
    try:
        return shutil.disk_usage(Path.home()).free
    except OSError:  # pragma: no cover - defensive
        return None


def _local_app_data(env: dict[str, str]) -> Path | None:
    raw = env.get("LOCALAPPDATA") or os.environ.get("LOCALAPPDATA")
    return Path(raw) if raw else None
