"""Default probe registry and plugin loading."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from devrepro.probes.base import Probe, ProbeContext

__all__ = ["build_default_probes", "load_plugin_probes"]


def build_default_probes(ctx: "ProbeContext") -> list["Probe"]:
    """Instantiate every built-in probe applicable to this platform."""
    from devrepro.probes.containers import ContainerProbe
    from devrepro.probes.env_probe import EnvAuditProbe
    from devrepro.probes.gpu import GpuAiProbe
    from devrepro.probes.network import NetworkTlsProbe
    from devrepro.probes.path_env import PathProbe
    from devrepro.probes.ports import PortsServicesProbe
    from devrepro.probes.shell_profiles import ShellProfileProbe
    from devrepro.probes.system import CpuRamDiskProbe, OsKernelProbe, ShellProbe
    from devrepro.probes.toolchains import ToolchainProbe
    from devrepro.probes.virt import VirtualizationProbe, WslProbe

    classes = [
        OsKernelProbe,
        CpuRamDiskProbe,
        ShellProbe,
        PathProbe,
        EnvAuditProbe,
        ToolchainProbe,
        ShellProfileProbe,
        NetworkTlsProbe,
        ContainerProbe,
        WslProbe,
        VirtualizationProbe,
        GpuAiProbe,
        PortsServicesProbe,
    ]
    probes: list[Probe] = []
    for cls in classes:
        try:
            probe = cls(ctx)
        except Exception:  # noqa: BLE001 - registry must never crash
            continue
        if probe.supported():
            probes.append(probe)
    return probes


def load_plugin_probes(ctx: "ProbeContext") -> list["Probe"]:
    """Load third-party probes registered under entry point group
    ``devrepro.probes``. Failures are skipped, never fatal."""
    probes: list[Probe] = []
    try:
        from importlib.metadata import entry_points

        eps = entry_points(group="devrepro.probes")
    except Exception:  # noqa: BLE001
        return probes
    for ep in eps:
        try:
            obj = ep.load()
            probe = obj(ctx)  # type: ignore[call-arg]
            if probe.supported():
                probes.append(probe)
        except Exception:  # noqa: BLE001 - plugin isolation
            continue
    return probes