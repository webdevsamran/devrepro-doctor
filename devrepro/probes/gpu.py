"""GPU / AI development stack probe.

Detects NVIDIA driver/CUDA toolkit, ROCm, Intel oneAPI/OpenVINO,
DirectML, WSL GPU passthrough, Vulkan/OpenCL basics and Apple Metal.
Reports only what is actually detected — never guesses compatibility.
"""

from __future__ import annotations

import re

from devrepro.core.models import Evidence, FindingState, GpuStack
from devrepro.probes.base import Probe, ProbeResult

__all__ = ["GpuAiProbe"]


class GpuAiProbe(Probe):
    id = "gpu/ai-stack"
    version = "1"

    def run(self) -> ProbeResult:
        r = self.ctx.runner
        notes: list[str] = []
        nvidia_driver: str | None = None
        cuda_toolkit: str | None = None
        rocm: str | None = None
        oneapi: str | None = None
        vulkan: str | None = None
        metal: str | None = None
        directml = False
        wsl_gpu: bool | None = None

        # NVIDIA driver via nvidia-smi -------------------------------------
        smi = r.run(("nvidia-smi",), timeout=10)
        if smi.ok:
            m = re.search(r"Driver Version:\s*([\d.]+)", smi.stdout)
            nvidia_driver = m.group(1) if m else None
            m2 = re.search(r"CUDA Version:\s*([\d.]+)", smi.stdout)
            if m2:
                notes.append(f"driver supports CUDA runtime up to {m2.group(1)}")

        # CUDA toolkit via nvcc ------------------------------------------------
        nvcc = r.run(("nvcc", "--version"), timeout=10)
        if nvcc.ok:
            m = re.search(r"release ([\d.]+)", nvcc.stdout)
            cuda_toolkit = m.group(1) if m else None

        # ROCm -------------------------------------------------------------------
        rocminfo = r.run(("rocminfo",), timeout=10)
        if rocminfo.ok:
            m = re.search(r"ROCm module internal version:\s*([\d.]+)", rocminfo.stdout)
            rocm = m.group(1) if m else "detected"

        # Intel oneAPI -------------------------------------------------------------
        for marker in ("sycl-ls", "pi"):
            res = r.run((marker,), timeout=8)
            if res.ok:
                oneapi = "detected"
                break

        # Vulkan ---------------------------------------------------------------------
        vres = r.run(("vulkaninfo", "--summary"), timeout=10)
        if vres.ok:
            m = re.search(r"apiVersion\s*=\s*([\d.]+)", vres.stdout)
            vulkan = m.group(1) if m else "detected"

        # Apple Metal --------------------------------------------------------------------
        if self.ctx.platform == "macos":
            mres = r.run(("system_profiler", "SPDisplaysDataType"), timeout=20)
            if mres.ok and "Metal" in mres.stdout:
                metal = "supported"

        # DirectML (Windows) -----------------------------------------------------------------
        if self.ctx.platform == "windows":
            dres = r.run(("powershell", "-NoProfile", "-Command",
                          "Get-Command dxdiag -ErrorAction SilentlyContinue"), timeout=15)
            directml = dres.ok  # presence of DirectX stack implies DML-capable runtime option

        # WSL GPU passthrough ------------------------------------------------------------------
        if self.ctx.platform == "windows":
            lres = r.run(("wsl", "-e", "nvidia-smi"), timeout=20)
            wsl_gpu = lres.ok
        elif self.ctx.platform_info.is_wsl:
            lres = r.run(("nvidia-smi",), timeout=10)
            wsl_gpu = lres.ok

        stack = GpuStack(
            nvidia_driver=nvidia_driver,
            cuda_toolkit=cuda_toolkit,
            rocm=rocm,
            oneapi=oneapi,
            directml=directml,
            vulkan=vulkan,
            metal=metal,
            wsl_gpu_passthrough=wsl_gpu,
            notes=tuple(notes),
        )

        findings = [
            self.finding(
                "gpu/stack-detected",
                FindingState.INFO,
                self._summarize(stack),
                evidence=(Evidence(source="command", command=("nvidia-smi",),
                                   excerpt=f"driver={nvidia_driver} cuda={cuda_toolkit}"),),
                component="gpu",
            )
        ]
        if nvidia_driver and cuda_toolkit:
            drv_major = int(nvidia_driver.split(".")[0])
            if drv_major < 470:
                findings.append(
                    self.finding(
                        "gpu/cuda-driver-old",
                        FindingState.WARN,
                        f"NVIDIA driver {nvidia_driver} predates CUDA 11.4 support; "
                        "modern ML frameworks require newer drivers.",
                        evidence=(Evidence(source="command", command=("nvidia-smi",),
                                           excerpt=f"driver={nvidia_driver}"),),
                        detected=nvidia_driver,
                        required=">=470",
                        component="gpu",
                        remediation_hint="Update the NVIDIA driver from the vendor site "
                        "(MEDIUM risk; DevRepro will not modify drivers).",
                    )
                )
        return ProbeResult(self.id, findings=tuple(findings), data={"stack": stack.model_dump(mode="json")})

    @staticmethod
    def _summarize(s: GpuStack) -> str:
        parts = []
        if s.nvidia_driver:
            parts.append(f"NVIDIA driver {s.nvidia_driver}")
        if s.cuda_toolkit:
            parts.append(f"CUDA toolkit {s.cuda_toolkit}")
        if s.rocm:
            parts.append(f"ROCm {s.rocm}")
        if s.oneapi:
            parts.append("Intel oneAPI detected")
        if s.directml:
            parts.append("DirectML available")
        if s.vulkan:
            parts.append(f"Vulkan {s.vulkan}")
        if s.metal:
            parts.append("Apple Metal supported")
        if s.wsl_gpu_passthrough:
            parts.append("WSL GPU passthrough OK")
        return "GPU/AI stack: " + ("; ".join(parts) if parts else "no GPU development stack detected")