"""Probes driven by recorded machine output, as AGENTS.md says they are.

`tests/fixtures/recordings/` has held reviewable captures of Windows, Ubuntu,
Fedora, macOS, WSL and Docker output since the first commit, and until now
nothing loaded any of it: no test imported a `Probe` subclass, and the
`RecordingRunner` those fixtures were meant to feed raised `AttributeError` on
every call (it used `dataclasses.field()` outside a dataclass). This file is
what makes the claim true.

Assertions here must hold on all twelve CI legs. That rules out anything
depending on the host: `PathProbe` calls `os.path.normcase` and `Path.is_dir()`
directly, so normalisation and liveness follow the machine running the tests,
not `ctx.platform`. Only host-independent properties are asserted.
"""

from __future__ import annotations

import pytest
from devrepro.core.models import FindingState
from devrepro.core.runner import CommandResult
from devrepro.probes.containers import ContainerProbe, _classify_daemon_error
from devrepro.probes.path_env import PathProbe

from conftest import make_ctx, recorded_docker_failures, recorded_path

RECORDED_MACHINES = ("windows", "ubuntu", "fedora", "macos")


def _analysis(machine: str):
    platform = "windows" if machine == "windows" else "linux"
    ctx = make_ctx(platform=platform, env={"PATH": recorded_path(machine)})
    result = PathProbe(ctx).run()
    assert result.error is None, f"{machine}: probe errored: {result.error}"
    return result, result.data["analysis"]


@pytest.mark.parametrize("machine", RECORDED_MACHINES)
def test_recorded_path_is_parsed_into_entries(machine: str) -> None:
    """Every recorded PATH parses, and entry order is preserved."""
    _, analysis = _analysis(machine)
    entries = analysis["entries"]
    assert entries, f"{machine}: no PATH entries parsed"
    assert [e["index"] for e in entries] == list(range(len(entries)))


def test_windows_recording_detects_the_duplicate_entry() -> None:
    r"""The Windows capture lists `C:\Program Files\Git\cmd` twice."""
    result, analysis = _analysis("windows")
    assert analysis["duplicates"], "duplicate PATH entry not detected"
    assert any("Git" in d for d in analysis["duplicates"])
    assert "path/duplicates" in {f.rule_id for f in result.findings}


def test_windows_recording_detects_the_store_alias() -> None:
    """WindowsApps aliases shadow real installs and must be reported."""
    result, analysis = _analysis("windows")
    assert analysis["store_aliases"], "Store alias not detected"
    assert any("WindowsApps" in a for a in analysis["store_aliases"])
    assert "path/store-aliases" in {f.rule_id for f in result.findings}


@pytest.mark.parametrize(
    ("machine", "manager"),
    [("ubuntu", ".pyenv"), ("ubuntu", ".nvm"), ("macos", ".nvm"), ("macos", ".pyenv")],
)
def test_recordings_detect_tool_manager_interference(machine: str, manager: str) -> None:
    """Version-manager shims on PATH are the classic shadowing cause."""
    _, analysis = _analysis(machine)
    joined = " ".join(analysis["tool_manager_interference"])
    assert manager in joined, f"{machine}: {manager} not reported as interference"


def test_every_finding_carries_evidence() -> None:
    """`AGENTS.md`: a Finding without an Evidence is not a finding."""
    for machine in RECORDED_MACHINES:
        result, _ = _analysis(machine)
        for finding in result.findings:
            assert finding.evidence, f"{machine}: {finding.rule_id} has no evidence"


# --------------------------------------------------------------- docker


@pytest.mark.parametrize("case", sorted(recorded_docker_failures()))
def test_recorded_docker_failures_classify_as_recorded(case: str) -> None:
    """The recorded stderr must classify the way the fixture claims.

    Two labels in that fixture were wrong when it was first wired up, because
    nothing had ever loaded it.
    """
    record = recorded_docker_failures()[case]
    assert _classify_daemon_error(str(record["stderr"])) == record["classification"]


def test_container_probe_reports_blocked_when_the_daemon_is_unreachable() -> None:
    """Drive the whole probe, not just the classifier."""
    failure = recorded_docker_failures()["daemon_socket_missing"]
    ctx = make_ctx(
        {
            "docker": [
                CommandResult(("docker", "--version"), 0, "Docker version 29.7.2, build abc", ""),
                CommandResult(
                    ("docker", "info"), int(failure["returncode"]), "", str(failure["stderr"])
                ),
            ]
        }
    )
    result = ContainerProbe(ctx).run()
    assert result.error is None
    blocked = [f for f in result.findings if f.state is FindingState.BLOCKED]
    assert blocked, "an unreachable daemon must produce a BLOCKED finding"
    assert blocked[0].rule_id == "containers/docker-daemon-unreachable"
    assert blocked[0].evidence, "finding must carry evidence"
    assert result.data["state"]["docker_daemon_ok"] is False


def test_container_probe_reports_missing_cli_without_crashing() -> None:
    """An absent binary is a normal result, never an exception."""
    result = ContainerProbe(make_ctx()).run()
    assert result.error is None
    assert "containers/docker-missing" in {f.rule_id for f in result.findings}
