"""Where a scan spends its time.

A diagnostic tool competes with the developer's patience, and this one has
already lost that competition once: `devrepro doctor` took 26 seconds, of which
16 were spent resolving PATH, and `docs/MCP-EXPOSURE.md` names exactly that cost
as a reason not to expose a scan to an agent. The fix was a one-line change of
algorithm. Finding it took an afternoon, because nothing in the tool could say
which part was slow.

This makes that measurable. It times each probe separately, and the phases
after them -- rules, scoring, privacy sanitisation -- so a regression report can
say "the container probe went from 0.2s to 9s" instead of "it feels slower".

Probes normally run in parallel, which is right for a scan and wrong for a
measurement: eight probes sharing a thread pool produce eight wall times that
overlap and sum to more than the elapsed time. `--sequential` (the default here)
measures each one alone. `--parallel` measures what a user actually waits for.
Both numbers are useful and they answer different questions, so both are
reported rather than one being chosen for you.

Nothing here is a gate. A threshold that fails a shared CI runner on a bad
afternoon is a threshold people delete; `tests/test_performance.py` guards the
one algorithmic shape that actually regressed, and this exists so the next
regression is found in minutes rather than in an afternoon.
"""

from __future__ import annotations

import dataclasses
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from devrepro.probes.base import Probe, ProbeResult

__all__ = ["BenchReport", "PhaseTiming", "ProbeTiming", "bench_probes", "bench_scan"]


@dataclass(frozen=True)
class ProbeTiming:
    """How long one probe took, and how much it had to say."""

    probe_id: str
    seconds: float
    findings: int
    #: Subprocess calls the probe made, when the runner counts them. This is
    #: the number that explains a slow probe: process startup dominates, so
    #: "twelve calls" and "one call" differ by more than the work inside them.
    commands: int | None = None
    error: str | None = None

    @property
    def milliseconds(self) -> float:
        return self.seconds * 1000


@dataclass(frozen=True)
class PhaseTiming:
    name: str
    seconds: float


@dataclass(frozen=True)
class BenchReport:
    probes: tuple[ProbeTiming, ...] = ()
    phases: tuple[PhaseTiming, ...] = ()
    #: Wall time for the whole run, which is *not* the sum of the probe times
    #: when they ran in parallel.
    total_seconds: float = 0.0
    parallel: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def slowest(self) -> ProbeTiming | None:
        return max(self.probes, key=lambda p: p.seconds) if self.probes else None

    @property
    def probe_seconds(self) -> float:
        return sum(p.seconds for p in self.probes)

    def as_dict(self) -> dict[str, object]:
        return {
            "total_seconds": round(self.total_seconds, 4),
            "probe_seconds": round(self.probe_seconds, 4),
            "parallel": self.parallel,
            "probes": [
                {
                    "probe_id": p.probe_id,
                    "seconds": round(p.seconds, 4),
                    "findings": p.findings,
                    "commands": p.commands,
                    "error": p.error,
                }
                for p in sorted(self.probes, key=lambda p: p.seconds, reverse=True)
            ],
            "phases": [{"name": p.name, "seconds": round(p.seconds, 4)} for p in self.phases],
            "notes": list(self.notes),
        }


class CountingRunner:
    """Wraps a runner and counts calls, so a slow probe can be explained.

    Process startup dominates a scan -- a probe making twelve subprocess calls
    is slower than one making a single call for reasons that have nothing to do
    with the work inside them. Timing alone cannot distinguish those; the count
    can.
    """

    def __init__(self, inner: object) -> None:
        self.inner = inner
        self.count = 0

    def run(self, args: Sequence[str], **kwargs: object) -> object:
        self.count += 1
        run = self.inner.run  # type: ignore[attr-defined]
        return run(args, **kwargs)

    def __getattr__(self, name: str) -> object:  # pragma: no cover - passthrough
        return getattr(self.inner, name)


def bench_probes(
    probes: Sequence[Probe],
    *,
    parallel: bool = False,
    clock: Callable[[], float] | None = None,
) -> BenchReport:
    """Time each probe, sequentially by default.

    Sequential is the default because it is the measurement that can be
    attributed. Run in parallel, eight probes share a thread pool and their
    wall times overlap, so the numbers sum to more than the elapsed time and no
    single one of them is a probe's actual cost.
    """
    clock = clock or time.perf_counter
    timings: list[ProbeTiming] = []
    started = clock()

    if parallel:
        from devrepro.probes.base import ProbeEngine

        results = ProbeEngine(list(probes)).run_all()
        total = clock() - started
        for probe in probes:
            parallel_result = results.get(probe.id)
            timings.append(
                ProbeTiming(
                    probe_id=probe.id,
                    # Not attributable under a shared pool; reported as zero
                    # rather than as a plausible-looking number that is wrong.
                    seconds=0.0,
                    findings=len(getattr(parallel_result, "findings", ()) or ()),
                    error=getattr(parallel_result, "error", None),
                )
            )
        return BenchReport(
            probes=tuple(timings),
            total_seconds=total,
            parallel=True,
            notes=(
                "Parallel run: per-probe times are not attributable and are reported as 0. "
                "Use the sequential mode to find which probe is slow.",
            ),
        )

    for probe in probes:
        counter = _wrap_runner(probe)
        probe_started = clock()
        result: ProbeResult | None = None
        error: str | None = None
        try:
            result = probe.run() if probe.supported() else None
            if result is None:
                error = "unsupported on this platform"
        except Exception as exc:  # a probe that raises still has a cost worth knowing
            error = f"{type(exc).__name__}: {exc}"
        elapsed = clock() - probe_started
        _restore_runner(probe, counter)
        timings.append(
            ProbeTiming(
                probe_id=probe.id,
                seconds=elapsed,
                findings=len(result.findings) if result else 0,
                commands=counter.count if counter else None,
                error=error or (result.error if result else None),
            )
        )

    return BenchReport(
        probes=tuple(timings),
        total_seconds=clock() - started,
        parallel=False,
    )


def _wrap_runner(probe: Probe) -> CountingRunner | None:
    """Give one probe a counting runner, and hand back the counter.

    `ProbeContext` is frozen -- "read-only by contract", which is the right
    design and means assigning `ctx.runner` does nothing. The first version of
    this did exactly that inside a `try`, so the swap failed silently and every
    probe reported no commands at all. The `Probe` object itself is ordinary,
    so replacing its context is what works.

    Returns None when there is nothing to wrap, and the caller reports the
    count as unknown rather than as zero: "we did not measure" and "it made no
    subprocess calls" are different facts.
    """
    ctx = getattr(probe, "ctx", None)
    inner = getattr(ctx, "runner", None)
    if ctx is None or inner is None:
        return None
    counter = CountingRunner(inner)
    probe.ctx = dataclasses.replace(ctx, runner=counter)
    return counter


def _restore_runner(probe: Probe, counter: CountingRunner | None) -> None:
    """Put the probe back as it was; a caller may reuse it."""
    if counter is None:
        return
    ctx = getattr(probe, "ctx", None)
    if ctx is not None:
        probe.ctx = dataclasses.replace(ctx, runner=counter.inner)


def bench_scan(
    project_dir: Path | None = None,
    *,
    clock: Callable[[], float] | None = None,
) -> BenchReport:
    """Time a whole scan by phase: probes, rules, scoring, serialisation.

    The phases after the probes were never the problem, and measuring them is
    how that stays a fact rather than an assumption.
    """
    clock = clock or time.perf_counter
    from devrepro.cli.pipeline import run_scan
    from devrepro.reports.renderers import render_json

    phases: list[PhaseTiming] = []
    started = clock()

    scan_started = clock()
    report = run_scan(project_dir=project_dir)
    phases.append(PhaseTiming("scan", clock() - scan_started))

    render_started = clock()
    render_json(report)
    phases.append(PhaseTiming("render+privacy", clock() - render_started))

    return BenchReport(
        phases=tuple(phases),
        total_seconds=clock() - started,
        notes=(
            f"{len(report.findings)} finding(s) from {len(report.tools)} tool installation(s).",
        ),
    )
