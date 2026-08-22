"""ai-gpu rule pack: report real detected compatibility only."""

from __future__ import annotations

from devrepro.core.models import Evidence, Finding, FindingState
from devrepro.rules.base import RuleContext

__all__ = ["evaluate"]


def evaluate(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    gpu = ctx.gpu
    ai_reqs = [
        r for r in ctx.requirements
        if r.ecosystem in ("python", "generic")
        and any(k in r.name.lower() for k in ("torch", "tensorflow", "cuda", "onnxruntime", "jax"))
    ]
    if gpu is None:
        if ai_reqs:
            findings.append(
                Finding(
                    rule_id="gpu/state-unknown",
                    state=FindingState.UNKNOWN,
                    summary="AI dependencies declared but GPU stack could not be probed.",
                    evidence=(Evidence(source="system", excerpt="no gpu probe result"),),
                    component="gpu",
                )
            )
        return findings

    if ai_reqs and not (gpu.nvidia_driver or gpu.rocm or gpu.oneapi or gpu.metal):
        findings.append(
            Finding(
                rule_id="gpu/no-accelerator",
                state=FindingState.WARN,
                summary="AI frameworks are project dependencies but no GPU/AI accelerator "
                "stack was detected; training/inference will fall back to CPU.",
                evidence=(Evidence(source="command", excerpt="nvidia-smi/rocminfo/sycl-ls all absent"),),
                component="gpu",
            )
        )
    if gpu.nvidia_driver and gpu.cuda_toolkit is None and ai_reqs:
        findings.append(
            Finding(
                rule_id="gpu/cuda-toolkit-missing",
                state=FindingState.INFO,
                summary=f"NVIDIA driver {gpu.nvidia_driver} present but CUDA toolkit (nvcc) "
                "not found — building CUDA extensions from source will fail.",
                evidence=(Evidence(source="command", command=("nvcc", "--version"),
                                   excerpt="nvcc not found"),),
                component="cuda",
                remediation_hint="Install the CUDA toolkit matching your framework's "
                "supported versions (MEDIUM risk).",
            )
        )
    return findings