"""Three host facts that make builds slow or wrong, and the ways each can lie.

Every one of these is a property of the machine that no tool in the build chain
can see, and every one produces a symptom that points somewhere else. A slow
filesystem looks like a slow build tool. Real-time scanning looks like a slow
compiler. An uncorrected clock looks like a broken TLS certificate.

The tests below concentrate on the boundary between "fine", "broken" and
"could not tell", because collapsing the third into either of the others is how
each of these checks does harm: a machine reported as protected when nobody
could look, or as unsynchronised when the query simply failed.

Two of these tests exist because the probe was run on a real machine and stayed
silent when it should not have: `w32tm` reports a stopped Windows Time service
by *failing*, and a workspace keeps its `node_modules` one directory down.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from devrepro.core.models import FindingState, PlatformInfo
from devrepro.core.runner import CommandResult
from devrepro.platforms.antivirus import (
    DefenderState,
    advise,
    parse_exclusion_paths,
    parse_realtime_status,
)
from devrepro.platforms.cuda import (
    compare_toolkit_to_driver,
    mixed_architectures,
    parse_query_gpu,
    parse_smi_header,
)
from devrepro.platforms.mounts import classify_path, parse_proc_mounts
from devrepro.platforms.timesync import (
    parse_chronyc_tracking,
    parse_timedatectl,
    parse_w32tm_failure,
    parse_w32tm_status,
)
from devrepro.probes.base import ProbeContext
from devrepro.probes.hostperf import HostPerfProbe

NL = chr(10)


class TableRunner:
    def __init__(self, table: dict[str, CommandResult]) -> None:
        self.table = table

    def run(
        self,
        args: object,
        *,
        timeout: float = 15.0,
        env: object = None,
        cwd: str | None = None,
    ) -> CommandResult:
        argv = tuple(str(a) for a in args)  # type: ignore[call-overload]
        joined = " ".join(argv)
        for token, result in self.table.items():
            if token in joined:
                return result
        return CommandResult(argv, 127, "", "not found")


def ok(stdout: str) -> CommandResult:
    return CommandResult(("x",), 0, stdout, "")


def fail(stderr: str) -> CommandResult:
    return CommandResult(("x",), 1, "", stderr)


def probe(
    table: dict[str, CommandResult] | None = None,
    *,
    platform: str = "linux",
    is_wsl: bool = False,
    project_dir: Path | None = None,
) -> HostPerfProbe:
    ctx = ProbeContext(
        runner=TableRunner(table or {}),  # type: ignore[arg-type]
        platform=platform,  # type: ignore[arg-type]
        platform_info=PlatformInfo(
            os_name=platform.title(), os_version="1", arch="x86_64", is_wsl=is_wsl
        ),
        project_dir=project_dir,
        env={},
    )
    return HostPerfProbe(ctx)


def ids(probe_: HostPerfProbe) -> list[str]:
    return [f.rule_id for f in probe_.run().findings]


# =========================================================== the filesystem


def test_a_wsl_shell_under_mnt_c_is_the_headline_case(tmp_path: Path) -> None:
    """The most common WSL performance complaint, and the fix is one `cp`."""
    verdict = classify_path("/mnt/c/work/project", platform="linux", is_wsl=True)

    assert verdict.slow is True
    assert "9p" in verdict.detail
    assert "into the Linux filesystem" in (verdict.remedy or "")


def test_a_linux_path_inside_wsl_is_fine() -> None:
    verdict = classify_path(
        "/home/someone/project",
        platform="linux",
        is_wsl=True,
        mounts=(("/", "ext4"),),
    )
    assert verdict.slow is False


def test_a_network_mount_is_reported_with_its_filesystem() -> None:
    verdict = classify_path(
        "/mnt/share/project",
        platform="linux",
        mounts=(("/mnt/share", "nfs4"), ("/", "ext4")),
    )
    assert verdict.slow is True
    assert "nfs4" in verdict.kind


def test_the_longest_matching_mount_point_wins() -> None:
    """`/` matches everything; the specific mount is the one that describes it."""
    mounts = parse_proc_mounts(
        "server:/x /mnt/share nfs4 rw 0 0" + NL + "/dev/sda1 / ext4 rw 0 0" + NL
    )
    verdict = classify_path("/mnt/share/project", platform="linux", mounts=mounts)
    assert verdict.slow is True


def test_a_unc_path_is_a_network_share_on_windows() -> None:
    verdict = classify_path(r"\\fileserver\dev\project", platform="windows")
    assert verdict.slow is True
    assert verdict.kind == "network-share"


def test_a_local_windows_path_is_fine() -> None:
    assert classify_path(r"D:\work\project", platform="windows").slow is False


def test_an_unidentifiable_mount_is_unknown_not_fast() -> None:
    """A failed measurement is not a measurement of "fine"."""
    verdict = classify_path("/somewhere", platform="linux", mounts=())
    assert verdict.slow is None
    assert verdict.kind == "unknown"


def test_an_escaped_mount_point_is_decoded() -> None:
    """`/proc/mounts` writes a space as \\040; the raw form never matches a real path."""
    mounts = parse_proc_mounts("//srv/x /mnt/my\\040share cifs rw 0 0" + NL)
    assert mounts[0][0] == "/mnt/my share"


def test_the_probe_reports_a_slow_filesystem(tmp_path: Path) -> None:
    found = ids(
        probe(
            {"/proc/mounts": ok("server:/x /mnt/share nfs rw 0 0" + NL)},
            project_dir=Path("/mnt/share/project"),
        )
    )
    assert "host/slow-filesystem" in found


def test_the_probe_says_nothing_about_a_normal_disk(tmp_path: Path) -> None:
    found = ids(
        probe(
            {"/proc/mounts": ok("/dev/sda1 / ext4 rw 0 0" + NL)},
            project_dir=tmp_path,
        )
    )
    assert "host/slow-filesystem" not in found


# ============================================================== antivirus


def test_defender_status_is_read_as_a_tristate() -> None:
    assert parse_realtime_status("True") is True
    assert parse_realtime_status("False") is False
    assert parse_realtime_status("") is None
    assert parse_realtime_status("Access denied") is None


def test_exclusion_paths_are_read_one_per_line() -> None:
    assert parse_exclusion_paths("C:\\a" + NL + "C:\\b" + NL) == ("C:\\a", "C:\\b")


def test_an_unreadable_configuration_is_not_an_empty_one() -> None:
    """From a non-elevated shell these look identical and mean the opposite."""
    advice = advise(
        DefenderState(unavailable_because="needs elevation"), "C:\\p", ("node_modules",)
    )
    assert advice.unknown_because
    assert advice.unexcluded == ()


def test_protection_being_off_is_a_known_answer_not_an_unknown_one() -> None:
    """The fault found by running this on a real machine.

    The first version reported "real-time protection is off" as UNKNOWN and
    advised re-running from an elevated shell -- a definite fact filed as an
    unknown, with a remedy for a different problem, and no mention of the usual
    cause: another product registered itself and Defender stood down.
    """
    advice = advise(DefenderState(realtime_enabled=False), "C:\\p", ("node_modules",))
    assert advice.unknown_because is None
    assert advice.inactive_because
    assert "another antivirus product" in advice.inactive_because


def test_an_already_excluded_directory_is_not_advised_again() -> None:
    advice = advise(
        DefenderState(realtime_enabled=True, exclusions=("C:\\p\\node_modules",)),
        "C:\\p",
        ("node_modules",),
    )
    assert advice.unexcluded == ()
    assert advice.already_excluded == ("C:\\p\\node_modules",)


def test_a_parent_exclusion_covers_a_child() -> None:
    advice = advise(
        DefenderState(realtime_enabled=True, exclusions=("C:\\p",)),
        "C:\\p",
        ("node_modules",),
    )
    assert advice.unexcluded == ()


def test_a_workspace_directory_keeps_its_own_reason() -> None:
    """`web/node_modules` is still node_modules, and the reason is keyed by the leaf."""
    advice = advise(DefenderState(realtime_enabled=True), "C:\\p", ("web/node_modules",))
    path, reason = advice.unexcluded[0]
    assert path == "C:\\p\\web\\node_modules"
    assert "install writes and reads" in reason


def test_the_command_is_produced_and_never_run() -> None:
    advice = advise(DefenderState(realtime_enabled=True), "C:\\p", ("node_modules",))
    assert advice.command is not None
    assert advice.command.startswith("Add-MpPreference")


def test_the_module_never_changes_a_setting() -> None:
    """The guarantee, asserted: no code path can build a `Set-MpPreference` call.

    Checked against the parsed tree rather than the raw text, because the
    module docstring says the words in the course of promising not to do it --
    and a grep over the file cannot tell the promise from the breach.
    """
    import ast

    source = (
        Path(__file__).resolve().parent.parent / "devrepro" / "platforms" / "antivirus.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.FunctionDef | ast.ClassDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    live = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]
    assert not [text for text in live if "Set-MpPreference" in text]


def test_the_advice_names_the_trade_rather_than_recommending_it() -> None:
    """Excluding a source tree from scanning is a real reduction in protection."""
    prose = " ".join(
        (Path(__file__).resolve().parent.parent / "devrepro" / "platforms" / "antivirus.py")
        .read_text(encoding="utf-8")
        .split()
    )
    assert "genuine reduction in protection" in prose
    assert "not a recommendation" in prose


# =============================================================== time sync


def test_a_stopped_windows_time_service_reports_itself_by_failing() -> None:
    """Found by running the probe: the answer is on the failure path.

    A probe that reads only successful output stays silent on exactly the
    machines this check exists for.
    """
    sync = parse_w32tm_failure("The following error occurred: The service has not been started.")
    assert sync is not None
    assert sync.synchronised is False


def test_an_unrelated_w32tm_failure_is_not_a_clock_finding() -> None:
    """ "w32tm is missing" and "the service is stopped" are different answers."""
    assert parse_w32tm_failure("'w32tm' is not recognized") is None


def test_the_local_cmos_clock_source_is_the_finding() -> None:
    """A machine synchronising with itself looks configured and corrects nothing."""
    sync = parse_w32tm_status("Source: Local CMOS Clock" + NL + "Stratum: 0")
    assert sync.self_referential is True
    assert sync.actionable is True


def test_a_real_windows_time_source_produces_no_finding() -> None:
    sync = parse_w32tm_status("Source: time.windows.com" + NL + "Stratum: 3")
    assert sync.actionable is False


def test_timedatectl_synchronised_is_quiet() -> None:
    sync = parse_timedatectl("System clock synchronized: yes" + NL + "NTP service: active" + NL)
    assert sync.actionable is False


def test_a_machine_with_no_ntp_service_is_reported() -> None:
    sync = parse_timedatectl("System clock synchronized: no" + NL + "NTP service: inactive" + NL)
    assert sync.synchronised is False
    assert sync.actionable is True


def test_a_freshly_booted_machine_is_not_a_fault() -> None:
    """The daemon is running and has not converged; that resolves itself."""
    sync = parse_timedatectl("System clock synchronized: no" + NL + "NTP service: active" + NL)
    assert sync.actionable is False


def test_chrony_at_stratum_zero_has_no_usable_source() -> None:
    """The shape that looks healthiest from outside and is doing the least."""
    sync = parse_chronyc_tracking("Reference ID    : 00000000 ()" + NL + "Stratum         : 0")
    assert sync.synchronised is False


def test_chrony_tracking_a_real_server_is_quiet() -> None:
    sync = parse_chronyc_tracking(
        "Reference ID    : C0248F97 (ntp.example)" + NL + "Stratum         : 2"
    )
    assert sync.actionable is False


def test_an_unanswerable_query_is_not_reported_as_unsynchronised(tmp_path: Path) -> None:
    """Silence from the tool is not evidence about the clock."""
    found = ids(probe({}, project_dir=tmp_path))
    assert "host/clock-unsynchronised" not in found


def test_the_probe_reports_an_unsynchronised_clock(tmp_path: Path) -> None:
    found = ids(
        probe(
            {"timedatectl": ok("System clock synchronized: no" + NL + "NTP service: inactive")},
            project_dir=tmp_path,
        )
    )
    assert "host/clock-unsynchronised" in found


# ==================================================================== CUDA


def test_the_driver_ceiling_is_read_from_the_machine_not_a_table() -> None:
    """A bundled driver-to-CUDA table would be wrong within a release."""
    state = parse_smi_header("| NVIDIA-SMI 550.54  Driver Version: 550.54  CUDA Version: 12.4  |")
    assert state.driver == "550.54"
    assert state.max_cuda == "12.4"


def test_minor_version_compatibility_is_honoured() -> None:
    """The comparison hand-rolled checks get backwards.

    CUDA 11+ promises that any minor within a major runs on a driver meeting
    that major's floor. A strict `toolkit <= ceiling` reports a working machine
    as broken, and somebody then upgrades a driver that was fine.
    """
    verdict = compare_toolkit_to_driver("12.4", "12.2")
    assert verdict.ok is True
    assert "Minor-version compatibility" in verdict.summary


def test_a_major_version_ahead_of_the_driver_is_a_real_problem() -> None:
    verdict = compare_toolkit_to_driver("12.0", "11.8")
    assert verdict.ok is False
    assert "insufficient" in verdict.summary


def test_a_toolkit_below_the_ceiling_is_fine() -> None:
    assert compare_toolkit_to_driver("11.8", "12.4").ok is True


@pytest.mark.parametrize(
    ("toolkit", "ceiling"),
    [(None, None), ("12.0", None), (None, "12.4")],
)
def test_a_missing_half_is_unknown_and_says_which(toolkit: str | None, ceiling: str | None) -> None:
    verdict = compare_toolkit_to_driver(toolkit, ceiling)
    assert verdict.ok is None
    assert verdict.unknown_because


def test_devices_are_enumerated_for_the_mixed_case() -> None:
    devices = parse_query_gpu(
        "0, NVIDIA GeForce RTX 4090, 24564 MiB, 8.9"
        + NL
        + "1, NVIDIA GeForce RTX 3090, 24576 MiB, 8.6"
    )
    assert [d.index for d in devices] == [0, 1]
    assert devices[0].memory_mib == 24564
    assert mixed_architectures(d.compute_capability for d in devices) == ("8.6", "8.9")


def test_matching_devices_produce_no_warning() -> None:
    devices = parse_query_gpu("0, A, 1 MiB, 8.6" + NL + "1, B, 1 MiB, 8.6")
    assert mixed_architectures(d.compute_capability for d in devices) == ()


def test_an_old_driver_that_cannot_report_capability_does_not_invent_a_mismatch() -> None:
    """`[Not Supported]` compared as a value would warn on a uniform machine."""
    devices = parse_query_gpu("0, A, 1 MiB, [Not Supported]" + NL + "1, B, 1 MiB, [Not Supported]")
    assert all(d.compute_capability is None for d in devices)
    assert mixed_architectures(d.compute_capability for d in devices) == ()


def test_a_single_gpu_never_warns() -> None:
    assert mixed_architectures(["8.6"]) == ()


# ================================================================= probe


def test_the_probe_produces_no_findings_on_a_clean_machine(tmp_path: Path) -> None:
    """Silence is the correct output for a machine with nothing wrong."""
    found = probe(
        {
            "/proc/mounts": ok("/dev/sda1 / ext4 rw 0 0" + NL),
            "timedatectl": ok("System clock synchronized: yes" + NL + "NTP service: active"),
        },
        project_dir=tmp_path,
    ).run()
    assert found.findings == ()


def test_a_failing_mount_read_does_not_crash_the_probe(tmp_path: Path) -> None:
    result = probe(
        {"/proc/mounts": fail("nope"), "mount": fail("nope")}, project_dir=tmp_path
    ).run()
    assert all(f.state is not FindingState.ERROR for f in result.findings)


# ============================================== the network opt-in (a real bug)


def test_a_default_scan_opens_no_sockets() -> None:
    """The invariant this project leads with, and which was not true.

    `devrepro bench` put `network/tls` at 11.4 of 37.5 sequential seconds while
    running zero subprocess commands -- which for a probe means it is blocking
    in-process. It was: a TLS handshake to github.com, the npm registry and
    PyPI, plus an HTTPS request for clock skew, on every `doctor`, `scan`,
    `preflight`, `guard` and `snapshot`.

    `devrepro/network/diagnostics.py` gates all of it on `allow_network`, and
    the `network` command passes the flag. The probe went around both. Three
    third-party hosts, and any corporate proxy in the path, learned that this
    machine had run this tool.
    """
    from devrepro.core.models import PlatformInfo as _PlatformInfo
    from devrepro.probes.base import ProbeContext as _Ctx
    from devrepro.probes.network import NetworkTlsProbe

    ctx = _Ctx(
        runner=TableRunner({}),  # type: ignore[arg-type]
        platform="linux",
        platform_info=_PlatformInfo(os_name="Linux", os_version="1", arch="x86_64"),
        env={"HTTPS_PROXY": "http://user:secret@proxy.internal:8080"},
    )

    result = NetworkTlsProbe(ctx).run()

    assert [f.rule_id for f in result.findings] == ["network/checks-skipped"]
    assert result.data["network_checks_opt_in"] is False


def test_proxy_configuration_is_still_reported_without_the_flag() -> None:
    """Reading an environment variable is local; connecting to a host is not.

    Dropping the proxy report along with the connections would have cost the
    most useful half of this probe to fix the other half.
    """
    from devrepro.core.models import PlatformInfo as _PlatformInfo
    from devrepro.probes.base import ProbeContext as _Ctx
    from devrepro.probes.network import NetworkTlsProbe

    ctx = _Ctx(
        runner=TableRunner({}),  # type: ignore[arg-type]
        platform="linux",
        platform_info=_PlatformInfo(os_name="Linux", os_version="1", arch="x86_64"),
        env={"HTTPS_PROXY": "http://user:secret@proxy.internal:8080"},
    )

    proxies = NetworkTlsProbe(ctx).run().data["proxies"]

    assert isinstance(proxies, dict)
    assert "proxy.internal" in proxies["HTTPS_PROXY"]
    assert "secret" not in proxies["HTTPS_PROXY"]


def test_the_skip_is_reported_rather_than_left_silent() -> None:
    """A scan that says nothing about network health reads as one that found it fine."""
    from devrepro.core.models import PlatformInfo as _PlatformInfo
    from devrepro.probes.base import ProbeContext as _Ctx
    from devrepro.probes.network import NetworkTlsProbe

    ctx = _Ctx(
        runner=TableRunner({}),  # type: ignore[arg-type]
        platform="linux",
        platform_info=_PlatformInfo(os_name="Linux", os_version="1", arch="x86_64"),
        env={},
    )
    finding = NetworkTlsProbe(ctx).run().findings[0]
    assert "--allow-network" in (finding.remediation_hint or "")
