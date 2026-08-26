"""Tests for platform depth probes (Linux + macOS) and env-manager diagnostics."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

from devrepro.envmanagers.diagnostics import (
    inventory_project,
    parse_mise_toml_tools,
    parse_tool_versions,
    pinned_vs_active,
)
from devrepro.platforms.linux_probe import (
    cpu_governor,
    distro_info,
    fd_limits,
    inotify_limits,
)
from devrepro.platforms.macos_probe import brew_prefix_conflict, rosetta_status


def _reader(files: dict[str, str]) -> Callable[[str], str | None]:
    def read(name: str) -> str | None:
        return files.get(name)

    return read


# ------------------------------------------------------------------ linux ----

_UBUNTU = (
    'NAME="Ubuntu"\nVERSION_ID="24.04"\nID=ubuntu\nID_LIKE=debian\nPRETTY_NAME="Ubuntu 24.04 LTS"\n'
)
LINUX_LIMITS = (
    "Limit                     Soft           Hard\n"
    "Max open files            1024           4096\n"
    "Max processes             63348          63348\n"
)


class TestDistroInfo:
    def test_ubuntu_maps_to_debian_family_with_apt(self) -> None:
        info = distro_info(_reader({"/etc/os-release": _UBUNTU}))
        assert info.available
        assert info.family == "debian"
        assert "apt" in info.package_managers
        assert info.version == "24.04"

    def test_arch_derivative_via_id_like(self) -> None:
        manjaro = 'NAME="Manjaro Linux"\nID=manjaro\nID_LIKE=arch\n'
        info = distro_info(_reader({"/etc/os-release": manjaro}))
        assert info.family == "arch"
        assert "pacman" in info.package_managers

    def test_missing_os_release_is_unavailable_not_error(self) -> None:
        info = distro_info(_reader({}))
        assert not info.available
        assert info.family == "unknown"
        assert info.package_managers == ()

    def test_centos_inherits_fedora_family(self) -> None:
        centos = 'NAME="CentOS Stream"\nID=centos\nID_LIKE="rhel fedora"\n'
        assert distro_info(_reader({"/etc/os-release": centos})).family == "fedora"


class TestLimitsAndGovernor:
    def test_fd_limits_parsed_from_proc(self) -> None:
        limits = fd_limits(_reader({"/proc/self/limits": LINUX_LIMITS}))
        assert limits.soft == 1024
        assert limits.hard == 4096
        assert limits.source == "resource"

    def test_unlimited_values_become_none(self) -> None:
        text = "Limit  Soft     Hard\nMax open files  unlimited  unlimited\n"
        limits = fd_limits(_reader({"/proc/self/limits": text}))
        assert limits.soft is None and limits.hard is None

    def test_low_inotify_watches_produce_guidance(self) -> None:
        files = {
            "/proc/sys/fs/inotify/max_user_watches": "8192\n",
            "/proc/sys/fs/inotify/max_user_instances": "128\n",
        }
        info = inotify_limits(_reader(files))
        assert info.max_user_watches == 8192
        assert info.guidance and "524288" in info.guidance and "sysctl" in info.guidance

    def test_adequate_inotify_has_no_guidance(self) -> None:
        files = {"/proc/sys/fs/inotify/max_user_watches": "1048576\n"}
        info = inotify_limits(_reader(files))
        assert info.max_user_watches == 1048576
        assert info.guidance is None

    def test_cpu_governor_reported_when_present(self) -> None:
        gov = cpu_governor(
            _reader({"/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor": "powersave\n"})
        )
        assert gov.available and gov.governor == "powersave"

    def test_cpu_governor_absent_on_vms(self) -> None:
        gov = cpu_governor(_reader({}))
        assert not gov.available and gov.note


# ----------------------------------------------------------------- macos -----


class _FakeRunner:
    """Minimal CommandRunner stand-in driven by a lookup table."""

    def __init__(self, responses: dict[tuple[str, ...], tuple[int, str]]) -> None:
        self._responses = responses

    def run(self, argv: tuple[str, ...], timeout: float | None = None, **kw: object):  # type: ignore[no-untyped-def]
        from devrepro.core.runner import CommandResult

        code, out = self._responses.get(argv, (1, ""))
        return CommandResult(command=argv, returncode=code, stdout=out, stderr="")


class TestMacosDepth:
    def test_rosetta_translation_detected(self) -> None:
        runner = _FakeRunner(
            {
                ("uname", "-m"): (0, "arm64\n"),
                ("sysctl", "-n", "sysctl.proc_translated"): (0, "1\n"),
            }
        )
        status = rosetta_status(runner)  # type: ignore[arg-type]
        assert status.machine == "arm64" and status.translated is True

    def test_homebrew_arm64_conflict_flagged(self) -> None:
        runner = _FakeRunner({("brew", "--prefix"): (0, "/usr/local\n")})
        info = brew_prefix_conflict(runner, "arm64")  # type: ignore[arg-type]
        assert info.conflict
        assert info.note and "mixed-arch" in info.note

    def test_homebrew_correct_prefix_no_conflict(self) -> None:
        runner = _FakeRunner({("brew", "--prefix"): (0, "/opt/homebrew\n")})
        info = brew_prefix_conflict(runner, "arm64")  # type: ignore[arg-type]
        assert not info.conflict


# ---------------------------------------------------- env managers ----------


class TestEnvManagers:
    def test_tool_versions_parsed_with_comments(self) -> None:
        pins = parse_tool_versions("# comment\nnodejs 20.11.0\npython 3.12 3.11\n")
        names = [(p.name, p.version) for p in pins]
        assert ("nodejs", "20.11.0") in names
        assert ("python", "3.12") in names and ("python", "3.11") in names

    def test_mise_tools_table_parsed(self) -> None:
        text = (
            "[settings]\nlegacy_version_file = false\n\n"
            '[tools]\nnode = "22.2.0"\n'
            'python = { version = "3.12", virtualenv = ".venv" }\n'
        )
        pins = parse_mise_toml_tools(text)
        got = {p.name: p.version for p in pins}
        assert got["node"] == "22.2.0"
        assert got["python"] == "3.12"

    def test_inventory_detects_locked_flake_and_devbox(self, tmp_path: Path) -> None:
        (tmp_path / "flake.nix").write_text("{}\n", encoding="utf-8")
        (tmp_path / "flake.lock").write_text("{}\n", encoding="utf-8")
        (tmp_path / "devbox.json").write_text("{}\n", encoding="utf-8")  # no lock!
        inv = inventory_project(tmp_path)
        kinds = {m.manager: m for m in inv.managers}
        assert kinds["nix"].locked is True
        assert kinds["devbox"].locked is False
        warnings = [f.message for f in inv.findings if f.manager == "devbox"]
        assert warnings and "devbox lock" in warnings[0]

    def test_inventory_flags_envrc_and_dual_pinning(self, tmp_path: Path) -> None:
        (tmp_path / ".tool-versions").write_text("nodejs 18\n", encoding="utf-8")
        (tmp_path / "mise.toml").write_text('[tools]\nnode = "22"\n', encoding="utf-8")
        (tmp_path / ".envrc").write_text("use flake\n", encoding="utf-8")
        inv = inventory_project(tmp_path)
        managers = {m.manager for m in inv.managers}
        assert {"asdf", "mise", "direnv"} <= managers
        msgs = [f.message for f in inv.findings]
        assert any("duplicate pinning" in m for m in msgs)
        assert any("executable shell code" in m for m in msgs)

    def test_pinned_vs_active_major_mismatch_warns(self) -> None:
        from devrepro.envmanagers.diagnostics import PinnedTool

        pins = (
            PinnedTool("node", "22.2.0", "mise.toml"),
            PinnedTool("python", "3.12.4", ".tool-versions"),
            PinnedTool("go", "1.22", ".tool-versions"),
        )
        findings = pinned_vs_active(pins, {"node": "18.19.1", "python": "3.12.7"})
        assert any(f.severity == "warn" and f.message.startswith("node:") for f in findings)
        assert any(f.message.startswith("python:") for f in findings)
        go_findings = [f for f in findings if f.message.startswith("go")]
        assert go_findings and go_findings[0].severity == "info"

    def test_empty_project_has_no_managers(self, tmp_path: Path) -> None:
        inv = inventory_project(tmp_path)
        assert inv.managers == () and inv.pins == () and inv.findings == ()


# ------------------------------------------------------------------ CLI ------

from devrepro.cli.app import app  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

_cli = CliRunner()


class TestCliCommands:
    def test_platform_depth_runs_on_any_host(self) -> None:
        result = _cli.invoke(app, ["platform-depth", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["host_system"] in {"windows", "linux", "darwin"}

    def test_envmanagers_empty_project_ready(self, tmp_path: Path) -> None:
        result = _cli.invoke(app, ["envmanagers", str(tmp_path), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["managers"] == [] and data["findings"] == []
