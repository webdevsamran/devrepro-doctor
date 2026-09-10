"""Whether a prebuilt binary can load here, and why nothing says when it cannot.

Package managers pick a compiled artefact from three facts -- architecture, C
library, and that library's version -- and every way of getting one wrong
produces a failure about something else. musl instead of glibc means pip skips
the manylinux wheel and builds from source, so the error names a missing
header. An x86_64 interpreter on an arm64 host installs x86_64 wheels for ever
and never reports a problem at all.

None of it is testable on the machine that runs these tests, which is the point
of keeping the parsing separate: a musl host and an arm64 Mac are both driven
here from a machine that is neither.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from devrepro.core.models import FindingState, PlatformInfo
from devrepro.core.runner import CommandResult
from devrepro.platforms.abi import (
    COMMON_MANYLINUX,
    MANYLINUX_GLIBC,
    compare_arch,
    normalise_arch,
    parse_libc,
    wheel_tags_for_glibc,
)
from devrepro.probes.abi import AbiProbe
from devrepro.probes.base import ProbeContext

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

NL = chr(10)

GLIBC_BANNER = (
    "ldd (Ubuntu GLIBC 2.39-0ubuntu8.3) 2.39"
    + NL
    + "Copyright (C) 2024 Free Software Foundation, Inc."
)
OLD_GLIBC_BANNER = "ldd (GNU libc) 2.17" + NL + "Copyright (C) 2012"
MUSL_BANNER = "musl libc (x86_64)" + NL + "Version 1.2.5" + NL + "Dynamic Program Loader"


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


def probe(table: dict[str, CommandResult], *, platform: str, arch: str) -> AbiProbe:
    ctx = ProbeContext(
        runner=ArgvRunner(table),
        platform=platform,  # type: ignore[arg-type]
        platform_info=PlatformInfo(os_name=platform.title(), os_version="1", arch=arch),
        env={"PATH": "/usr/bin"},
    )
    return AbiProbe(ctx)


def ids(
    table: dict[str, CommandResult], *, platform: str = "linux", arch: str = "x86_64"
) -> list[str]:
    return [f.rule_id for f in probe(table, platform=platform, arch=arch).run().findings]


def ok(stdout: str = "", stderr: str = "", code: int = 0) -> CommandResult:
    return CommandResult(("x",), code, stdout, stderr)


# ------------------------------------------------------------ architecture


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("AMD64", "x86_64"),
        ("x64", "x86_64"),
        ("arm64", "aarch64"),
        ("armv8", "aarch64"),
        ("ia32", "i686"),
    ],
)
def test_the_same_architecture_spelled_differently_is_the_same(a: str, b: str) -> None:
    """Python says AMD64, uname says x86_64, node says x64.

    Comparing any two of those raw is how a tool reports every Windows machine
    as mismatched with itself.
    """
    assert compare_arch(a, b) is True


@pytest.mark.parametrize(("a", "b"), [("arm64", "x86_64"), ("AMD64", "aarch64")])
def test_genuinely_different_architectures_compare_false(a: str, b: str) -> None:
    assert compare_arch(a, b) is False


def test_an_unknown_architecture_is_unknowable_not_mismatched() -> None:
    """A name we do not recognise must not look like a difference."""
    assert normalise_arch("sparc64") is None
    assert compare_arch("sparc64", "x86_64") is None
    assert compare_arch(None, "x86_64") is None


def test_an_interpreter_on_the_wrong_architecture_is_reported() -> None:
    found = ids({}, platform="linux", arch="aarch64")
    # The test process really is x86_64, so the host/interpreter pair differs.
    assert "abi/interpreter-arch-mismatch" in found


def test_a_matching_architecture_says_nothing() -> None:
    assert ids({}, platform="linux", arch="x86_64") == []


def test_a_runtime_on_the_wrong_architecture_is_reported() -> None:
    """A node addon is chosen by node's architecture, not the machine's."""
    findings = (
        probe({"node -p process.arch": ok("x64")}, platform="linux", arch="aarch64").run().findings
    )
    match = next(f for f in findings if f.rule_id == "abi/runtime-arch-mismatch")
    assert match.component == "node"
    assert match.detected == "x64"


def test_a_runtime_agreeing_with_the_host_says_nothing() -> None:
    found = ids({"node -p process.arch": ok("x64")}, platform="linux", arch="x86_64")
    assert "abi/runtime-arch-mismatch" not in found


def test_rosetta_is_detected_and_named() -> None:
    findings = (
        probe({"sysctl.proc_translated": ok("1")}, platform="macos", arch="arm64").run().findings
    )
    match = next(f for f in findings if f.rule_id == "abi/translated-process")
    assert match.state is FindingState.WARN
    assert "will not tell you" in (match.remediation_hint or "")


def test_a_native_arm_mac_is_not_reported_as_translated() -> None:
    found = ids({"sysctl.proc_translated": ok("0")}, platform="macos", arch="arm64")
    assert "abi/translated-process" not in found


def test_rosetta_supersedes_the_generic_mismatch() -> None:
    """One problem, one finding, and the specific one is more useful."""
    found = ids({"sysctl.proc_translated": ok("1")}, platform="macos", arch="arm64")
    assert "abi/translated-process" in found
    assert "abi/interpreter-arch-mismatch" not in found


# -------------------------------------------------------------------- libc


def test_glibc_is_read_from_the_ldd_banner() -> None:
    info = parse_libc(GLIBC_BANNER)
    assert info.flavour == "glibc"
    assert info.version == (2, 39)


def test_musl_is_read_from_stderr_where_it_prints_it() -> None:
    """musl writes its banner to stderr and exits non-zero.

    A check reading only a successful stdout concludes there is no libc at all
    on exactly the systems where the answer matters most.
    """
    info = parse_libc(MUSL_BANNER)
    assert info.flavour == "musl"
    assert info.version == (1, 2, 5)


@pytest.mark.parametrize("text", ["", "   ", None])
def test_no_output_means_no_answer_not_a_wrong_one(text: str | None) -> None:
    assert parse_libc(text).flavour is None


def test_an_unrecognised_banner_keeps_the_raw_line_for_a_human() -> None:
    info = parse_libc("some other libc implementation" + NL + "line two")
    assert info.flavour is None
    assert info.raw == "some other libc implementation"


def test_musl_is_reported_because_manylinux_wheels_will_not_load() -> None:
    findings = (
        probe({"ldd --version": ok("", MUSL_BANNER, code=1)}, platform="linux", arch="x86_64")
        .run()
        .findings
    )
    match = next(f for f in findings if f.rule_id == "abi/musl-libc")
    assert match.state is FindingState.INFO
    assert "builds from source" in (match.remediation_hint or "")


def test_an_old_glibc_is_reported_against_the_common_wheel_tag() -> None:
    findings = (
        probe({"ldd --version": ok(OLD_GLIBC_BANNER)}, platform="linux", arch="x86_64")
        .run()
        .findings
    )
    match = next(f for f in findings if f.rule_id == "abi/glibc-below-common-wheel-tag")
    assert match.state is FindingState.WARN
    assert COMMON_MANYLINUX in match.summary
    # The tags it *can* install are named, so the answer is actionable.
    assert "manylinux2014" in (match.remediation_hint or "")


def test_a_current_glibc_is_recorded_as_a_pass() -> None:
    findings = (
        probe({"ldd --version": ok(GLIBC_BANNER)}, platform="linux", arch="x86_64").run().findings
    )
    assert any(f.rule_id == "abi/glibc-ok" for f in findings)


def test_libc_is_not_probed_off_linux() -> None:
    """`ldd` on macOS is a different program, and on Windows it is nothing."""
    instance = probe({}, platform="macos", arch="x86_64")
    instance.run()
    assert not any("ldd" in " ".join(call) for call in instance.ctx.runner.calls)  # type: ignore[union-attr]


# ------------------------------------------------------------- wheel tags


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ((2, 39), "manylinux_2_34"),
        ((2, 28), "manylinux_2_28"),
        ((2, 17), "manylinux2014"),
    ],
)
def test_the_highest_installable_tag_follows_the_glibc_version(
    version: tuple[int, ...], expected: str
) -> None:
    assert expected in wheel_tags_for_glibc(version)


def test_a_glibc_below_every_floor_supports_nothing() -> None:
    assert wheel_tags_for_glibc((2, 4)) == ()


def test_an_unknown_version_claims_nothing_rather_than_everything() -> None:
    """Claiming support is the direction that produces a silent source build."""
    assert wheel_tags_for_glibc(None) == ()
    assert wheel_tags_for_glibc((2,)) == ()


def test_the_floor_table_is_ordered_and_consistent() -> None:
    floors = [floor for _, floor in MANYLINUX_GLIBC]
    assert floors == sorted(floors), "tags must be listed from lowest floor upward"
    assert COMMON_MANYLINUX in dict(MANYLINUX_GLIBC)


# ----------------------------------------------------------------- shape


def test_the_probe_reports_what_it_found_even_with_no_findings() -> None:
    data = probe({"node -p process.arch": ok("x64")}, platform="linux", arch="x86_64").run().data
    assert data["runtime_arches"] == {"node": "x64"}
    assert data["host_arch"] == "x86_64"


def test_every_finding_carries_evidence_and_a_component() -> None:
    findings = (
        probe(
            {"ldd --version": ok("", MUSL_BANNER, code=1), "node -p process.arch": ok("x64")},
            platform="linux",
            arch="aarch64",
        )
        .run()
        .findings
    )

    assert len(findings) >= 3
    for finding in findings:
        assert finding.evidence, finding.rule_id
        assert finding.component, finding.rule_id
