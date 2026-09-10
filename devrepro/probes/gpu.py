"""GPU / AI development stack probe.

Detects NVIDIA driver/CUDA toolkit, ROCm, Intel oneAPI/OpenVINO, DirectML, WSL
GPU passthrough, Vulkan/OpenCL basics and Apple Metal.

The version comparison lives in `devrepro.platforms.cuda`, which explains why
"GPU not found" is the least useful answer available: what fails is the
relationship between the driver's runtime ceiling, the installed toolkit and
the framework build, and the error message names none of the three. The ceiling
is read from `nvidia-smi` rather than looked up in a table, because the machine
already knows and a bundled table would be wrong within a release.
"""

from __future__ import annotations

import re

from devrepro.core.models import Evidence, FindingState, GpuDeviceInfo, GpuStack
from devrepro.platforms.cuda import (
    compare_toolkit_to_driver,
    mixed_architectures,
    parse_query_gpu,
    parse_smi_header,
)
from devrepro.probes.base import Probe, ProbeResult

__all__ = ["GpuAiProbe"]

#: The one command that answers what a framework wheel was built for.
#: Named rather than run: importing torch takes seconds, allocates, and can
#: initialise a context on a device somebody else is training on.
TORCH_HINT = '`python -c "import torch; print(torch.version.cuda)"`'


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
        max_cuda: str | None = None
        devices: tuple[GpuDeviceInfo, ...] = ()
        smi = r.run(("nvidia-smi",), timeout=10)
        if smi.ok:
            state = parse_smi_header(smi.stdout)
            nvidia_driver = state.driver
            max_cuda = state.max_cuda
            if max_cuda:
                notes.append(f"driver supports CUDA runtime up to {max_cuda}")

            # Structured enumeration, for the mixed-device case. Attempted
            # second and allowed to fail: `--query-gpu=compute_cap` needs a
            # driver newer than plenty still in service, and a probe that only
            # handles the good case reports "no GPU" on exactly the machines
            # most likely to have a version problem.
            query = r.run(
                (
                    "nvidia-smi",
                    "--query-gpu=index,name,memory.total,compute_cap",
                    "--format=csv,noheader",
                ),
                timeout=10,
            )
            if query.ok:
                devices = tuple(
                    GpuDeviceInfo(
                        index=d.index,
                        name=d.name,
                        memory_mib=d.memory_mib,
                        compute_capability=d.compute_capability,
                    )
                    for d in parse_query_gpu(query.stdout)
                )

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
            dres = r.run(
                (
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-Command dxdiag -ErrorAction SilentlyContinue",
                ),
                timeout=15,
            )
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
            max_cuda_runtime=max_cuda,
            devices=devices,
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
                evidence=(
                    Evidence(
                        source="command",
                        command=("nvidia-smi",),
                        excerpt=f"driver={nvidia_driver} cuda={cuda_toolkit}",
                    ),
                ),
                component="gpu",
            )
        ]
        # The triple, rather than a presence check. Silent when there is nothing
        # to say: a machine with no NVIDIA hardware gets no finding about a
        # missing driver, because that is not a fault.
        verdict = compare_toolkit_to_driver(cuda_toolkit, max_cuda)
        if verdict.ok is False:
            findings.append(
                self.finding(
                    "gpu/cuda-driver-too-old",
                    FindingState.WARN,
                    verdict.summary,
                    evidence=(
                        Evidence(
                            source="command",
                            command=("nvidia-smi",),
                            excerpt=f"driver={nvidia_driver} max_cuda={max_cuda} "
                            f"toolkit={cuda_toolkit}",
                        ),
                    ),
                    detected=verdict.detected,
                    required=verdict.required,
                    component="gpu",
                    remediation_hint=(
                        "Update the NVIDIA driver, or install a toolkit inside the "
                        "major version the driver supports. DevRepro will not modify "
                        "drivers. To see what your framework build expects, run " + TORCH_HINT + "."
                    ),
                )
            )
        elif verdict.ok is True:
            findings.append(
                self.finding(
                    "gpu/cuda-compatible",
                    FindingState.PASS,
                    verdict.summary,
                    evidence=(
                        Evidence(
                            source="command",
                            command=("nvidia-smi",),
                            excerpt=f"max_cuda={max_cuda} toolkit={cuda_toolkit}",
                        ),
                    ),
                    detected=verdict.detected,
                    required=verdict.required,
                    component="gpu",
                )
            )
        elif nvidia_driver and not cuda_toolkit:
            findings.append(
                self.finding(
                    "gpu/cuda-toolkit-absent",
                    FindingState.INFO,
                    verdict.summary,
                    evidence=(
                        Evidence(
                            source="command",
                            command=("nvcc", "--version"),
                            excerpt=verdict.unknown_because or "nvcc did not answer",
                        ),
                    ),
                    required=verdict.required,
                    component="gpu",
                    remediation_hint=(
                        "Only needed to compile CUDA code. A framework wheel ships "
                        "its own runtime and does not need nvcc."
                    ),
                )
            )

        architectures = mixed_architectures(d.compute_capability for d in devices)
        if architectures:
            findings.append(
                self.finding(
                    "gpu/mixed-architectures",
                    FindingState.WARN,
                    f"{len(devices)} GPUs with differing compute capabilities "
                    f"({', '.join(architectures)}). A build targeting one produces "
                    "kernels the other cannot run, and the failure -- 'no kernel image "
                    "is available for execution on the device' -- names neither the "
                    "device nor the architecture.",
                    evidence=(
                        Evidence(
                            source="command",
                            command=("nvidia-smi", "--query-gpu=index,name,compute_cap"),
                            excerpt="; ".join(
                                f"{d.index}: {d.name} sm_{d.compute_capability}" for d in devices
                            ),
                        ),
                    ),
                    detected=", ".join(architectures),
                    component="gpu",
                    remediation_hint=(
                        "Build for every architecture present -- TORCH_CUDA_ARCH_LIST "
                        "or CMAKE_CUDA_ARCHITECTURES covering them all -- or pin the "
                        "job to one device with CUDA_VISIBLE_DEVICES."
                    ),
                )
            )

        return ProbeResult(
            self.id, findings=tuple(findings), data={"stack": stack.model_dump(mode="json")}
        )

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
        return "GPU/AI stack: " + (
            "; ".join(parts) if parts else "no GPU development stack detected"
        )
