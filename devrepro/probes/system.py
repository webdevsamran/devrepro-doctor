"""System probes: OS/kernel, CPU/RAM/disk, shell."""

from __future__ import annotations

import os
import platform as pyplatform
import shutil
import subprocess  # noqa: S404 - only for read-only system queries

from devrepro.core.models import Evidence, FindingState
from devrepro.probes.base import Probe, ProbeResult

__all__ = ["OsKernelProbe", "CpuRamDiskProbe", "ShellProbe"]


class OsKernelProbe(Probe):
    id = "system/os"
    version = "1"

    def run(self) -> ProbeResult:
        u = pyplatform.uname()
        data = {
            "os": u.system,
            "os_release": u.release,
            "os_version": u.version.split()[0] if u.version else "",
            "arch": u.machine,
            "kernel": f"{u.system} {u.release}",
        }
        ev = Evidence(source="system", excerpt=f"{u.system} {u.release} {u.machine}")
        finding = self.finding(
            "system/os-detected",
            FindingState.INFO,
            f"OS: {u.system} {u.release} ({u.machine})",
            evidence=(ev,),
            detected=data["kernel"],
            component="os",
        )
        return ProbeResult(self.id, findings=(finding,), data=data)


class CpuRamDiskProbe(Probe):
    id = "system/resources"
    version = "1"

    def run(self) -> ProbeResult:
        data: dict[str, object] = {"cpu_count": os.cpu_count()}
        ram_total = self._ram_total_bytes()
        if ram_total is not None:
            data["ram_gb"] = round(ram_total / 1024**3, 1)
        disk_free = self._disk_free_bytes()
        if disk_free is not None:
            data["disk_free_gb"] = round(disk_free / 1024**3, 1)
        excerpt = "; ".join(f"{k}={v}" for k, v in sorted(data.items()))
        ev = Evidence(source="system", excerpt=excerpt)
        finding = self.finding(
            "system/resources",
            FindingState.INFO,
            f"Resources: {excerpt}",
            evidence=(ev,),
            component="hardware",
        )
        return ProbeResult(self.id, findings=(finding,), data=data)

    @staticmethod
    def _ram_total_bytes() -> int | None:
        try:
            if hasattr(os, "sysconf"):
                pages = os.sysconf("SC_PHYS_PAGES")  # type: ignore[attr-defined]
                page_size = os.sysconf("SC_PAGE_SIZE")  # type: ignore[attr-defined]
                return int(pages) * int(page_size)
        except (ValueError, OSError):
            pass
        try:
            out = subprocess.run(  # noqa: S603
                ["wmic", "ComputerSystem", "get", "TotalPhysicalMemory"],
                capture_output=True, text=True, timeout=10, check=False,
            )
            for line in out.stdout.splitlines():
                line = line.strip()
                if line.isdigit():
                    return int(line)
        except Exception:  # noqa: BLE001
            pass
        return None

    @staticmethod
    def _disk_free_bytes() -> int | None:
        try:
            usage = shutil.disk_usage(os.getcwd())
            return usage.free
        except OSError:
            return None


class ShellProbe(Probe):
    id = "system/shell"
    version = "1"

    def run(self) -> ProbeResult:
        shell_name: str | None = None
        if self.ctx.platform == "windows":
            shell_name = "powershell" if os.environ.get("PSModulePath") else "cmd"
        else:
            shell_name = os.path.basename(str(os.environ.get("SHELL", ""))) or None
        data = {"shell": shell_name}
        ev = Evidence(source="env", excerpt=f"SHELL={shell_name or 'unknown'}")
        finding = self.finding(
            "system/shell",
            FindingState.INFO,
            f"Shell: {shell_name or 'unknown'}",
            evidence=(ev,),
            detected=shell_name,
            component="shell",
        )
        return ProbeResult(self.id, findings=(finding,), data=data)