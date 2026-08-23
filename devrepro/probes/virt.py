"""Virtualization probes: WSL diagnostics (Windows host) and generic
virtualization hints. WSL probe reports distros/version/default/interop
without exposing private distro paths.
"""

from __future__ import annotations

import re

from devrepro.core.models import Evidence, FindingState, WslState
from devrepro.probes.base import Probe, ProbeResult

__all__ = ["VirtualizationProbe", "WslProbe"]


class WslProbe(Probe):
    id = "virt/wsl"
    version = "1"
    platforms = ("windows",)

    def run(self) -> ProbeResult:
        r = self.ctx.runner
        findings = []
        errors: list[str] = []

        status = r.run(("wsl", "--status"), timeout=15)
        version: str | None = None
        default_distro: str | None = None
        if status.ok:
            text = status.stdout
            m = re.search(r"WSL(?:\s+version)?:?\s*(\d+(?:\.\d+)*)", text, re.IGNORECASE)
            if m:
                version = m.group(1)
            m2 = re.search(r"Default Distribution:\s*(.+)", text, re.IGNORECASE)
            if m2:
                default_distro = m2.group(1).strip()

        list_out = r.run(("wsl", "-l", "-v"), timeout=15)
        distros: list[str] = []
        if list_out.ok:
            # Output may be UTF-16 on Windows; normalize defensively.
            text = list_out.stdout
            if "\x00" in text:
                text = text.replace("\x00", "")
            for raw_line in text.splitlines()[1:]:
                stripped = raw_line.strip()
                if not stripped:
                    continue
                name = re.split(r"\s{2,}", stripped)[0].strip()
                if name and not name.lower().startswith("windows"):
                    distros.append(name)

        interop: bool | None = None
        if distros:
            cat = r.run(("wsl", "-e", "test", "-e", "/init"), timeout=15)
            interop = cat.returncode == 0

        available = bool(distros) or status.ok
        state = WslState(
            available=available,
            version=version,
            distros=tuple(distros),
            default_distro=default_distro,
            interop_enabled=interop,
            errors=tuple(errors),
        )

        if available:
            findings.append(
                self.finding(
                    "wsl/detected",
                    FindingState.INFO,
                    f"WSL available (version {version or 'unknown'}), "
                    f"{len(distros)} distro(s), default: {default_distro or 'unset'}.",
                    evidence=(self.cmd_evidence(("wsl", "--status"), status.stdout[:300]),),
                    detected=version,
                    component="wsl",
                )
            )
            if default_distro is None and distros:
                findings.append(
                    self.finding(
                        "wsl/no-default-distro",
                        FindingState.WARN,
                        "No default WSL distro set; tools relying on `wsl` will fail.",
                        evidence=(self.cmd_evidence(("wsl", "--status"), status.stdout[:300]),),
                        component="wsl",
                        remediation_hint="Run `wsl --set-default <distro>` (SAFE).",
                    )
                )
        else:
            findings.append(
                self.finding(
                    "wsl/not-installed",
                    FindingState.INFO,
                    "WSL not installed or not initialized.",
                    evidence=(
                        Evidence(
                            source="command",
                            command=("wsl", "--status"),
                            excerpt=(status.stderr or "no output")[:300],
                        ),
                    ),
                    component="wsl",
                )
            )

        return ProbeResult(
            self.id, findings=tuple(findings), data={"state": state.model_dump(mode="json")}
        )


class VirtualizationProbe(Probe):
    id = "virt/generic"
    version = "1"

    def run(self) -> ProbeResult:
        r = self.ctx.runner
        data: dict[str, object] = {}
        findings = []
        if self.ctx.platform == "macos":
            res = r.run(("sysctl", "-n", "kern.hv_vmm_present"), timeout=5)
            data["hypervisor_present"] = res.stdout.strip() == "1"
        elif self.ctx.platform == "linux":
            cpuinfo = r.run(("grep", "-c", "vmx\\|svm", "/proc/cpuinfo"), timeout=5)
            try:
                count = int(cpuinfo.stdout.strip())
            except ValueError:
                count = 0
            data["virtualization_cpu_flags"] = count > 0
        else:
            res = r.run(("systeminfo",), timeout=30)
            text = res.stdout
            data["hyper_v"] = ("Hyper-V Requirements" in text) or (
                "A hypervisor has been detected" in text
            )

        findings.append(
            self.finding(
                "virt/status",
                FindingState.INFO,
                "Virtualization capability checked.",
                evidence=(Evidence(source="system", excerpt=str(data)),),
                component="virtualization",
            )
        )
        return ProbeResult(self.id, findings=tuple(findings), data=data)
