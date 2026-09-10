"""Measuring where a scan spends its time, without lying about it.

This project lost the speed argument once already: a scan took 26 seconds, of
which 16 were resolving PATH, and finding that took an afternoon because
nothing in the tool could say which part was slow.

The measurement itself has two ways to be wrong, and both are pinned here.
Timing probes under a shared thread pool produces per-probe numbers that
overlap and sum to more than the elapsed time, so parallel mode reports zero
rather than a plausible-looking figure. And a probe whose subprocess calls were
never counted must report "unknown", not "none" -- the first version of the
counter failed silently against a frozen context and every probe read as making
no calls at all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from devrepro.bench import CountingRunner, bench_probes
from devrepro.core.models import Evidence, Finding, FindingState, PlatformInfo
from devrepro.core.runner import CommandResult
from devrepro.probes.base import Probe, ProbeContext, ProbeResult

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class StubRunner:
    def run(
        self,
        args: Sequence[str],
        *,
        timeout: float = 15.0,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
    ) -> CommandResult:
        return CommandResult(tuple(str(a) for a in args), 0, "", "")


def _ctx() -> ProbeContext:
    return ProbeContext(
        runner=StubRunner(),
        platform="linux",
        platform_info=PlatformInfo(os_name="Linux", os_version="1", arch="x86_64"),
        env={"PATH": "/usr/bin"},
    )


class QuietProbe(Probe):
    id = "test/quiet"

    def run(self) -> ProbeResult:
        return ProbeResult(self.id)


class ChattyProbe(Probe):
    """Makes several subprocess calls, which is what explains a slow probe."""

    id = "test/chatty"

    def run(self) -> ProbeResult:
        for name in ("a", "b", "c"):
            self.ctx.runner.run((name, "--version"))
        return ProbeResult(
            self.id,
            findings=(
                Finding(
                    rule_id="test/found",
                    state=FindingState.INFO,
                    summary="something",
                    evidence=(Evidence(source="system", excerpt="x"),),
                ),
            ),
        )


class RaisingProbe(Probe):
    id = "test/raises"

    def run(self) -> ProbeResult:
        raise RuntimeError("deliberate")


class WindowsOnlyProbe(Probe):
    id = "test/windows-only"
    platforms = ("windows",)

    def run(self) -> ProbeResult:  # pragma: no cover - never reached on linux ctx
        return ProbeResult(self.id)


class FakeClock:
    """Advances a fixed amount per reading, so timings are exact."""

    def __init__(self, step: float = 0.5) -> None:
        self.now = 0.0
        self.step = step

    def __call__(self) -> float:
        value = self.now
        self.now += self.step
        return value


# ------------------------------------------------------------------ counting


def test_subprocess_calls_are_counted() -> None:
    """The number that explains a slow probe: process startup dominates."""
    report = bench_probes([ChattyProbe(_ctx())])
    assert report.probes[0].commands == 3


def test_a_probe_that_runs_nothing_reports_zero_not_unknown() -> None:
    report = bench_probes([QuietProbe(_ctx())])
    assert report.probes[0].commands == 0


def test_the_frozen_context_is_actually_replaced() -> None:
    """The regression this file exists for, asserted at the point of failure.

    `ProbeContext` is frozen -- "read-only by contract" -- so assigning
    `ctx.runner` silently does nothing. The first counter did exactly that
    inside a `try`, and the swap never happened: every probe reported no
    subprocess calls, and the column meant to explain slowness was blank on
    every row.

    Checked from *inside* the probe rather than by reading the count
    afterwards, so it fails for the actual reason rather than for any of the
    other ways a count could come out wrong.
    """
    seen: list[str] = []

    class Observer(Probe):
        id = "test/observer"

        def run(self) -> ProbeResult:
            seen.append(type(self.ctx.runner).__name__)
            return ProbeResult(self.id)

    bench_probes([Observer(_ctx())])

    assert seen == ["CountingRunner"], f"the probe ran with {seen} rather than the counting runner"


def test_the_probe_is_left_as_it_was_found() -> None:
    """A caller may reuse the probes it passed in."""
    probe = ChattyProbe(_ctx())
    original = probe.ctx.runner
    bench_probes([probe])
    assert probe.ctx.runner is original
    assert not isinstance(probe.ctx.runner, CountingRunner)


# ------------------------------------------------------------------- timing


def test_each_probe_is_timed_separately() -> None:
    clock = FakeClock(step=1.0)
    report = bench_probes([QuietProbe(_ctx()), ChattyProbe(_ctx())], clock=clock)
    assert len(report.probes) == 2
    assert all(t.seconds > 0 for t in report.probes)


def test_the_slowest_probe_is_identified() -> None:
    report = bench_probes([QuietProbe(_ctx()), ChattyProbe(_ctx())])
    assert report.slowest is not None
    assert report.slowest.probe_id in {"test/quiet", "test/chatty"}


def test_an_empty_run_has_no_slowest_probe() -> None:
    assert bench_probes([]).slowest is None


def test_parallel_mode_reports_zero_rather_than_a_wrong_number() -> None:
    """Eight probes sharing a pool produce overlapping wall times.

    Summing them exceeds the elapsed time, and no individual figure is that
    probe's cost. Reporting zero is visibly not-a-measurement; reporting the
    overlapping value would look like one.
    """
    report = bench_probes([QuietProbe(_ctx()), ChattyProbe(_ctx())], parallel=True)

    assert report.parallel is True
    assert all(t.seconds == 0.0 for t in report.probes)
    assert report.total_seconds >= 0
    assert any("not attributable" in note for note in report.notes)


def test_parallel_mode_still_records_what_each_probe_found() -> None:
    report = bench_probes([ChattyProbe(_ctx())], parallel=True)
    assert report.probes[0].findings == 1


# ------------------------------------------------------------------ failures


def test_a_probe_that_raises_is_still_timed() -> None:
    """A probe that fails slowly is exactly the one worth measuring."""
    report = bench_probes([RaisingProbe(_ctx())])
    timing = report.probes[0]
    assert timing.error is not None
    assert "deliberate" in timing.error
    assert timing.seconds >= 0


def test_one_failing_probe_does_not_stop_the_others() -> None:
    report = bench_probes([RaisingProbe(_ctx()), ChattyProbe(_ctx())])
    assert {t.probe_id for t in report.probes} == {"test/raises", "test/chatty"}


def test_an_unsupported_probe_says_so_instead_of_reporting_zero_work() -> None:
    report = bench_probes([WindowsOnlyProbe(_ctx())])
    assert report.probes[0].error == "unsupported on this platform"
    assert report.probes[0].findings == 0


# ----------------------------------------------------------------- reporting


def test_the_json_shape_is_sorted_slowest_first() -> None:
    clock = FakeClock(step=1.0)
    payload = bench_probes([QuietProbe(_ctx()), ChattyProbe(_ctx())], clock=clock).as_dict()

    seconds = [row["seconds"] for row in payload["probes"]]  # type: ignore[index]
    assert seconds == sorted(seconds, reverse=True)


def test_the_json_shape_carries_every_field_the_table_prints() -> None:
    payload = bench_probes([ChattyProbe(_ctx())]).as_dict()
    row = payload["probes"][0]  # type: ignore[index]
    assert set(row) == {"probe_id", "seconds", "findings", "commands", "error"}
    assert set(payload) >= {"total_seconds", "probe_seconds", "parallel", "probes", "phases"}


@pytest.mark.parametrize("parallel", [False, True])
def test_the_report_is_json_serialisable(parallel: bool) -> None:
    import json

    payload = bench_probes([ChattyProbe(_ctx())], parallel=parallel).as_dict()
    assert json.loads(json.dumps(payload)) == payload


def test_probe_seconds_and_wall_clock_are_reported_separately() -> None:
    """They differ under parallelism, and conflating them hides the speed-up."""
    report = bench_probes([QuietProbe(_ctx()), ChattyProbe(_ctx())], parallel=True)
    assert report.probe_seconds == 0.0
    assert report.total_seconds >= 0.0
