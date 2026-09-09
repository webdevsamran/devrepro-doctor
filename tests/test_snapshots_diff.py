"""Snapshot round-trip, diff classification and history drift."""

from __future__ import annotations

import json

from devrepro.core.models import (
    ContainerState,
    DiffClassification,
    GpuStack,
    PlatformInfo,
    Snapshot,
    ToolInstallation,
    WslState,
)
from devrepro.diff.engine import diff_snapshots
from devrepro.snapshots.history import compute_drift
from devrepro.snapshots.store import load_snapshot, save_snapshot


def _snap(sid: str, pyver: str, extra_tool: bool = False) -> Snapshot:
    tools = [ToolInstallation(name="python", version=pyver, exe_path="/usr/bin/python")]
    if extra_tool:
        tools.append(ToolInstallation(name="docker", version="24.0.7", exe_path="/usr/bin/docker"))
    snap = Snapshot(
        devrepro_version="0.1.0",
        platform=PlatformInfo(os_name="Linux", os_version="6.5", arch="x86_64"),
        tools=tuple(tools),
    )
    object.__setattr__(snap, "_label", sid)
    return snap


def test_roundtrip(tmp_path) -> None:
    s = _snap("t1", "3.12.4")
    p = save_snapshot(s, tmp_path / "s.json")
    loaded = load_snapshot(p)
    assert loaded.snapshot_id == s.snapshot_id
    assert loaded.tools[0].version == "3.12.4"


def test_version_drift_classified() -> None:
    d = diff_snapshots(_snap("a", "3.11.8"), _snap("b", "3.12.4"))
    entry = next(e for e in d.entries if e.name == "python")
    assert entry.classification == DiffClassification.VERSION_DRIFT


def test_missing_tool_classified() -> None:
    d = diff_snapshots(_snap("a", "3.12.4"), _snap("b", "3.12.4", extra_tool=True))
    docker = next(e for e in d.entries if e.name == "docker")
    assert docker.classification == DiffClassification.MISSING


def test_same_snapshot_all_same() -> None:
    d = diff_snapshots(_snap("a", "3.12.4"), _snap("b", "3.12.4"))
    assert all(e.classification == DiffClassification.SAME for e in d.entries)


def test_diff_json_serializable() -> None:
    d = diff_snapshots(_snap("a", "3.11"), _snap("b", "3.12"))
    payload = json.dumps(d.model_dump(mode="json"), default=str)
    assert "version-drift" in payload


def test_drift_kinds() -> None:
    items = compute_drift(_snap("prev", "3.11.8"), _snap("cur", "3.12.4"))
    kinds = {i.kind for i in items}
    assert "runtime-changed" in kinds


# --- container / WSL / GPU drift -------------------------------------------
#
# These comparisons existed (or were promised by the section header) but could
# never fire: `snapshot_from_report` hardcoded containers/wsl/gpu to None
# because `ScanReport` never carried them, so both sides of every comparison
# were always None. The probes had been collecting the state all along.


def _machine(
    *,
    daemon_ok: bool = True,
    docker_cli: str = "29.7.2",
    cuda: str | None = "12.4",
    wsl_distro: str | None = None,
) -> Snapshot:
    return Snapshot(
        devrepro_version="0.1.0",
        platform=PlatformInfo(os_name="Linux", os_version="6.5", arch="x86_64"),
        containers=ContainerState(docker_cli_version=docker_cli, docker_daemon_ok=daemon_ok),
        gpu=GpuStack(cuda_toolkit=cuda),
        wsl=WslState(available=wsl_distro is not None, default_distro=wsl_distro),
    )


def _entry(diff, component: str, name: str):
    return next((e for e in diff.entries if e.component == component and e.name == name), None)


def test_docker_daemon_health_difference_is_project_critical() -> None:
    diff = diff_snapshots(_machine(daemon_ok=True), _machine(daemon_ok=False))
    entry = _entry(diff, "container", "docker-daemon")
    assert entry is not None, "docker daemon drift not reported"
    assert entry.project_critical is True
    assert entry.classification is DiffClassification.PROJECT_CRITICAL


def test_docker_cli_version_difference_is_version_drift() -> None:
    diff = diff_snapshots(_machine(docker_cli="29.7.2"), _machine(docker_cli="24.0.7"))
    entry = _entry(diff, "container", "docker-cli")
    assert entry is not None
    assert entry.classification is DiffClassification.VERSION_DRIFT
    assert entry.a_value == "29.7.2" and entry.b_value == "24.0.7"


def test_cuda_toolkit_difference_is_project_critical() -> None:
    """The classic 'trains here, not there' cause."""
    diff = diff_snapshots(_machine(cuda="12.4"), _machine(cuda="11.8"))
    entry = _entry(diff, "gpu", "cuda-toolkit")
    assert entry is not None
    assert entry.project_critical is True


def test_wsl_default_distro_difference_is_reported() -> None:
    diff = diff_snapshots(_machine(wsl_distro="Ubuntu"), _machine(wsl_distro="docker-desktop"))
    entry = _entry(diff, "wsl", "wsl-default-distro")
    assert entry is not None
    assert entry.a_value == "Ubuntu" and entry.b_value == "docker-desktop"


def test_identical_machines_report_no_container_wsl_or_gpu_drift() -> None:
    diff = diff_snapshots(_machine(), _machine())
    assert not [e for e in diff.entries if e.component in {"container", "wsl", "gpu"}]


def test_absent_on_both_sides_is_not_drift() -> None:
    """Neither machine reporting a capability is silence, not a difference."""
    bare = Snapshot(
        devrepro_version="0.1.0",
        platform=PlatformInfo(os_name="Linux", os_version="6.5", arch="x86_64"),
    )
    diff = diff_snapshots(bare, bare)
    assert not [e for e in diff.entries if e.component in {"container", "wsl", "gpu"}]


def test_snapshot_from_report_propagates_probe_state() -> None:
    """A Snapshot must carry what the scan collected.

    `snapshot_from_report` hardcoded these to None, so container/WSL/GPU drift
    was structurally unreportable no matter what the probes found.
    """
    from devrepro.core.models import ScanReport
    from devrepro.snapshots.store import snapshot_from_report

    report = ScanReport(
        devrepro_version="0.1.0",
        platform=PlatformInfo(os_name="Linux", os_version="6.5", arch="x86_64"),
        containers=ContainerState(docker_cli_version="29.7.2", docker_daemon_ok=False),
        wsl=WslState(available=True, default_distro="Ubuntu"),
        gpu=GpuStack(cuda_toolkit="12.4"),
    )
    snap = snapshot_from_report(report)
    assert snap.containers is not None and snap.containers.docker_cli_version == "29.7.2"
    assert snap.wsl is not None and snap.wsl.default_distro == "Ubuntu"
    assert snap.gpu is not None and snap.gpu.cuda_toolkit == "12.4"
