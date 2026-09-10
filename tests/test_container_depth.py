"""Which engine is behind `docker`, and what shape it is in.

The container probe used to answer one question -- is a daemon responding --
which is the least useful container question there is, because a dead daemon
announces itself the moment you try to use it. These tests cover the ones that
cost an afternoon instead: a different engine answering the same CLI, a daemon
emulating another architecture, cgroup v1 changing how memory limits behave, a
storage driver that copies every layer, and a disk full of things nobody wants.

Every parser test runs against recorded output in
`tests/fixtures/recordings/docker/`, so a machine none of us has can still
drive them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from devrepro.containers.engine import (
    LEGACY_STORAGE_DRIVERS,
    classify_endpoint,
    identify_backend,
    parse_docker_info,
    parse_system_df,
)
from devrepro.core.models import ContainerState, FindingState, PlatformInfo
from devrepro.core.runner import CommandResult
from devrepro.probes.base import ProbeContext
from devrepro.probes.containers import ContainerProbe, _normalise_arch, _parse_context

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

RECORDINGS = Path(__file__).resolve().parent / "fixtures" / "recordings" / "docker"
NL = chr(10)


def recorded_info(name: str) -> str:
    payloads = json.loads((RECORDINGS / "info.json").read_text(encoding="utf-8"))
    return json.dumps(payloads[name])


# ------------------------------------------------------------------ parsing


def test_a_desktop_engine_is_read_in_full() -> None:
    info = parse_docker_info(recorded_info("docker_desktop_macos_arm"))
    assert info is not None
    assert info.server_version == "27.4.0"
    assert info.server_arch == "aarch64"
    assert info.storage_driver == "overlayfs"
    assert info.cgroup_version == "2"
    assert info.cpus == 10
    assert info.rootless is False


def test_rootless_is_read_out_of_security_options() -> None:
    """Docker has no `Rootless` key; it is one entry in a list of strings."""
    info = parse_docker_info(recorded_info("rootless_linux"))
    assert info is not None
    assert info.rootless is True


def test_daemon_warnings_are_carried_through() -> None:
    info = parse_docker_info(recorded_info("legacy_linux_cgroup_v1_devicemapper"))
    assert info is not None
    assert any("devicemapper" in w for w in info.warnings)


def test_a_partial_object_from_a_starting_daemon_is_not_an_error() -> None:
    """A daemon coming up prints an object with no ServerVersion in it."""
    info = parse_docker_info(recorded_info("starting_up_partial"))
    assert info is not None
    assert info.server_version is None


@pytest.mark.parametrize("text", ["", "not json", "[]", '"a string"', "null"])
def test_unparseable_info_returns_none_rather_than_raising(text: str) -> None:
    assert parse_docker_info(text) is None


def test_disk_usage_is_read_line_by_line() -> None:
    """`docker system df --format json` is newline-delimited, not an array.

    Feeding the whole output to `json.loads` fails on the second line, so the
    first implementation reported no disk usage at all on every machine.
    """
    usage = parse_system_df((RECORDINGS / "system_df.txt").read_text(encoding="utf-8"))
    assert usage is not None
    assert usage.images_bytes == 31_420_000_000
    assert usage.dangling_images == 41
    assert usage.unused_volumes == 19
    # 26.88 + 1.101 + 3.902 + 12.71 GB, in docker's decimal units.
    assert usage.reclaimable_bytes == pytest.approx(44_593_000_000, rel=0.001)


def test_a_reclaimable_percentage_is_not_mistaken_for_a_size() -> None:
    """`Reclaimable` renders as "26.88GB (85%)"; the percentage is noise."""
    usage = parse_system_df('{"Type":"Images","Size":"10GB","Reclaimable":"9GB (90%)"}')
    assert usage is not None
    assert usage.reclaimable_bytes == 9_000_000_000


def test_sizes_use_decimal_units_like_docker_prints_them() -> None:
    """Reporting 1.2GB as 1.29e9 would disagree with the number beside it."""
    usage = parse_system_df('{"Type":"Images","Size":"1.2GB","Reclaimable":"0B"}')
    assert usage is not None
    assert usage.images_bytes == 1_200_000_000


def test_empty_df_output_is_none_not_a_zeroed_report() -> None:
    """Zeroes would read as "nothing to reclaim", which is a different claim."""
    assert parse_system_df("") is None


# ------------------------------------------------------------- identity


@pytest.mark.parametrize(
    ("endpoint", "expected"),
    [
        ("unix:///Users/anna/.colima/default/docker.sock", "colima"),
        ("unix:///Users/anna/.rd/docker.sock", "rancher-desktop"),
        ("unix:///Users/anna/.orbstack/run/docker.sock", "orbstack"),
        ("npipe:////./pipe/dockerDesktopLinuxEngine", "docker-desktop"),
        ("unix:///run/user/1000/podman/podman.sock", "podman"),
        ("unix:///var/run/docker.sock", "native"),
    ],
)
def test_the_backend_is_identified_from_the_socket(endpoint: str, expected: str) -> None:
    assert identify_backend(endpoint=endpoint, platform="linux") == expected


def test_rancher_desktop_is_not_mistaken_for_docker_desktop() -> None:
    """`rancher-desktop` contains "desktop"; order in the table is load-bearing."""
    assert identify_backend(context_name="rancher-desktop") == "rancher-desktop"


def test_an_unrecognised_engine_reports_nothing_rather_than_guessing() -> None:
    assert identify_backend(endpoint="tcp://10.0.0.5:2375") is None
    assert identify_backend() is None


def test_the_endpoint_itself_never_reaches_the_snapshot() -> None:
    """A Colima socket path contains a username, and snapshots get shared.

    Only the scheme is kept. This is the whole reason `classify_endpoint`
    exists rather than a field holding the string.
    """
    endpoint = "unix:///Users/anna/.colima/default/docker.sock"
    assert classify_endpoint(endpoint) == "unix"
    assert "anna" not in (classify_endpoint(endpoint) or "")


@pytest.mark.parametrize(
    ("host", "server", "same"),
    [
        ("AMD64", "x86_64", True),
        ("x86_64", "x86_64", True),
        ("arm64", "aarch64", True),
        ("arm64", "x86_64", False),
        ("AMD64", "aarch64", False),
    ],
)
def test_architecture_names_are_normalised_before_comparison(
    host: str, server: str, same: bool
) -> None:
    """Python says AMD64, docker says x86_64.

    Comparing them raw reported every Windows machine as running under
    emulation, which would have been the most confidently wrong finding in the
    tool.
    """
    assert (_normalise_arch(host) == _normalise_arch(server)) is same


def test_context_inspect_output_is_read_defensively() -> None:
    payload = json.dumps(
        [{"Name": "colima", "Endpoints": {"docker": {"Host": "unix:///x/.colima/docker.sock"}}}]
    )
    assert _parse_context(payload) == ("colima", "unix:///x/.colima/docker.sock")


@pytest.mark.parametrize("text", ["", "[]", "{}", "not json", '{"Endpoints": 5}'])
def test_malformed_context_output_is_not_an_error(text: str) -> None:
    assert _parse_context(text) == (None, None)


# --------------------------------------------------------------- findings


def _probe() -> ContainerProbe:
    ctx = ProbeContext(
        runner=_NullRunner(),
        platform="linux",
        platform_info=PlatformInfo(os_name="Linux", os_version="1", arch="x86_64"),
        env={"PATH": "/usr/bin"},
    )
    return ContainerProbe(ctx)


class _NullRunner:
    """Never invoked by `_depth_findings`, which takes state and returns findings."""

    def run(
        self,
        args: Sequence[str],
        *,
        timeout: float = 15.0,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
    ) -> CommandResult:  # pragma: no cover - defensive
        raise AssertionError(f"_depth_findings must not run commands, got {tuple(args)}")


def _ids(state: ContainerState) -> list[str]:
    return [f.rule_id for f in _probe()._depth_findings(state)]


def test_an_emulated_daemon_is_reported() -> None:
    """The build succeeds and takes ten times longer; nothing else says so."""
    ids = _ids(ContainerState(docker_daemon_ok=True, server_arch="aarch64", buildx_version="0.17"))
    assert "containers/arch-emulated" in ids


def test_a_matching_architecture_is_silent() -> None:
    ids = _ids(ContainerState(docker_daemon_ok=True, server_arch="x86_64", buildx_version="0.17"))
    assert "containers/arch-emulated" not in ids


def test_cgroup_v1_is_reported_and_v2_is_not() -> None:
    assert "containers/cgroup-v1" in _ids(ContainerState(cgroup_version="1"))
    assert "containers/cgroup-v1" not in _ids(ContainerState(cgroup_version="2"))


@pytest.mark.parametrize("driver", sorted(LEGACY_STORAGE_DRIVERS))
def test_every_legacy_storage_driver_is_reported(driver: str) -> None:
    assert "containers/storage-driver-legacy" in _ids(ContainerState(storage_driver=driver))


def test_overlay2_is_not_reported() -> None:
    assert "containers/storage-driver-legacy" not in _ids(ContainerState(storage_driver="overlay2"))


def test_reclaimable_space_is_reported_only_when_it_is_large() -> None:
    """Every machine that has built an image has a couple of gigabytes."""
    assert "containers/disk-reclaimable" not in _ids(ContainerState(reclaimable_bytes=3 * 1000**3))
    assert "containers/disk-reclaimable" in _ids(ContainerState(reclaimable_bytes=44 * 1000**3))


def test_the_tool_never_offers_to_prune_for_you() -> None:
    """Read-only by default: pruning removes data, so it stays a suggestion."""
    findings = _probe()._depth_findings(ContainerState(reclaimable_bytes=44 * 1000**3))
    hint = findings[0].remediation_hint or ""
    assert "docker system prune" in hint
    assert "does not run it" in hint


def test_two_engines_installed_is_information_not_a_problem() -> None:
    findings = _probe()._depth_findings(ContainerState(other_runtimes=("Colima", "Podman")))
    match = next(f for f in findings if f.rule_id == "containers/multiple-runtimes")
    assert match.state is FindingState.INFO


def test_one_engine_installed_says_nothing() -> None:
    assert "containers/multiple-runtimes" not in _ids(ContainerState(other_runtimes=("Podman",)))


def test_missing_buildx_is_reported_only_when_the_daemon_answers() -> None:
    """With the daemon down, "no buildx" is noise on top of a real blocker."""
    assert "containers/buildkit-unavailable" in _ids(ContainerState(docker_daemon_ok=True))
    assert "containers/buildkit-unavailable" not in _ids(ContainerState(docker_daemon_ok=False))


def test_a_daemon_that_is_down_still_yields_no_configuration_findings() -> None:
    """Nothing is known about an engine that did not answer, so nothing is said."""
    assert _ids(ContainerState(docker_cli_version="27.0.0", docker_daemon_ok=False)) == []


def test_every_finding_carries_evidence_and_a_component() -> None:
    state = ContainerState(
        docker_daemon_ok=True,
        server_arch="aarch64",
        cgroup_version="1",
        storage_driver="vfs",
        reclaimable_bytes=44 * 1000**3,
        other_runtimes=("Colima", "Podman"),
    )
    findings = _probe()._depth_findings(state)
    assert len(findings) == 6
    for finding in findings:
        assert finding.evidence, finding.rule_id
        assert finding.component == "docker", finding.rule_id


# ------------------------------------------------------- probe end-to-end


class _ArgvRunner:
    """Dispatches on a distinctive token in the argv, not on argv[0].

    `RecordingRunner` keys on the first token and consumes a queue in order,
    which for a probe that issues six different `docker` subcommands means the
    test silently mis-associates responses the moment the probe reorders a
    call. Matching on the subcommand keeps the test about behaviour rather
    than about call order.
    """

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


def _ok(stdout: str) -> CommandResult:
    return CommandResult(("x",), 0, stdout, "")


def test_the_probe_assembles_state_from_every_source() -> None:
    runner = _ArgvRunner(
        {
            "docker --version": _ok("Docker version 26.1.3, build abc"),
            "docker info": _ok(recorded_info("colima_macos_amd64_on_arm")),
            "docker context inspect": _ok(
                json.dumps(
                    [
                        {
                            "Name": "colima",
                            "Endpoints": {
                                "docker": {"Host": "unix:///Users/anna/.colima/docker.sock"}
                            },
                        }
                    ]
                )
            ),
            "docker buildx version": _ok("github.com/docker/buildx v0.17.1 abcdef"),
            "docker system df": _ok((RECORDINGS / "system_df.txt").read_text(encoding="utf-8")),
            "docker compose version": _ok("2.29.1"),
            "kubectl version": _ok('{"clientVersion":{"gitVersion":"v1.31.0"}}'),
        }
    )
    ctx = ProbeContext(
        runner=runner,
        platform="macos",
        platform_info=PlatformInfo(os_name="Darwin", os_version="15", arch="arm64"),
        env={"PATH": "/usr/bin"},
    )

    state = ContainerState.model_validate(ContainerProbe(ctx).run().data["state"])

    assert state.docker_daemon_ok is True
    assert state.backend == "colima"
    assert state.endpoint_kind == "unix"
    assert state.context_name == "colima"
    assert state.server_version == "26.1.3"
    assert state.storage_driver == "overlay2"
    assert state.cgroup_version == "2"
    assert state.buildx_version == "0.17.1"
    assert state.reclaimable_bytes is not None and state.reclaimable_bytes > 40 * 1000**3


def test_the_probe_never_stores_the_socket_path() -> None:
    """The privacy claim, checked against the serialized state a snapshot holds."""
    runner = _ArgvRunner(
        {
            "docker --version": _ok("Docker version 26.1.3, build abc"),
            "docker info": _ok(recorded_info("colima_macos_amd64_on_arm")),
            "docker context inspect": _ok(
                json.dumps(
                    [
                        {
                            "Name": "colima",
                            "Endpoints": {
                                "docker": {"Host": "unix:///Users/anna-surname/.colima/docker.sock"}
                            },
                        }
                    ]
                )
            ),
        }
    )
    ctx = ProbeContext(
        runner=runner,
        platform="macos",
        platform_info=PlatformInfo(os_name="Darwin", os_version="15", arch="x86_64"),
        env={"PATH": "/usr/bin"},
    )

    serialized = json.dumps(ContainerProbe(ctx).run().data["state"])

    assert "anna-surname" not in serialized
    assert "docker.sock" not in serialized


def test_an_emulated_colima_reaches_the_findings() -> None:
    """The wiring, not just the helper: arm64 host, x86_64 engine."""
    runner = _ArgvRunner(
        {
            "docker --version": _ok("Docker version 26.1.3, build abc"),
            "docker info": _ok(recorded_info("colima_macos_amd64_on_arm")),
            "docker buildx version": _ok("buildx v0.17.1"),
            "docker system df": _ok(""),
        }
    )
    ctx = ProbeContext(
        runner=runner,
        platform="macos",
        platform_info=PlatformInfo(os_name="Darwin", os_version="15", arch="arm64"),
        env={"PATH": "/usr/bin"},
    )

    ids = [f.rule_id for f in ContainerProbe(ctx).run().findings]
    assert "containers/arch-emulated" in ids


def test_a_daemon_that_is_down_still_names_the_backend() -> None:
    """`docker context inspect` answers whether or not the daemon is up.

    Which is the useful part: "Docker Desktop is not running" is actionable and
    "a daemon is not running" is not, and the difference is one command that
    works either way.
    """
    runner = _ArgvRunner(
        {
            "docker --version": _ok("Docker version 29.7.2, build abc"),
            "docker info": CommandResult(
                ("docker", "info"),
                1,
                "",
                "error during connect: open //./pipe/dockerDesktopLinuxEngine: "
                "The system cannot find the file specified.",
            ),
            "docker context inspect": _ok(
                json.dumps(
                    [
                        {
                            "Name": "desktop-linux",
                            "Endpoints": {
                                "docker": {"Host": "npipe:////./pipe/dockerDesktopLinuxEngine"}
                            },
                        }
                    ]
                )
            ),
        }
    )
    ctx = ProbeContext(
        runner=runner,
        platform="windows",
        platform_info=PlatformInfo(os_name="Windows", os_version="11", arch="AMD64"),
        env={"PATH": "C:" + chr(92) + "bin"},
    )

    result = ContainerProbe(ctx).run()
    state = ContainerState.model_validate(result.data["state"])

    assert state.docker_daemon_ok is False
    assert state.backend == "docker-desktop"
    assert state.endpoint_kind == "npipe"
    assert any(f.rule_id.startswith("containers/docker-daemon") for f in result.findings)
